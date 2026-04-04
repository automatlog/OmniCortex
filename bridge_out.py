#!/usr/bin/env python3
"""
bridge_out.py

Outbound telephony bridge:
- Accepts media websocket consumer on /speak
- Pulls synthesized audio from brain_orchestrator /egress/{call_id}
- Streams frames back to caller-facing leg
- Also exposes HTTP stream /stream/{call_id} for dialplan playback()
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib

try:
    import audioop
except ImportError:
    audioop = None
import json
import logging
import os
import shlex
import ssl
import struct
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Dict, Optional

import aiohttp
from aiohttp import web

try:
    import edge_tts
    HAS_EDGE_TTS = True
except Exception:
    HAS_EDGE_TTS = False


LOG = logging.getLogger("bridge_out")

DEFAULT_ORCH_EGRESS_WS = "ws://127.0.0.1:8101/egress"
DEFAULT_FS_CLI = os.getenv("BRIDGE_OUT_FS_CLI", "/usr/local/freeswitch/bin/fs_cli")
DEFAULT_TTS_DIR = os.getenv("BRIDGE_OUT_TTS_DIR", "/tmp/bridge_out_tts")
DEFAULT_TTS_VOICE = os.getenv("BRIDGE_OUT_TTS_VOICE", "en-US-AriaNeural")


def _to_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _require_call_uuid(request: web.Request) -> str:
    call_id = str(request.query.get("call_uuid") or "").strip()
    if not call_id:
        raise web.HTTPBadRequest(text="call_uuid query param is required")
    return call_id


def _build_orchestrator_url(base: str, call_id: str, query: Dict[str, str]) -> str:
    suffix = f"/{urllib.parse.quote(call_id, safe='')}"
    return f"{base.rstrip('/')}{suffix}"


def _build_orchestrator_headers(query: Dict[str, str]) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    header_map = {
        "agent_id": "x-voice-agent-id",
        "token": "x-voice-token",
        "voice_prompt": "x-voice-prompt",
        "seed": "x-voice-seed",
        "context_query": "x-voice-context-query",
        "x_user_id": "x-user-id",
    }
    for key, header_name in header_map.items():
        value = str(query.get(key) or "").strip()
        if value:
            headers[header_name] = value
    return headers


def _normalize_call_id(raw_call_id: str) -> str:
    """
    Accept both:
      /stream/{call_id}
      /stream/{call_id}.raw
    and normalize to plain call UUID.
    """
    call_id = str(raw_call_id or "").strip()
    if call_id.lower().endswith(".raw"):
        call_id = call_id[:-4]
    return call_id


def _normalize_http_audio_chunk(
    audio_bytes: bytes,
    source_sample_rate: int,
    output_sample_rate: int,
    rate_state,
) -> tuple[bytes, object]:
    if not audio_bytes:
        return b"", rate_state
    if audioop is None:
        # If audioop is unavailable, return audio as-is without resampling
        return audio_bytes, rate_state
    if source_sample_rate == output_sample_rate:
        return audio_bytes, rate_state
    converted, next_state = audioop.ratecv(
        audio_bytes,
        2,
        1,
        source_sample_rate,
        output_sample_rate,
        rate_state,
    )
    return converted, next_state


def _silence_chunk_bytes(sample_rate: int, frame_ms: int) -> bytes:
    samples = max(1, int(round(sample_rate * (frame_ms / 1000.0))))
    return b"\x00\x00" * samples


@dataclass
class CallState:
    call_id: str
    tts_queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    tts_task: Optional[asyncio.Task] = None
    flush_task: Optional[asyncio.Task] = None
    generation: int = 0
    tts_active: bool = False
    tts_playing: bool = False
    sentence_buf: str = ""
    last_text_time: float = 0.0
    upstream_audio_seen: bool = False
    last_binary_audio_at: float = 0.0
    upstream_ws: Optional[aiohttp.ClientWebSocketResponse] = None
    upstream_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


async def _get_call_state(app: web.Application, call_id: str) -> CallState:
    registry: Dict[str, CallState] = app["call_states"]
    state = registry.get(call_id)
    if state is None:
        state = CallState(call_id=call_id)
        registry[call_id] = state
    return state


async def _send_upstream_control(state: CallState, payload: Dict[str, object]) -> None:
    if state.upstream_ws is None or state.upstream_ws.closed:
        return
    async with state.upstream_lock:
        if state.upstream_ws is None or state.upstream_ws.closed:
            return
        await state.upstream_ws.send_str(json.dumps(payload))


async def _set_tts_state(state: CallState, active: bool, playing: bool) -> None:
    changed = (state.tts_active != active) or (state.tts_playing != playing)
    state.tts_active = active
    state.tts_playing = playing
    if changed:
        await _send_upstream_control(
            state,
            {
                "type": "tts_state",
                "active": active,
                "playing": playing,
            },
        )


async def _cancel_tts(cfg: Dict[str, object], state: CallState, reason: str) -> None:
    state.generation += 1
    state.sentence_buf = ""
    drained = 0
    while True:
        try:
            state.tts_queue.get_nowait()
            drained += 1
        except asyncio.QueueEmpty:
            break

    await _set_tts_state(state, active=False, playing=False)
    LOG.info("[%s] cancel tts reason=%s drained=%d", state.call_id, reason, drained)

    fs_cli = str(cfg["fs_cli"])
    try:
        proc = await asyncio.create_subprocess_exec(
            fs_cli,
            "-x",
            f"uuid_break {state.call_id} all",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            LOG.warning(
                "[%s] uuid_break failed rc=%s out=%s err=%s",
                state.call_id,
                proc.returncode,
                out.decode(errors="ignore").strip(),
                err.decode(errors="ignore").strip(),
            )
    except FileNotFoundError:
        LOG.warning("[%s] fs_cli not found at %s", state.call_id, fs_cli)
    except Exception as exc:
        LOG.warning("[%s] uuid_break failed: %s", state.call_id, exc)


async def _tts_worker(cfg: Dict[str, object], state: CallState) -> None:
    if not cfg["tts_enabled"]:
        return
    if not HAS_EDGE_TTS:
        LOG.warning("[%s] edge-tts unavailable; text TTS fallback disabled", state.call_id)
        return

    os.makedirs(str(cfg["tts_dir"]), exist_ok=True)
    while True:
        text = await state.tts_queue.get()
        if text is None:
            return

        job_generation = state.generation
        stamp = int(time.time() * 1000)
        mp3_path = os.path.join(str(cfg["tts_dir"]), f"{state.call_id[:8]}_{stamp}.mp3")
        wav_path = os.path.join(str(cfg["tts_dir"]), f"{state.call_id[:8]}_{stamp}.wav")
        try:
            await _set_tts_state(state, active=True, playing=False)
            await edge_tts.Communicate(text, str(cfg["tts_voice"])).save(mp3_path)
            if job_generation != state.generation:
                continue

            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                mp3_path,
                "-ar",
                str(cfg["output_sample_rate"]),
                "-ac",
                "1",
                "-sample_fmt",
                "s16",
                wav_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, err = await proc.communicate()
            if proc.returncode != 0:
                LOG.warning("[%s] ffmpeg failed: %s", state.call_id, err.decode(errors="ignore").strip())
                continue
            if job_generation != state.generation:
                continue

            fs_cli = str(cfg["fs_cli"])
            cmd = f"uuid_broadcast {state.call_id} {shlex.quote(wav_path)} aleg"
            proc = await asyncio.create_subprocess_exec(
                fs_cli,
                "-x",
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await proc.communicate()
            if proc.returncode != 0:
                LOG.warning(
                    "[%s] uuid_broadcast failed rc=%s out=%s err=%s",
                    state.call_id,
                    proc.returncode,
                    out.decode(errors="ignore").strip(),
                    err.decode(errors="ignore").strip(),
                )
                continue
            if job_generation != state.generation:
                continue

            await _set_tts_state(state, active=True, playing=True)
            wav_size = os.path.getsize(wav_path) if os.path.exists(wav_path) else 0
            wav_duration = wav_size / max(1, int(cfg["output_sample_rate"]) * 2)
            remaining = max(0.2, wav_duration + 0.35)
            while remaining > 0 and state.generation == job_generation:
                await asyncio.sleep(min(0.1, remaining))
                remaining -= 0.1
        except FileNotFoundError as exc:
            LOG.warning("[%s] TTS dependency missing: %s", state.call_id, exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOG.warning("[%s] TTS worker failed: %s", state.call_id, exc)
        finally:
            await _set_tts_state(state, active=False, playing=False)
            for path in (mp3_path, wav_path):
                with contextlib.suppress(Exception):
                    if path and os.path.exists(path):
                        os.unlink(path)


async def _ensure_tts_worker(cfg: Dict[str, object], state: CallState) -> None:
    if state.tts_task is None or state.tts_task.done():
        state.tts_task = asyncio.create_task(
            _tts_worker(cfg, state),
            name=f"bridge_out-tts-{state.call_id}",
        )


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
        working = working[split_idx + 1 :]
        cleaned = sentence.replace("\u2581", " ").strip()
        if len(cleaned) > 2:
            sentences.append(cleaned)
    return sentences, working


async def _maybe_enqueue_tts(cfg: Dict[str, object], state: CallState, text: str) -> None:
    if not cfg["tts_enabled"]:
        return
    if state.upstream_audio_seen:
        return
    await _ensure_tts_worker(cfg, state)
    await state.tts_queue.put(text)


async def _text_flush_worker(cfg: Dict[str, object], state: CallState) -> None:
    flush_after = float(cfg["tts_flush_after_sec"])
    while True:
        await asyncio.sleep(0.5)
        if not state.sentence_buf:
            continue
        if state.upstream_audio_seen:
            state.sentence_buf = ""
            continue
        if time.monotonic() - state.last_text_time < flush_after:
            continue
        cleaned = state.sentence_buf.replace("\u2581", " ").strip()
        state.sentence_buf = ""
        if len(cleaned) > 2:
            await _maybe_enqueue_tts(cfg, state, cleaned)


async def _ensure_text_flush_worker(cfg: Dict[str, object], state: CallState) -> None:
    if state.flush_task is None or state.flush_task.done():
        state.flush_task = asyncio.create_task(
            _text_flush_worker(cfg, state),
            name=f"bridge_out-flush-{state.call_id}",
        )


async def _handle_upstream_text(
    cfg: Dict[str, object],
    state: CallState,
    text: str,
    client_ws: Optional[web.WebSocketResponse] = None,
) -> None:
    payload: Optional[Dict[str, object]] = None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            payload = parsed
    except Exception:
        payload = None

    if payload is not None:
        msg_type = str(payload.get("type") or "").strip().lower()
        if msg_type in {"barge_in", "cancel_tts", "interrupt"}:
            await _cancel_tts(cfg, state, msg_type or "control")
            return
        if msg_type == "assistant_text":
            text = str(payload.get("text") or "").strip()
        elif msg_type in {"tts_state", "bridge_out_ready"}:
            return

    cleaned = text.strip()
    if not cleaned:
        return

    LOG.info('[%s] bridge_out text="%s"', state.call_id, cleaned)
    if client_ws is not None and not client_ws.closed:
        await client_ws.send_str(cleaned)

    if not cfg["tts_enabled"] or state.upstream_audio_seen:
        return
    state.last_text_time = time.monotonic()
    state.sentence_buf += cleaned
    complete, remainder = _extract_sentences(state.sentence_buf)
    state.sentence_buf = remainder
    await _ensure_text_flush_worker(cfg, state)
    for sentence in complete:
        await _maybe_enqueue_tts(cfg, state, sentence)


async def _client_to_upstream_control(
    client_ws: web.WebSocketResponse,
    upstream_ws: aiohttp.ClientWebSocketResponse,
    call_id: str,
) -> None:
    async for msg in client_ws:
        if msg.type == web.WSMsgType.ERROR:
            raise RuntimeError(f"speak client ws error: {client_ws.exception()}")
        if msg.type in (web.WSMsgType.CLOSE, web.WSMsgType.CLOSED):
            break
        if msg.type == web.WSMsgType.TEXT:
            text = str(msg.data)
            LOG.debug("[%s] bridge_out control text: %s", call_id, text)
            await upstream_ws.send_str(text)


async def _upstream_to_client_audio(
    cfg: Dict[str, object],
    state: CallState,
    upstream_ws: aiohttp.ClientWebSocketResponse,
    client_ws: web.WebSocketResponse,
    call_id: str,
) -> None:
    async for msg in upstream_ws:
        if msg.type == aiohttp.WSMsgType.ERROR:
            raise RuntimeError(f"upstream egress ws error: {upstream_ws.exception()}")
        if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
            break
        if msg.type == aiohttp.WSMsgType.BINARY:
            state.upstream_audio_seen = True
            state.last_binary_audio_at = time.monotonic()
            if state.tts_active or state.tts_playing or not state.tts_queue.empty() or state.sentence_buf:
                await _cancel_tts(cfg, state, "upstream_audio")
            await client_ws.send_bytes(bytes(msg.data))
        elif msg.type == aiohttp.WSMsgType.TEXT:
            await _handle_upstream_text(cfg, state, str(msg.data), client_ws)


async def ws_speak(request: web.Request) -> web.WebSocketResponse:
    cfg = request.app["cfg"]
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    call_id = "-"
    state: Optional[CallState] = None
    try:
        call_id = _require_call_uuid(request)
        state = await _get_call_state(request.app, call_id)
        target = _build_orchestrator_url(cfg["orchestrator_egress_ws"], call_id, dict(request.query))
        headers = _build_orchestrator_headers(dict(request.query))

        timeout = aiohttp.ClientTimeout(total=cfg["upstream_timeout_sec"])
        ssl_ctx: object = False
        if target.startswith("wss://"):
            if cfg["upstream_ssl_verify"]:
                ssl_ctx = True
            else:
                ssl_ctx = ssl.create_default_context()
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE

        LOG.info("[%s] bridge_out connect orchestrator=%s", call_id, target)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(target, ssl=ssl_ctx, headers=headers or None) as upstream:
                state.upstream_ws = upstream
                await _send_upstream_control(state, {"type": "bridge_out_ready"})
                tx_task = asyncio.create_task(_upstream_to_client_audio(cfg, state, upstream, ws, call_id))
                rx_task = asyncio.create_task(_client_to_upstream_control(ws, upstream, call_id))
                done, pending = await asyncio.wait({tx_task, rx_task}, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                for task in done:
                    exc = task.exception()
                    if exc:
                        raise exc
    except web.HTTPException as exc:
        await ws.send_str(exc.text)
        await ws.close(code=1008, message=exc.text.encode("utf-8", errors="ignore"))
    except Exception as exc:
        LOG.exception("[%s] bridge_out failed: %s", call_id, exc)
        if not ws.closed:
            await ws.close(code=1011, message=b"bridge_out failed")
    finally:
        if state is not None and state.upstream_ws is not None and state.upstream_ws.closed:
            state.upstream_ws = None
        if not ws.closed:
            await ws.close()
    return ws


def _write_wav(path: str, pcm_data: bytes, sample_rate: int, channels: int = 1, sample_width: int = 2) -> None:
    """Write raw PCM16 data as a WAV file with proper headers."""
    data_size = len(pcm_data)
    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width
    # RIFF header + fmt chunk + data chunk
    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))  # file size - 8
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))  # fmt chunk size
        f.write(struct.pack("<H", 1))   # PCM format
        f.write(struct.pack("<H", channels))
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I", byte_rate))
        f.write(struct.pack("<H", block_align))
        f.write(struct.pack("<H", sample_width * 8))  # bits per sample
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(pcm_data)


async def _broadcast_wav(fs_cli: str, call_id: str, wav_path: str) -> bool:
    """Play a WAV file on a FreeSWITCH call via uuid_broadcast."""
    cmd = f"uuid_broadcast {call_id} {shlex.quote(wav_path)} aleg"
    try:
        proc = await asyncio.create_subprocess_exec(
            fs_cli, "-x", cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            LOG.warning(
                "[%s] uuid_broadcast failed rc=%s out=%s err=%s",
                call_id, proc.returncode,
                out.decode(errors="ignore").strip(),
                err.decode(errors="ignore").strip(),
            )
            return False
        return True
    except FileNotFoundError:
        LOG.warning("[%s] fs_cli not found at %s", call_id, fs_cli)
        return False
    except Exception as exc:
        LOG.warning("[%s] uuid_broadcast failed: %s", call_id, exc)
        return False


async def _broadcast_tts_worker(cfg: Dict[str, object], state: CallState) -> None:
    """
    TTS worker for broadcast_loop: takes sentences from tts_queue,
    converts via edge-tts → MP3 → ffmpeg → WAV → uuid_broadcast.
    """
    if not HAS_EDGE_TTS:
        LOG.warning("[%s] edge-tts unavailable; TTS broadcast disabled", state.call_id)
        return

    wav_dir = str(cfg["tts_dir"])
    os.makedirs(wav_dir, exist_ok=True)
    output_sr = int(cfg["output_sample_rate"])
    tts_count = 0

    while True:
        text = await state.tts_queue.get()
        if text is None:
            return

        job_gen = state.generation
        stamp = int(time.time() * 1000)
        mp3_path = os.path.join(wav_dir, f"{state.call_id[:8]}_tts_{stamp}.mp3")
        wav_path = os.path.join(wav_dir, f"{state.call_id[:8]}_tts_{stamp}.wav")
        try:
            await _set_tts_state(state, active=True, playing=False)
            LOG.info("[%s] TTS generating: \"%s\"", state.call_id, text)
            await edge_tts.Communicate(text, str(cfg["tts_voice"])).save(mp3_path)
            if job_gen != state.generation:
                continue

            # Convert MP3 → WAV at FS sample rate
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
                LOG.warning("[%s] ffmpeg failed: %s", state.call_id, err.decode(errors="ignore").strip())
                continue
            if job_gen != state.generation:
                continue

            # Play via uuid_broadcast
            ok = await _broadcast_wav(str(cfg["fs_cli"]), state.call_id, wav_path)
            if not ok:
                continue
            if job_gen != state.generation:
                continue

            tts_count += 1
            await _set_tts_state(state, active=True, playing=True)
            wav_size = os.path.getsize(wav_path) if os.path.exists(wav_path) else 0
            wav_duration = wav_size / max(1, output_sr * 2)
            LOG.info(
                "[%s] TTS broadcast #%d size=%d duration=%.2fs text=\"%s\"",
                state.call_id, tts_count, wav_size, wav_duration, text[:80],
            )
            # Wait for playback to finish before next sentence
            remaining = max(0.2, wav_duration + 0.35)
            while remaining > 0 and state.generation == job_gen:
                await asyncio.sleep(min(0.1, remaining))
                remaining -= 0.1
        except FileNotFoundError as exc:
            LOG.warning("[%s] TTS dependency missing: %s", state.call_id, exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOG.warning("[%s] TTS broadcast worker failed: %s", state.call_id, exc)
        finally:
            await _set_tts_state(state, active=False, playing=False)
            for path in (mp3_path, wav_path):
                with contextlib.suppress(Exception):
                    if path and os.path.exists(path):
                        os.unlink(path)


async def _broadcast_loop(
    app: web.Application,
    call_id: str,
    query: Dict[str, str],
) -> None:
    """
    Background task: pull from orchestrator egress, use TTS for text tokens,
    and uuid_broadcast the resulting WAV files to FS.
    """
    cfg = app["cfg"]
    state = await _get_call_state(app, call_id)
    target = _build_orchestrator_url(cfg["orchestrator_egress_ws"], call_id, query)
    headers = _build_orchestrator_headers(query)
    timeout = aiohttp.ClientTimeout(total=cfg["upstream_timeout_sec"])
    ssl_ctx: object = False
    if target.startswith("wss://"):
        if cfg["upstream_ssl_verify"]:
            ssl_ctx = True
        else:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

    session: Optional[aiohttp.ClientSession] = None
    upstream: Optional[aiohttp.ClientWebSocketResponse] = None
    tts_task: Optional[asyncio.Task] = None
    text_buf = ""
    texts_received = 0
    sentences_queued = 0
    try:
        session = aiohttp.ClientSession(timeout=timeout)
        upstream = await session.ws_connect(target, ssl=ssl_ctx, headers=headers or None)
        state.upstream_ws = upstream

        # Start TTS worker
        tts_task = asyncio.create_task(
            _broadcast_tts_worker(cfg, state),
            name=f"broadcast-tts-{call_id}",
        )

        await _send_upstream_control(state, {"type": "bridge_out_ready"})
        LOG.info("[%s] broadcast_loop (TTS mode) connected orchestrator=%s", call_id, target)

        last_text_time = 0.0
        flush_after = float(cfg.get("tts_flush_after_sec", 1.25))

        while True:
            try:
                msg = await upstream.receive(timeout=0.5)
            except asyncio.TimeoutError:
                # Flush partial text buffer after silence gap
                if text_buf and (time.monotonic() - last_text_time) >= flush_after:
                    cleaned = text_buf.replace("\u2581", " ").strip()
                    text_buf = ""
                    if len(cleaned) > 2:
                        state.tts_queue.put_nowait(cleaned)
                        sentences_queued += 1
                continue

            if msg.type == aiohttp.WSMsgType.ERROR:
                raise RuntimeError(f"upstream egress ws error: {upstream.exception()}")
            if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                break
            if msg.type == aiohttp.WSMsgType.BINARY:
                # Binary audio from orchestrator — just count it, TTS handles playback
                state.last_binary_audio_at = time.monotonic()
                continue
            if msg.type == aiohttp.WSMsgType.TEXT:
                raw = str(msg.data or "").strip()
                if not raw:
                    continue

                # Try parsing JSON control messages
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        msg_type = str(parsed.get("type") or "").strip().lower()
                        if msg_type in {"barge_in", "cancel_tts", "interrupt"}:
                            await _cancel_tts(cfg, state, msg_type)
                            text_buf = ""
                            continue
                        if msg_type == "assistant_text":
                            raw = str(parsed.get("text") or "").strip()
                        elif msg_type in {"tts_state", "bridge_out_ready"}:
                            continue
                except Exception:
                    pass

                cleaned = raw.strip()
                if not cleaned:
                    continue

                texts_received += 1
                LOG.info('[%s] text token: "%s"', call_id, cleaned)
                last_text_time = time.monotonic()
                text_buf += cleaned

                # Extract complete sentences and enqueue for TTS
                complete, remainder = _extract_sentences(text_buf)
                text_buf = remainder
                for sentence in complete:
                    state.tts_queue.put_nowait(sentence)
                    sentences_queued += 1
                    LOG.info('[%s] TTS queued sentence: "%s"', call_id, sentence)

        # Flush remaining text
        if text_buf:
            cleaned = text_buf.replace("\u2581", " ").strip()
            if len(cleaned) > 2:
                state.tts_queue.put_nowait(cleaned)
                sentences_queued += 1

        # Signal TTS worker to finish after processing queue
        state.tts_queue.put_nowait(None)
        if tts_task is not None:
            await asyncio.wait_for(tts_task, timeout=60)

    except asyncio.CancelledError:
        LOG.info("[%s] broadcast_loop cancelled", call_id)
    except Exception as exc:
        LOG.exception("[%s] broadcast_loop failed: %s", call_id, exc)
    finally:
        if tts_task is not None and not tts_task.done():
            tts_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await tts_task
        if upstream is not None and not upstream.closed:
            with contextlib.suppress(Exception):
                await upstream.close()
        if state.upstream_ws is upstream:
            state.upstream_ws = None
        if session is not None and not session.closed:
            await session.close()
        LOG.info(
            "[%s] broadcast_loop done texts=%d sentences_queued=%d",
            call_id, texts_received, sentences_queued,
        )


async def http_stream(request: web.Request) -> web.Response:
    """
    Trigger endpoint for FS dialplan.

    Returns a short silence WAV so playback() finishes immediately and FS
    falls through to park. The real audio delivery happens in a background
    _broadcast_loop task using uuid_broadcast.
    """
    cfg = request.app["cfg"]
    call_id = _normalize_call_id(str(request.match_info.get("call_id") or ""))
    if not call_id:
        raise web.HTTPBadRequest(text="call_id path param is required")

    output_sr = int(cfg["output_sample_rate"])

    # Build a 1-second silence WAV so playback() completes quickly
    silence_samples = output_sr  # 1 second
    silence_pcm = b"\x00\x00" * silence_samples
    wav_buf = bytearray()
    data_size = len(silence_pcm)
    wav_buf += b"RIFF"
    wav_buf += struct.pack("<I", 36 + data_size)
    wav_buf += b"WAVE"
    wav_buf += b"fmt "
    wav_buf += struct.pack("<I", 16)
    wav_buf += struct.pack("<H", 1)   # PCM
    wav_buf += struct.pack("<H", 1)   # mono
    wav_buf += struct.pack("<I", output_sr)
    wav_buf += struct.pack("<I", output_sr * 2)
    wav_buf += struct.pack("<H", 2)
    wav_buf += struct.pack("<H", 16)
    wav_buf += b"data"
    wav_buf += struct.pack("<I", data_size)
    wav_buf += silence_pcm

    # Start the broadcast loop as a background task
    query = dict(request.query)
    task = asyncio.create_task(
        _broadcast_loop(request.app, call_id, query),
        name=f"broadcast-{call_id}",
    )
    # Store task so cleanup can cancel it
    bg_tasks: Dict[str, asyncio.Task] = request.app.setdefault("bg_tasks", {})
    old_task = bg_tasks.get(call_id)
    if old_task is not None and not old_task.done():
        old_task.cancel()
    bg_tasks[call_id] = task

    LOG.info("[%s] http_stream triggered broadcast_loop, returning 1s silence WAV", call_id)
    return web.Response(
        body=bytes(wav_buf),
        content_type="audio/wav",
        headers={"Cache-Control": "no-cache"},
    )


async def health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def on_cleanup(app: web.Application) -> None:
    # Cancel background broadcast tasks
    bg_tasks: Dict[str, asyncio.Task] = app.get("bg_tasks", {})
    for task in list(bg_tasks.values()):
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    registry: Dict[str, CallState] = app.get("call_states", {})
    for state in list(registry.values()):
        with contextlib.suppress(Exception):
            await _cancel_tts(app["cfg"], state, "shutdown")
        if state.tts_task is not None:
            state.tts_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await state.tts_task
        if state.flush_task is not None:
            state.flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await state.flush_task


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Outbound telephony bridge (websocket + HTTP stream)")
    parser.add_argument("--host", default=os.getenv("BRIDGE_OUT_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("BRIDGE_OUT_PORT", "8002")))
    parser.add_argument("--endpoint", default=os.getenv("BRIDGE_OUT_ENDPOINT", "/speak"))
    parser.add_argument("--stream-endpoint", default=os.getenv("BRIDGE_OUT_STREAM_ENDPOINT", "/stream/{call_id}"))
    parser.add_argument(
        "--http-media-type",
        default=os.getenv("BRIDGE_OUT_HTTP_MEDIA_TYPE", "audio/wav"),
    )
    parser.add_argument(
        "--broadcast-flush-ms",
        type=int,
        default=int(os.getenv("BRIDGE_OUT_BROADCAST_FLUSH_MS", "500")),
        help="Accumulate this many ms of PCM before writing WAV and broadcasting via uuid_broadcast.",
    )
    parser.add_argument(
        "--orchestrator-egress-ws",
        default=os.getenv("ORCH_EGRESS_WS", DEFAULT_ORCH_EGRESS_WS),
    )
    parser.add_argument(
        "--source-sample-rate",
        type=int,
        default=int(os.getenv("BRIDGE_OUT_SOURCE_SAMPLE_RATE", "8000")),
        help="PCM sample rate received from orchestrator before HTTP playback conversion.",
    )
    parser.add_argument(
        "--output-sample-rate",
        type=int,
        default=int(os.getenv("BRIDGE_OUT_OUTPUT_SAMPLE_RATE", "8000")),
        help="PCM sample rate expected by FreeSWITCH playback/raw stream.",
    )
    parser.add_argument("--tts-enabled", dest="tts_enabled", action="store_true")
    parser.add_argument("--no-tts-enabled", dest="tts_enabled", action="store_false")
    parser.set_defaults(tts_enabled=_to_bool(os.getenv("BRIDGE_OUT_TTS_ENABLED", "1")))
    parser.add_argument("--tts-voice", default=os.getenv("BRIDGE_OUT_TTS_VOICE", DEFAULT_TTS_VOICE))
    parser.add_argument("--tts-dir", default=os.getenv("BRIDGE_OUT_TTS_DIR", DEFAULT_TTS_DIR))
    parser.add_argument(
        "--tts-flush-after-sec",
        type=float,
        default=float(os.getenv("BRIDGE_OUT_TTS_FLUSH_AFTER_SEC", "1.25")),
        help="Flush partial upstream text to TTS after this much silence.",
    )
    parser.add_argument("--fs-cli", default=os.getenv("BRIDGE_OUT_FS_CLI", DEFAULT_FS_CLI))
    parser.add_argument(
        "--http-silence-frame-ms",
        type=int,
        default=int(os.getenv("BRIDGE_OUT_HTTP_SILENCE_FRAME_MS", "20")),
        help="Write PCM silence to the HTTP playback stream at this cadence when no upstream audio arrives.",
    )
    parser.add_argument("--http-write-silence", dest="http_write_silence", action="store_true")
    parser.add_argument("--no-http-write-silence", dest="http_write_silence", action="store_false")
    parser.set_defaults(http_write_silence=_to_bool(os.getenv("BRIDGE_OUT_HTTP_WRITE_SILENCE", "1")))
    parser.add_argument("--upstream-timeout-sec", type=float, default=float(os.getenv("VOICE_GATEWAY_TIMEOUT_SEC", "1800")))
    parser.add_argument("--upstream-ssl-verify", action="store_true", default=_to_bool(os.getenv("VOICE_GATEWAY_UPSTREAM_SSL_VERIFY", "0")))
    parser.add_argument("--ssl-cert", default=os.getenv("VOICE_GATEWAY_SSL_CERT", ""))
    parser.add_argument("--ssl-key", default=os.getenv("VOICE_GATEWAY_SSL_KEY", ""))
    parser.add_argument("--log-level", default=os.getenv("VOICE_GATEWAY_LOG_LEVEL", "INFO"))
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = web.Application()
    app["cfg"] = {
        "orchestrator_egress_ws": args.orchestrator_egress_ws,
        "upstream_timeout_sec": args.upstream_timeout_sec,
        "upstream_ssl_verify": args.upstream_ssl_verify,
        "http_media_type": args.http_media_type,
        "source_sample_rate": args.source_sample_rate,
        "output_sample_rate": args.output_sample_rate,
        "tts_enabled": args.tts_enabled,
        "tts_voice": args.tts_voice,
        "tts_dir": args.tts_dir,
        "tts_flush_after_sec": max(0.25, args.tts_flush_after_sec),
        "fs_cli": args.fs_cli,
        "http_silence_frame_ms": max(10, args.http_silence_frame_ms),
        "http_write_silence": args.http_write_silence,
        "broadcast_flush_ms": max(100, args.broadcast_flush_ms),
    }
    app["call_states"] = {}
    app.router.add_get(args.endpoint, ws_speak)
    app.router.add_get(args.stream_endpoint, http_stream)
    app.router.add_get("/stream/{call_id}.raw", http_stream)
    app.router.add_get("/health", health)
    app.on_cleanup.append(on_cleanup)

    ssl_context = None
    if args.ssl_cert or args.ssl_key:
        if not args.ssl_cert or not args.ssl_key:
            raise RuntimeError("Both --ssl-cert and --ssl-key are required for TLS")
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(args.ssl_cert, args.ssl_key)

    LOG.info(
        "starting bridge_out host=%s port=%s endpoint=%s stream_endpoint=%s orchestrator=%s source_sr=%s output_sr=%s tts=%s silence=%s",
        args.host,
        args.port,
        args.endpoint,
        args.stream_endpoint,
        args.orchestrator_egress_ws,
        args.source_sample_rate,
        args.output_sample_rate,
        args.tts_enabled and HAS_EDGE_TTS,
        args.http_write_silence,
    )
    web.run_app(app, host=args.host, port=args.port, ssl_context=ssl_context)


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        main()
