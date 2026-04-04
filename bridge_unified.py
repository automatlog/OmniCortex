#!/usr/bin/env python3
"""
bridge_unified.py — Single-process FreeSWITCH <-> PersonaPlex voice bridge.

Runs on the FreeSWITCH machine. Combines bridge_in + brain_orchestrator + bridge_out:

  1. Accepts audio_fork WebSocket from FS dialplan on /freeswitch/{call_id}
  2. Connects directly to PersonaPlex WS (Opus encode/decode, silence pump)
  3. Plays PersonaPlex responses back to caller via edge-tts + uuid_broadcast

Dialplan example:
  <action application="audio_fork" data="start ws://127.0.0.1:8090/freeswitch?call_uuid=${uuid} 16k"/>
  <action application="park"/>
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import re
import shlex
import ssl
import struct
import time
import urllib.parse
from typing import Dict, Optional

import aiohttp
import numpy as np
import sphn
from aiohttp import web

try:
    import edge_tts
    HAS_EDGE_TTS = True
except Exception:
    HAS_EDGE_TTS = False

try:
    from core.voice.asr_engine import get_asr_engine
    HAS_LOCAL_ASR = True
except Exception:
    HAS_LOCAL_ASR = False
    get_asr_engine = None


LOG = logging.getLogger("bridge")

# PersonaPlex frame kinds
FRAME_HANDSHAKE = 0x00
FRAME_AUDIO = 0x01
FRAME_TEXT = 0x02
FRAME_CTRL = 0x03

STOP_PHRASES = [
    "stop", "wait", "hold on", "pause", "one second", "just a second",
    "interrupt", "cancel", "stop talking", "please stop", "enough",
    "quiet", "mute", "shut up",
]

TTS_VOICE_MAP = {
    "en": "en-US-AriaNeural", "hi": "hi-IN-SwaraNeural",
    "gu": "gu-IN-DhwaniNeural", "ta": "ta-IN-PallaviNeural",
    "te": "te-IN-ShrutiNeural", "mr": "mr-IN-AarohiNeural",
    "bn": "bn-IN-TanishaaNeural", "kn": "kn-IN-SapnaNeural",
    "ml": "ml-IN-SobhanaNeural", "ur": "ur-PK-UzmaNeural",
}


# ── Helpers ──────────────────────────────────────────────────────────

def _to_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int16_bytes_to_float32(payload: bytes) -> np.ndarray:
    if not payload:
        return np.zeros((0,), dtype=np.float32)
    return np.frombuffer(payload, dtype=np.int16).astype(np.float32) / 32768.0


def _float32_to_int16_bytes(samples: np.ndarray) -> bytes:
    return (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()


def _resample_linear(samples: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr or samples.size == 0:
        return samples.astype(np.float32, copy=False)
    src_len = samples.shape[0]
    dst_len = int(round(src_len * float(dst_sr) / float(src_sr)))
    if dst_len <= 1:
        return np.zeros((0,), dtype=np.float32)
    src_x = np.linspace(0.0, 1.0, num=src_len, endpoint=True)
    dst_x = np.linspace(0.0, 1.0, num=dst_len, endpoint=True)
    return np.interp(dst_x, src_x, samples).astype(np.float32)


def _rms(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples))))


def _normalize_phrase_text(text: str) -> str:
    return " ".join(
        "".join(ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in (text or "")).split()
    )


def _match_stop_phrase(text: str) -> str:
    normalized = f" {_normalize_phrase_text(text)} "
    for phrase in STOP_PHRASES:
        if f" {phrase} " in normalized:
            return phrase
    return ""


def _detect_text_language(text: str) -> str:
    if not text or len(text.strip()) < 3:
        return "en"
    devanagari = sum(1 for c in text if '\u0900' <= c <= '\u097F')
    total = len(text.replace(" ", ""))
    if total == 0:
        return "en"
    threshold = total * 0.2
    if devanagari > threshold:
        return "hi"
    return "en"


def _extract_sentences(buffer: str) -> tuple[list[str], str]:
    sentences: list[str] = []
    working = buffer
    while True:
        split_idx = -1
        for end_ch in ".!?\n":
            idx = working.find(end_ch)
            if idx == -1:
                continue
            if end_ch == "." and idx > 0 and idx < len(working) - 1:
                if working[idx - 1].isdigit() and working[idx + 1].isdigit():
                    continue
            split_idx = idx
            break
        if split_idx == -1:
            break
        sentence = working[: split_idx + 1].strip()
        working = working[split_idx + 1:]
        cleaned = sentence.replace("\u2581", " ").strip()
        if len(cleaned) > 2:
            sentences.append(cleaned)
    return sentences, working


def _write_wav(path: str, pcm_data: bytes, sample_rate: int) -> None:
    data_size = len(pcm_data)
    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))
        f.write(struct.pack("<H", 1))  # PCM
        f.write(struct.pack("<H", 1))  # mono
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I", sample_rate * 2))
        f.write(struct.pack("<H", 2))
        f.write(struct.pack("<H", 16))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(pcm_data)


def _resolve_call_id(request: web.Request) -> str:
    candidates = [
        request.query.get("call_uuid"),
        request.query.get("uuid"),
        request.match_info.get("call_id"),
        request.headers.get("x-call-uuid"),
    ]
    for value in candidates:
        call_id = str(value or "").strip()
        if call_id:
            return call_id
    raise web.HTTPBadRequest(text="call UUID missing")


# ── Session ──────────────────────────────────────────────────────────

class BridgeSession:
    """One per call. Manages PersonaPlex connection, TTS, and barge-in."""

    def __init__(self, call_id: str, cfg: dict) -> None:
        self.call_id = call_id
        self.cfg = cfg
        self.closed = False

        # PersonaPlex connection
        self.pp_ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.http_session: Optional[aiohttp.ClientSession] = None
        self._handshake_event = asyncio.Event()
        self._upstream_send_lock = asyncio.Lock()
        self._last_upstream_audio_send = 0.0

        # Opus encode/decode
        self.moshi_sr = int(cfg["moshi_sample_rate"])
        self.fs_sr = int(cfg["fs_sample_rate"])
        self.opus_writer = sphn.OpusStreamWriter(self.moshi_sr)
        self.opus_reader = sphn.OpusStreamReader(self.moshi_sr)

        # TTS state
        self.tts_queue: asyncio.Queue = asyncio.Queue()
        self.tts_active = False
        self.tts_playing = False
        self.tts_generation = 0
        self.suppress_tts_until = 0.0
        self.text_buf = ""
        self.last_text_time = 0.0
        self.text_lang_buf = ""
        self.tts_voice = str(cfg["tts_voice"])

        # Barge-in
        self.phrase_audio_queue: asyncio.Queue = asyncio.Queue(maxsize=64)

        # Stats
        self.frames_in = 0
        self.frames_out = 0

    async def connect_personaplex(self) -> None:
        url = str(self.cfg["personaplex_ws"])
        timeout = aiohttp.ClientTimeout(total=float(self.cfg["upstream_timeout_sec"]))
        ssl_ctx: object = False
        if url.startswith("wss://"):
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

        self.http_session = aiohttp.ClientSession(timeout=timeout)
        self.pp_ws = await self.http_session.ws_connect(url, ssl=ssl_ctx)
        LOG.info("[%s] connected to PersonaPlex: %s", self.call_id, url.split("?")[0])

    async def wait_handshake(self, timeout: float = 15.0) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._handshake_event.wait(), timeout=timeout)

    async def send_pcm_to_pp(self, pcm_fs: np.ndarray) -> int:
        """Resample FS PCM → Moshi rate, Opus encode, send with FRAME_AUDIO prefix."""
        if pcm_fs.size == 0 or self.pp_ws is None or self.pp_ws.closed:
            return 0
        pcm_moshi = _resample_linear(pcm_fs, self.fs_sr, self.moshi_sr)
        if pcm_moshi.size == 0:
            return 0
        frames_sent = 0
        async with self._upstream_send_lock:
            self.opus_writer.append_pcm(pcm_moshi.astype(np.float32, copy=False))
            while True:
                opus_payload = self.opus_writer.read_bytes()
                if not opus_payload:
                    break
                if self.pp_ws is None or self.pp_ws.closed:
                    break
                await self.pp_ws.send_bytes(bytes([FRAME_AUDIO]) + opus_payload)
                frames_sent += 1
            if frames_sent > 0:
                self._last_upstream_audio_send = time.monotonic()
        return frames_sent

    async def cancel_tts(self, reason: str) -> None:
        self.tts_generation += 1
        self.text_buf = ""
        self.tts_active = False
        self.tts_playing = False
        self.suppress_tts_until = time.monotonic() + float(self.cfg.get("tts_suppress_after_barge_sec", 1.75))
        drained = 0
        while True:
            try:
                self.tts_queue.get_nowait()
                drained += 1
            except asyncio.QueueEmpty:
                break
        LOG.info("[%s] cancel_tts reason=%s drained=%d", self.call_id, reason, drained)
        fs_cli = str(self.cfg["fs_cli"])
        try:
            proc = await asyncio.create_subprocess_exec(
                fs_cli, "-x", f"uuid_break {self.call_id} all",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        except Exception as exc:
            LOG.warning("[%s] uuid_break failed: %s", self.call_id, exc)

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.pp_ws is not None and not self.pp_ws.closed:
            with contextlib.suppress(Exception):
                await self.pp_ws.close()
        if self.http_session is not None and not self.http_session.closed:
            await self.http_session.close()
        LOG.info("[%s] session closed in=%d out=%d", self.call_id, self.frames_in, self.frames_out)


# ── Coroutines ───────────────────────────────────────────────────────

async def _silence_pump(session: BridgeSession) -> None:
    """Feed silence to PersonaPlex when no real audio is arriving."""
    await session.wait_handshake()
    frame_ms = 20
    samples = max(1, int(round(session.moshi_sr * (frame_ms / 1000.0))))
    silence = np.zeros((samples,), dtype=np.float32)
    silence_writer = sphn.OpusStreamWriter(session.moshi_sr)
    tick = frame_ms / 1000.0
    LOG.info("[%s] silence pump started", session.call_id)

    while not session.closed:
        await asyncio.sleep(tick)
        if session.pp_ws is None or session.pp_ws.closed:
            return
        if time.monotonic() - session._last_upstream_audio_send < 0.025:
            continue
        async with session._upstream_send_lock:
            silence_writer.append_pcm(silence)
            while True:
                opus_payload = silence_writer.read_bytes()
                if not opus_payload:
                    break
                if session.pp_ws is None or session.pp_ws.closed:
                    return
                await session.pp_ws.send_bytes(bytes([FRAME_AUDIO]) + opus_payload)
            session._last_upstream_audio_send = time.monotonic()


async def _pp_reader(session: BridgeSession) -> None:
    """Read from PersonaPlex: decode text tokens → TTS queue."""
    assert session.pp_ws is not None
    text_byte_buf = bytearray()

    async for msg in session.pp_ws:
        if msg.type == aiohttp.WSMsgType.ERROR:
            raise RuntimeError(f"PersonaPlex ws error: {session.pp_ws.exception()}")
        if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
            break
        if msg.type != aiohttp.WSMsgType.BINARY:
            continue
        data = bytes(msg.data)
        if not data:
            continue
        kind = data[0]
        payload = data[1:]

        if kind == FRAME_HANDSHAKE:
            session._handshake_event.set()
            LOG.info("[%s] PersonaPlex handshake", session.call_id)
            continue

        if kind == FRAME_TEXT and payload:
            # Accumulate bytes for multi-byte UTF-8 reassembly
            text_byte_buf.extend(payload)
            try:
                token = text_byte_buf.decode("utf-8")
                text_byte_buf.clear()
            except UnicodeDecodeError:
                if len(text_byte_buf) > 6:
                    token = text_byte_buf.decode("utf-8", errors="replace")
                    text_byte_buf.clear()
                else:
                    continue

            LOG.info("[%s] text: \"%s\"", session.call_id, token.replace("\u2581", " ").strip())
            session.last_text_time = time.monotonic()
            session.text_buf += token

            # Language detection
            session.text_lang_buf += token
            if len(session.text_lang_buf) > 30:
                lang = _detect_text_language(session.text_lang_buf)
                new_voice = TTS_VOICE_MAP.get(lang, str(session.cfg["tts_voice"]))
                if new_voice != session.tts_voice:
                    LOG.info("[%s] TTS voice switch: %s -> %s", session.call_id, session.tts_voice, new_voice)
                    session.tts_voice = new_voice
                session.text_lang_buf = ""

            # Extract sentences
            complete, remainder = _extract_sentences(session.text_buf)
            session.text_buf = remainder
            for sentence in complete:
                if time.monotonic() >= session.suppress_tts_until:
                    session.tts_queue.put_nowait(sentence)
                    LOG.info("[%s] TTS queued: \"%s\"", session.call_id, sentence)

        elif kind == FRAME_AUDIO:
            session.frames_out += 1  # count but don't play — TTS handles output

        elif kind == FRAME_CTRL:
            LOG.debug("[%s] PP ctrl: %s", session.call_id, payload.decode("utf-8", errors="ignore"))


async def _tts_worker(session: BridgeSession) -> None:
    """Take sentences from queue, edge-tts → WAV → uuid_broadcast."""
    if not HAS_EDGE_TTS:
        LOG.warning("[%s] edge-tts unavailable", session.call_id)
        return

    tts_dir = str(session.cfg["tts_dir"])
    os.makedirs(tts_dir, exist_ok=True)
    output_sr = int(session.cfg["fs_sample_rate"])
    tts_count = 0

    while True:
        text = await session.tts_queue.get()
        if text is None:
            return

        job_gen = session.tts_generation
        stamp = int(time.time() * 1000)
        mp3_path = os.path.join(tts_dir, f"{session.call_id[:8]}_tts_{stamp}.mp3")
        wav_path = os.path.join(tts_dir, f"{session.call_id[:8]}_tts_{stamp}.wav")
        try:
            if time.monotonic() < session.suppress_tts_until:
                LOG.info("[%s] TTS skipped (suppressed after barge-in)", session.call_id)
                continue

            session.tts_active = True
            LOG.info("[%s] TTS generating: \"%s\" voice=%s", session.call_id, text, session.tts_voice)
            await edge_tts.Communicate(text, session.tts_voice).save(mp3_path)
            if job_gen != session.tts_generation:
                continue

            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", mp3_path,
                "-ar", str(output_sr), "-ac", "1", "-sample_fmt", "s16",
                wav_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, err = await proc.communicate()
            if proc.returncode != 0:
                LOG.warning("[%s] ffmpeg failed: %s", session.call_id, err.decode(errors="ignore").strip())
                continue
            if job_gen != session.tts_generation:
                continue

            # uuid_broadcast
            fs_cli = str(session.cfg["fs_cli"])
            cmd = f"uuid_broadcast {session.call_id} {shlex.quote(wav_path)} aleg"
            proc = await asyncio.create_subprocess_exec(
                fs_cli, "-x", cmd,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            out, _ = await proc.communicate()
            result = out.decode(errors="ignore").strip()
            if "+OK" not in result and job_gen == session.tts_generation:
                LOG.warning("[%s] uuid_broadcast: %s", session.call_id, result)
                continue
            if job_gen != session.tts_generation:
                continue

            tts_count += 1
            session.tts_playing = True
            wav_size = os.path.getsize(wav_path) if os.path.exists(wav_path) else 0
            wav_duration = wav_size / max(1, output_sr * 2)
            LOG.info(
                "[%s] TTS #%d playing: %.1fs \"%s\"",
                session.call_id, tts_count, wav_duration, text[:60],
            )
            remaining = max(0.2, wav_duration + 0.35)
            while remaining > 0 and session.tts_generation == job_gen:
                await asyncio.sleep(min(0.1, remaining))
                remaining -= 0.1

        except FileNotFoundError as exc:
            LOG.warning("[%s] TTS dep missing: %s", session.call_id, exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOG.warning("[%s] TTS failed: %s", session.call_id, exc)
        finally:
            session.tts_active = False
            session.tts_playing = False
            for path in (mp3_path, wav_path):
                with contextlib.suppress(Exception):
                    if path and os.path.exists(path):
                        os.unlink(path)


async def _text_flusher(session: BridgeSession) -> None:
    """Flush partial text buffer after silence gap."""
    flush_after = float(session.cfg.get("tts_flush_after_sec", 1.25))
    while not session.closed:
        await asyncio.sleep(0.5)
        if not session.text_buf:
            continue
        if time.monotonic() - session.last_text_time < flush_after:
            continue
        cleaned = session.text_buf.replace("\u2581", " ").strip()
        session.text_buf = ""
        if len(cleaned) > 2 and time.monotonic() >= session.suppress_tts_until:
            session.tts_queue.put_nowait(cleaned)
            LOG.info("[%s] TTS flushed: \"%s\"", session.call_id, cleaned)


async def _phrase_barge_worker(session: BridgeSession) -> None:
    """Listen for stop phrases in caller audio during TTS playback."""
    if not HAS_LOCAL_ASR:
        LOG.info("[%s] phrase barge-in disabled (no ASR)", session.call_id)
        return

    asr = await get_asr_engine()
    if asr is None:
        return

    fs_sr = int(session.cfg["fs_sample_rate"])
    min_samples = max(1, int(fs_sr * 0.8))
    max_samples = max(min_samples, int(fs_sr * 2.5))
    last_check = 0.0
    pcm_window = np.zeros((0,), dtype=np.float32)
    LOG.info("[%s] phrase barge-in enabled", session.call_id)

    while not session.closed:
        chunk = await session.phrase_audio_queue.get()
        try:
            if chunk is None:
                return
            if not (session.tts_active or session.tts_playing):
                pcm_window = np.zeros((0,), dtype=np.float32)
                continue
            if chunk.size == 0:
                continue

            if _rms(chunk) < 0.012:
                if pcm_window.size > max_samples:
                    pcm_window = pcm_window[-max_samples:]
                continue

            pcm_window = np.concatenate([pcm_window, chunk])
            if pcm_window.size > max_samples:
                pcm_window = pcm_window[-max_samples:]
            if pcm_window.size < min_samples:
                continue

            now = time.monotonic()
            if now - last_check < 0.8:
                continue
            last_check = now

            transcript, confidence, detected_lang = await asr.transcribe(
                pcm_window.copy(), sample_rate=fs_sr,
            )
            transcript = (transcript or "").strip()
            if transcript:
                LOG.info("[%s] barge ASR: \"%s\" (conf=%.2f)", session.call_id, transcript, confidence)
            phrase = _match_stop_phrase(transcript)
            if phrase:
                await session.cancel_tts(f"stop_phrase:{phrase}")
                pcm_window = np.zeros((0,), dtype=np.float32)
            elif pcm_window.size >= max_samples:
                pcm_window = pcm_window[-min_samples:]
        finally:
            session.phrase_audio_queue.task_done()


# ── WebSocket handler ────────────────────────────────────────────────

async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    """Handle audio_fork WebSocket from FreeSWITCH."""
    cfg = request.app["cfg"]
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    call_id = "-"
    session: Optional[BridgeSession] = None

    try:
        call_id = _resolve_call_id(request)
        session = BridgeSession(call_id, cfg)
        LOG.info("[%s] call started remote=%s", call_id, request.remote or "-")

        # Connect to PersonaPlex
        await session.connect_personaplex()

        # Start background tasks
        tasks = []
        tasks.append(asyncio.create_task(_silence_pump(session), name=f"silence-{call_id}"))
        tasks.append(asyncio.create_task(_pp_reader(session), name=f"pp-reader-{call_id}"))
        tasks.append(asyncio.create_task(_tts_worker(session), name=f"tts-{call_id}"))
        tasks.append(asyncio.create_task(_text_flusher(session), name=f"flusher-{call_id}"))
        if HAS_LOCAL_ASR and cfg.get("barge_in_enabled", True):
            tasks.append(asyncio.create_task(_phrase_barge_worker(session), name=f"barge-{call_id}"))

        # Wait for handshake before forwarding audio
        await session.wait_handshake()
        LOG.info("[%s] PersonaPlex handshake done, forwarding audio", call_id)

        # Main loop: read audio from FS, forward to PersonaPlex
        async for msg in ws:
            if msg.type == web.WSMsgType.ERROR:
                raise RuntimeError(f"FS ws error: {ws.exception()}")
            if msg.type in (web.WSMsgType.CLOSE, web.WSMsgType.CLOSED):
                break
            if msg.type == web.WSMsgType.BINARY:
                data = bytes(msg.data)
                if not data:
                    continue
                pcm_fs = _int16_bytes_to_float32(data)
                session.frames_in += await session.send_pcm_to_pp(pcm_fs)

                if session.frames_in <= 3 or session.frames_in % 200 == 0:
                    LOG.info("[%s] FS audio frame #%d (%d bytes, rms=%.4f)",
                             call_id, session.frames_in, len(data), _rms(pcm_fs))

                # Feed barge-in detector
                if session.tts_active or session.tts_playing:
                    try:
                        session.phrase_audio_queue.put_nowait(pcm_fs.copy())
                    except asyncio.QueueFull:
                        with contextlib.suppress(asyncio.QueueEmpty):
                            session.phrase_audio_queue.get_nowait()
                            session.phrase_audio_queue.task_done()
                        with contextlib.suppress(asyncio.QueueFull):
                            session.phrase_audio_queue.put_nowait(pcm_fs.copy())

            elif msg.type == web.WSMsgType.TEXT:
                LOG.debug("[%s] FS text: %s", call_id, msg.data)

    except web.HTTPException as exc:
        LOG.warning("[%s] rejected: %s", call_id, exc.text)
        if not ws.closed:
            await ws.send_str(exc.text or "error")
            await ws.close(code=1008)
    except Exception as exc:
        LOG.exception("[%s] bridge failed: %s", call_id, exc)
        if not ws.closed:
            await ws.close(code=1011, message=b"bridge failed")
    finally:
        # Cleanup
        if session is not None:
            session.tts_queue.put_nowait(None)
            with contextlib.suppress(asyncio.QueueFull):
                session.phrase_audio_queue.put_nowait(None)
            await session.close()
        for task in tasks if 'tasks' in dir() else []:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if not ws.closed:
            await ws.close()
        LOG.info("[%s] call ended", call_id)
    return ws


async def health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


# ── CLI ──────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Unified FS <-> PersonaPlex voice bridge")
    p.add_argument("--host", default=os.getenv("BRIDGE_HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.getenv("BRIDGE_PORT", "8090")))
    p.add_argument("--endpoint", default=os.getenv("BRIDGE_ENDPOINT", "/freeswitch"))
    p.add_argument(
        "--personaplex-ws",
        default=os.getenv("PERSONAPLEX_WS", ""),
        help="PersonaPlex WebSocket URL (e.g. ws://198.13.252.19:14484/api/chat?text_prompt=...)",
    )
    p.add_argument("--fs-sample-rate", type=int, default=int(os.getenv("BRIDGE_FS_SR", "16000")),
                    help="Sample rate from audio_fork (usually 16000 for 16k mode)")
    p.add_argument("--moshi-sample-rate", type=int, default=int(os.getenv("BRIDGE_MOSHI_SR", "24000")))
    p.add_argument("--fs-cli", default=os.getenv("BRIDGE_FS_CLI", "/usr/local/freeswitch/bin/fs_cli"))
    p.add_argument("--tts-voice", default=os.getenv("BRIDGE_TTS_VOICE", "en-US-AriaNeural"))
    p.add_argument("--tts-dir", default=os.getenv("BRIDGE_TTS_DIR", "/tmp/bridge_tts"))
    p.add_argument("--tts-flush-after-sec", type=float,
                    default=float(os.getenv("BRIDGE_TTS_FLUSH_SEC", "1.25")))
    p.add_argument("--tts-suppress-after-barge-sec", type=float,
                    default=float(os.getenv("BRIDGE_TTS_SUPPRESS_SEC", "1.75")))
    p.add_argument("--barge-in-enabled", action="store_true",
                    default=_to_bool(os.getenv("BRIDGE_BARGE_IN", "1")))
    p.add_argument("--upstream-timeout-sec", type=float,
                    default=float(os.getenv("BRIDGE_TIMEOUT_SEC", "1800")))
    p.add_argument("--log-level", default=os.getenv("BRIDGE_LOG_LEVEL", "INFO"))
    return p


def main() -> None:
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.personaplex_ws:
        raise RuntimeError("--personaplex-ws is required (PersonaPlex WebSocket URL)")

    app = web.Application()
    app["cfg"] = {
        "personaplex_ws": args.personaplex_ws,
        "fs_sample_rate": args.fs_sample_rate,
        "moshi_sample_rate": args.moshi_sample_rate,
        "fs_cli": args.fs_cli,
        "tts_voice": args.tts_voice,
        "tts_dir": args.tts_dir,
        "tts_flush_after_sec": max(0.25, args.tts_flush_after_sec),
        "tts_suppress_after_barge_sec": max(0.1, args.tts_suppress_after_barge_sec),
        "barge_in_enabled": args.barge_in_enabled,
        "upstream_timeout_sec": args.upstream_timeout_sec,
    }
    app.router.add_get(args.endpoint, ws_handler)
    app.router.add_get(f"{args.endpoint}/{{call_id}}", ws_handler)
    app.router.add_get("/health", health)

    LOG.info(
        "starting bridge host=%s port=%s endpoint=%s personaplex=%s fs_sr=%d moshi_sr=%d tts=%s barge=%s",
        args.host, args.port, args.endpoint,
        args.personaplex_ws.split("?")[0],
        args.fs_sample_rate, args.moshi_sample_rate,
        args.tts_voice, args.barge_in_enabled,
    )
    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        main()
