#!/usr/bin/env python3
"""
brain_orchestrator.py

Session brain for split voice bridge topology:
- Receives inbound media from bridge_in.py  at /ingest/{call_id}
- Sends outbound media to bridge_out.py     at /egress/{call_id}
- Maintains one upstream OmniCortex /voice/ws per call session
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
import ssl
import time
import urllib.parse
from dataclasses import dataclass
from typing import Dict, Optional, Union

import aiohttp
import numpy as np
import sphn
from aiohttp import web

try:
    from core.voice.asr_engine import get_asr_engine
    HAS_LOCAL_ASR = True
except Exception:
    HAS_LOCAL_ASR = False
    get_asr_engine = None


LOG = logging.getLogger("brain_orchestrator")

FRAME_HANDSHAKE = 0x00
FRAME_AUDIO = 0x01
FRAME_TEXT = 0x02
FRAME_CTRL = 0x03

DEFAULT_UPSTREAM_CHAT_WS = os.getenv("UPSTREAM_CHAT_WS", "")
DEFAULT_AGENT_ID = os.getenv("AGENT_ID", "")
DEFAULT_TOKEN = os.getenv("ORCHESTRATOR_TOKEN", "")

STOP_PHRASES = [
    "stop",
    "wait",
    "hold on",
    "pause",
    "one second",
    "just a second",
    "interrupt",
    "cancel",
    "stop talking",
    "please stop",
    "enough",
    "quiet",
    "mute",
    "shut up",
]

OutboundItem = Union[bytes, str]


def _to_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int16_bytes_to_float32(payload: bytes) -> np.ndarray:
    if not payload:
        return np.zeros((0,), dtype=np.float32)
    arr = np.frombuffer(payload, dtype=np.int16).astype(np.float32)
    return arr / 32768.0


def _decode_fs_audio_bytes(audio_bytes: bytes, codec: str) -> bytes:
    normalized_codec = str(codec or "").strip().upper()
    if not audio_bytes or not normalized_codec or normalized_codec in {"PCM16", "L16", "LINEAR16"}:
        return audio_bytes
    if normalized_codec in {"PCMU", "MULAW", "G711U", "G.711U"}:
        return audioop.ulaw2lin(audio_bytes, 2)
    if normalized_codec in {"PCMA", "ALAW", "G711A", "G.711A"}:
        return audioop.alaw2lin(audio_bytes, 2)
    return audio_bytes


def _float32_to_int16_bytes(samples: np.ndarray) -> bytes:
    clipped = np.clip(samples, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16).tobytes()


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
    normalized = "".join(ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in (text or ""))
    return " ".join(normalized.split())


def _match_stop_phrase(text: str) -> str:
    normalized = f" {_normalize_phrase_text(text)} "
    if not normalized.strip():
        return ""
    for phrase in STOP_PHRASES:
        if f" {phrase} " in normalized:
            return phrase
    return ""


def _extract_request_params(request: web.Request) -> Dict[str, str]:
    params: Dict[str, str] = {}
    for key, value in request.query.items():
        text = str(value or "").strip()
        if text:
            params[key] = text

    header_map = {
        "x-voice-agent-id": "agent_id",
        "x-voice-token": "token",
        "x-voice-prompt": "voice_prompt",
        "x-voice-seed": "seed",
        "x-voice-context-query": "context_query",
        "x-user-id": "x_user_id",
    }
    for header_name, param_name in header_map.items():
        value = str(request.headers.get(header_name) or "").strip()
        if value and not params.get(param_name):
            params[param_name] = value
    return params


def _safe_url_for_log(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if not parsed.query:
        return url
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", parsed.fragment))


@dataclass
class OrchestratorConfig:
    host: str
    port: int
    omnicortex_voice_ws: str
    default_agent_id: str
    default_token: str
    default_voice_prompt: str
    default_seed: str
    default_context_query: str
    inbound_mode: str
    outbound_mode: str
    fs_input_codec: str
    fs_sample_rate: int
    moshi_sample_rate: int
    forward_text_frames: bool
    upstream_ssl_verify: bool
    upstream_timeout_sec: float
    session_idle_sec: float
    outbound_queue_max: int
    barge_in_enabled: bool
    barge_in_rms_threshold: float
    barge_in_min_interval_sec: float
    barge_in_send_interrupt: bool
    barge_in_min_audio_sec: float
    barge_in_max_audio_sec: float
    barge_in_check_interval_sec: float
    silence_pump_enabled: bool
    silence_frame_ms: int
    silence_skip_recent_sec: float


class OrchestratorSession:
    def __init__(self, call_id: str, cfg: OrchestratorConfig, params: Dict[str, str], remote: str) -> None:
        self.call_id = call_id
        self.cfg = cfg
        self.remote = remote
        self.params = dict(params)
        self.last_activity = time.monotonic()

        self.ingest_ws: Optional[web.WebSocketResponse] = None
        self.egress_ws: Optional[web.WebSocketResponse] = None
        self.omni_ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.http_session: Optional[aiohttp.ClientSession] = None
        self.upstream_reader_task: Optional[asyncio.Task] = None
        self.silence_pump_task: Optional[asyncio.Task] = None
        self.phrase_barge_task: Optional[asyncio.Task] = None

        self.outbound_queue: asyncio.Queue[OutboundItem] = asyncio.Queue(
            maxsize=max(1, cfg.outbound_queue_max)
        )
        self.opus_writer = sphn.OpusStreamWriter(cfg.moshi_sample_rate)
        self.opus_reader = sphn.OpusStreamReader(cfg.moshi_sample_rate)
        self.phrase_audio_queue: asyncio.Queue[Optional[np.ndarray]] = asyncio.Queue(maxsize=64)

        self._closed = False
        self._connect_lock = asyncio.Lock()
        self._upstream_send_lock = asyncio.Lock()
        self._handshake_event = asyncio.Event()
        self._last_barge_in = 0.0
        self._last_upstream_audio_send = 0.0
        self.tts_active = False

        self.frames_in = 0
        self.frames_out = 0
        self.frames_dropped = 0

    @property
    def closed(self) -> bool:
        return self._closed

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    def merge_params(self, params: Dict[str, str]) -> None:
        for key, value in params.items():
            text = str(value).strip()
            if text and not self.params.get(key):
                self.params[key] = text

    def is_idle(self, now: float, idle_sec: float) -> bool:
        ingest_alive = self.ingest_ws is not None and not self.ingest_ws.closed
        egress_alive = self.egress_ws is not None and not self.egress_ws.closed
        return (not ingest_alive) and (not egress_alive) and (now - self.last_activity >= idle_sec)

    def _build_upstream_url_and_headers(self) -> tuple:
        """Return (url, headers_dict) for the upstream WS connect."""
        q = self.params
        params: Dict[str, str] = {}
        headers: Dict[str, str] = {}

        # Collect known keys — only include if non-empty
        _KNOWN_KEYS = {
            "agent_id": self.cfg.default_agent_id,
            "token": self.cfg.default_token,
            "voice_prompt": self.cfg.default_voice_prompt,
            "seed": self.cfg.default_seed,
            "context_query": self.cfg.default_context_query,
            "x_user_id": "",
        }
        for key, fallback in _KNOWN_KEYS.items():
            value = (q.get(key) or fallback or "").strip()
            if value:
                params[key] = value

        # Pass through any extra query params not in the known set
        # (e.g. text_prompt for direct PersonaPlex)
        for key, value in q.items():
            if key not in _KNOWN_KEYS and key != "call_uuid":
                text = str(value).strip()
                if text:
                    params[key] = text

        # PersonaPlex reads OmniCortex bearer from Authorization header,
        # not the token query param (which is for its own RunPod auth).
        token_val = params.get("token", "")
        if token_val:
            headers["Authorization"] = f"Bearer {token_val}"

        x_user = params.pop("x_user_id", "")
        if x_user:
            headers["x-user-id"] = x_user

        if not params:
            return self.cfg.omnicortex_voice_ws, headers
        sep = "&" if "?" in self.cfg.omnicortex_voice_ws else "?"
        return f"{self.cfg.omnicortex_voice_ws}{sep}{urllib.parse.urlencode(params)}", headers

    async def ensure_upstream(self) -> None:
        if self._closed:
            raise RuntimeError("session is closed")
        async with self._connect_lock:
            if self.omni_ws is not None and not self.omni_ws.closed:
                return
            url, headers = self._build_upstream_url_and_headers()
            timeout = aiohttp.ClientTimeout(total=self.cfg.upstream_timeout_sec)
            ssl_ctx: object = False
            if url.startswith("wss://"):
                if self.cfg.upstream_ssl_verify:
                    ssl_ctx = True
                else:
                    ssl_ctx = ssl.create_default_context()
                    ssl_ctx.check_hostname = False
                    ssl_ctx.verify_mode = ssl.CERT_NONE

            if self.http_session is None or self.http_session.closed:
                self.http_session = aiohttp.ClientSession(timeout=timeout)
            self._handshake_event.clear()
            self.omni_ws = await self.http_session.ws_connect(
                url, ssl=ssl_ctx, headers=headers,
            )
            self.upstream_reader_task = asyncio.create_task(
                self._upstream_reader_loop(),
                name=f"orchestrator-upstream-{self.call_id}",
            )
            if self.cfg.silence_pump_enabled and self.silence_pump_task is None:
                self.silence_pump_task = asyncio.create_task(
                    self._silence_pump_loop(),
                    name=f"orchestrator-silence-{self.call_id}",
                )
            if self.cfg.barge_in_enabled and self.phrase_barge_task is None:
                self.phrase_barge_task = asyncio.create_task(
                    self._phrase_barge_loop(),
                    name=f"orchestrator-barge-{self.call_id}",
                )
            LOG.info("[%s] upstream connected remote=%s url=%s", self.call_id, self.remote, _safe_url_for_log(url))

    async def _wait_for_handshake(self) -> None:
        if self._handshake_event.is_set():
            return
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._handshake_event.wait(), timeout=10.0)

    async def _send_upstream_bytes(self, payload: bytes) -> None:
        if self.omni_ws is None or self.omni_ws.closed:
            return
        async with self._upstream_send_lock:
            await self.omni_ws.send_bytes(payload)
            self._last_upstream_audio_send = time.monotonic()

    async def _send_pcm_to_upstream(self, pcm_fs: np.ndarray) -> int:
        if pcm_fs.size == 0:
            return 0
        pcm_moshi = _resample_linear(pcm_fs, self.cfg.fs_sample_rate, self.cfg.moshi_sample_rate)
        if pcm_moshi.size == 0:
            return 0

        frames_sent = 0
        async with self._upstream_send_lock:
            self.opus_writer.append_pcm(pcm_moshi.astype(np.float32, copy=False))
            while True:
                opus_payload = self.opus_writer.read_bytes()
                if not opus_payload:
                    break
                if self.omni_ws is None or self.omni_ws.closed:
                    break
                await self.omni_ws.send_bytes(bytes([FRAME_AUDIO]) + opus_payload)
                frames_sent += 1
            if frames_sent > 0:
                self._last_upstream_audio_send = time.monotonic()
        return frames_sent

    async def _send_bridge_out_control(self, payload: Dict[str, object]) -> None:
        await self._enqueue_outbound(json.dumps(payload))

    async def _enqueue_outbound(self, item: OutboundItem) -> None:
        while self.outbound_queue.full():
            try:
                self.outbound_queue.get_nowait()
                self.frames_dropped += 1
            except asyncio.QueueEmpty:
                break
        try:
            self.outbound_queue.put_nowait(item)
        except asyncio.QueueFull:
            self.frames_dropped += 1

    def _flush_outbound(self) -> int:
        dropped = 0
        while True:
            try:
                self.outbound_queue.get_nowait()
                dropped += 1
            except asyncio.QueueEmpty:
                break
        self.frames_dropped += dropped
        return dropped

    async def _send_interrupt(self) -> None:
        if self.omni_ws is None or self.omni_ws.closed:
            return
        payload = json.dumps({"type": "interrupt", "reason": "barge_in"}).encode("utf-8")
        with contextlib.suppress(Exception):
            await self._send_upstream_bytes(bytes([FRAME_CTRL]) + payload)

    async def _silence_pump_loop(self) -> None:
        await self._wait_for_handshake()
        frame_ms = max(10, self.cfg.silence_frame_ms)
        samples = max(1, int(round(self.cfg.moshi_sample_rate * (frame_ms / 1000.0))))
        silence = np.zeros((samples,), dtype=np.float32)
        silence_writer = sphn.OpusStreamWriter(self.cfg.moshi_sample_rate)
        tick = frame_ms / 1000.0
        LOG.info("[%s] silence pump started frame_ms=%d", self.call_id, frame_ms)

        while not self._closed:
            try:
                await asyncio.sleep(tick)
                if self.omni_ws is None or self.omni_ws.closed:
                    return
                if time.monotonic() - self._last_upstream_audio_send < self.cfg.silence_skip_recent_sec:
                    continue
                async with self._upstream_send_lock:
                    silence_writer.append_pcm(silence)
                    while True:
                        opus_payload = silence_writer.read_bytes()
                        if not opus_payload:
                            break
                        if self.omni_ws is None or self.omni_ws.closed:
                            return
                        await self.omni_ws.send_bytes(bytes([FRAME_AUDIO]) + opus_payload)
                    self._last_upstream_audio_send = time.monotonic()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOG.warning("[%s] silence pump stopped: %s", self.call_id, exc)
                return

    async def _trigger_phrase_barge_in(self, phrase: str, transcript: str) -> None:
        now = time.monotonic()
        if now - self._last_barge_in < self.cfg.barge_in_min_interval_sec:
            return
        self._last_barge_in = now
        dropped = self._flush_outbound()
        self.tts_active = False
        LOG.info(
            '[%s] phrase barge-in phrase="%s" dropped=%d transcript="%s"',
            self.call_id,
            phrase,
            dropped,
            transcript,
        )
        await self._send_bridge_out_control(
            {
                "type": "barge_in",
                "reason": f"stop_phrase:{phrase}",
                "transcript": transcript,
            }
        )
        if self.cfg.barge_in_send_interrupt:
            await self._send_interrupt()

    async def _phrase_barge_loop(self) -> None:
        if not HAS_LOCAL_ASR:
            LOG.warning("[%s] phrase barge-in disabled: local ASR unavailable", self.call_id)
            return

        asr = await get_asr_engine()
        min_samples = max(1, int(self.cfg.fs_sample_rate * self.cfg.barge_in_min_audio_sec))
        max_samples = max(min_samples, int(self.cfg.fs_sample_rate * self.cfg.barge_in_max_audio_sec))
        last_check = 0.0
        pcm_window = np.zeros((0,), dtype=np.float32)
        LOG.info("[%s] phrase barge enabled stop_phrases=%d", self.call_id, len(STOP_PHRASES))

        while not self._closed:
            chunk = await self.phrase_audio_queue.get()
            try:
                if chunk is None:
                    return
                if not self.tts_active:
                    pcm_window = np.zeros((0,), dtype=np.float32)
                    continue
                if chunk.size == 0:
                    continue

                level = _rms(chunk)
                if level < self.cfg.barge_in_rms_threshold:
                    if pcm_window.size > max_samples:
                        pcm_window = pcm_window[-max_samples:]
                    continue

                pcm_window = np.concatenate([pcm_window, chunk])
                if pcm_window.size > max_samples:
                    pcm_window = pcm_window[-max_samples:]
                if pcm_window.size < min_samples:
                    continue

                now = time.monotonic()
                if now - last_check < self.cfg.barge_in_check_interval_sec:
                    continue
                last_check = now

                transcript, confidence, detected_lang = await asr.transcribe(
                    pcm_window.copy(),
                    sample_rate=self.cfg.fs_sample_rate,
                )
                transcript = (transcript or "").strip()
                if transcript:
                    LOG.info(
                        '[%s] phrase ASR lang=%s conf=%.2f text="%s"',
                        self.call_id,
                        detected_lang,
                        confidence,
                        transcript,
                    )
                phrase = _match_stop_phrase(transcript)
                if phrase:
                    await self._trigger_phrase_barge_in(phrase, transcript)
                    pcm_window = np.zeros((0,), dtype=np.float32)
                elif pcm_window.size >= max_samples:
                    pcm_window = pcm_window[-min_samples:]
            finally:
                self.phrase_audio_queue.task_done()

    async def _upstream_reader_loop(self) -> None:
        assert self.omni_ws is not None
        try:
            async for msg in self.omni_ws:
                self.touch()
                if msg.type == aiohttp.WSMsgType.ERROR:
                    raise RuntimeError(f"upstream ws error: {self.omni_ws.exception()}")
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
                    self._handshake_event.set()
                    LOG.info("[%s] upstream handshake", self.call_id)
                    continue
                if kind == FRAME_TEXT:
                    if self.cfg.forward_text_frames:
                        await self._enqueue_outbound(payload.decode("utf-8", errors="ignore"))
                    continue
                if kind == FRAME_CTRL:
                    LOG.debug(
                        "[%s] upstream ctrl: %s",
                        self.call_id,
                        payload.decode("utf-8", errors="ignore"),
                    )
                    continue
                if kind != FRAME_AUDIO:
                    LOG.warning("[%s] unknown upstream frame=%s", self.call_id, kind)
                    continue

                if self.cfg.outbound_mode == "moshi":
                    await self._enqueue_outbound(data)
                    self.frames_out += 1
                    continue

                self.opus_reader.append_bytes(payload)
                pcm_moshi = self.opus_reader.read_pcm()
                if pcm_moshi is None:
                    continue
                arr = np.asarray(pcm_moshi)
                if arr.size == 0:
                    continue
                if arr.ndim == 2:
                    arr = arr[0]
                arr = arr.astype(np.float32, copy=False)
                pcm_fs = _resample_linear(arr, self.cfg.moshi_sample_rate, self.cfg.fs_sample_rate)
                await self._enqueue_outbound(_float32_to_int16_bytes(pcm_fs))
                self.frames_out += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOG.warning("[%s] upstream reader stopped: %s", self.call_id, exc)
        finally:
            await self.close(reason="upstream disconnected")

    async def handle_ingest(self, ws: web.WebSocketResponse) -> None:
        if self.ingest_ws is not None and not self.ingest_ws.closed and self.ingest_ws is not ws:
            await self.ingest_ws.close(code=1000, message=b"ingest replaced")
        self.ingest_ws = ws
        self.touch()
        await self.ensure_upstream()
        assert self.omni_ws is not None
        await self._wait_for_handshake()

        try:
            async for msg in ws:
                self.touch()
                if msg.type == web.WSMsgType.ERROR:
                    raise RuntimeError(f"ingest ws error: {ws.exception()}")
                if msg.type in (web.WSMsgType.CLOSE, web.WSMsgType.CLOSED):
                    break
                if msg.type == web.WSMsgType.TEXT:
                    text = str(msg.data)
                    await self._send_upstream_bytes(bytes([FRAME_CTRL]) + text.encode("utf-8", errors="ignore"))
                    continue
                if msg.type != web.WSMsgType.BINARY:
                    continue
                data = bytes(msg.data)
                if not data:
                    continue

                if self.cfg.inbound_mode == "moshi":
                    if data[0] in (FRAME_HANDSHAKE, FRAME_AUDIO, FRAME_TEXT, FRAME_CTRL):
                        await self._send_upstream_bytes(data)
                    else:
                        await self._send_upstream_bytes(bytes([FRAME_AUDIO]) + data)
                    self.frames_in += 1
                    continue

                pcm_16bit_signed_8000hz_mono = _decode_fs_audio_bytes(data, self.cfg.fs_input_codec)
                pcm_fs = _int16_bytes_to_float32(pcm_16bit_signed_8000hz_mono)
                if self.cfg.barge_in_enabled and self.tts_active:
                    try:
                        self.phrase_audio_queue.put_nowait(pcm_fs.copy())
                    except asyncio.QueueFull:
                        with contextlib.suppress(asyncio.QueueEmpty):
                            self.phrase_audio_queue.get_nowait()
                            self.phrase_audio_queue.task_done()
                        with contextlib.suppress(asyncio.QueueFull):
                            self.phrase_audio_queue.put_nowait(pcm_fs.copy())
                self.frames_in += await self._send_pcm_to_upstream(pcm_fs)
        finally:
            if self.ingest_ws is ws:
                self.ingest_ws = None
            self.touch()

    async def _egress_send_loop(self, ws: web.WebSocketResponse) -> None:
        while not ws.closed and not self._closed:
            try:
                item = await asyncio.wait_for(self.outbound_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if isinstance(item, bytes):
                await ws.send_bytes(item)
            else:
                await ws.send_str(item)

    async def _egress_receive_loop(self, ws: web.WebSocketResponse) -> None:
        async for msg in ws:
            if msg.type == web.WSMsgType.ERROR:
                raise RuntimeError(f"egress ws error: {ws.exception()}")
            if msg.type in (web.WSMsgType.CLOSE, web.WSMsgType.CLOSED):
                break
            if msg.type == web.WSMsgType.TEXT:
                text = str(msg.data or "").strip()
                if text:
                    try:
                        payload = json.loads(text)
                    except Exception:
                        LOG.debug("[%s] bridge_out text: %s", self.call_id, text)
                    else:
                        if isinstance(payload, dict):
                            if payload.get("type") == "tts_state":
                                self.tts_active = bool(payload.get("active"))
                                LOG.debug("[%s] tts_state active=%s", self.call_id, self.tts_active)
                            elif payload.get("type") == "bridge_out_ready":
                                LOG.debug("[%s] bridge_out ready", self.call_id)
            self.touch()

    async def handle_egress(self, ws: web.WebSocketResponse) -> None:
        if self.egress_ws is not None and not self.egress_ws.closed and self.egress_ws is not ws:
            await self.egress_ws.close(code=1000, message=b"egress replaced")
        self.egress_ws = ws
        self.touch()
        await self.ensure_upstream()

        sender = asyncio.create_task(self._egress_send_loop(ws), name=f"orchestrator-egress-send-{self.call_id}")
        receiver = asyncio.create_task(self._egress_receive_loop(ws), name=f"orchestrator-egress-recv-{self.call_id}")
        done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc:
                raise exc

        if self.egress_ws is ws:
            self.egress_ws = None
        self.touch()

    async def close(self, reason: str) -> None:
        if self._closed:
            return
        self._closed = True
        LOG.info(
            "[%s] close reason=%s in=%d out=%d dropped=%d",
            self.call_id,
            reason,
            self.frames_in,
            self.frames_out,
            self.frames_dropped,
        )
        if self.upstream_reader_task is not None:
            self.upstream_reader_task.cancel()
            try:
                await self.upstream_reader_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                LOG.warning("Exception while awaiting upstream_reader_task: %s", e)
            self.upstream_reader_task = None
        if self.silence_pump_task is not None:
            self.silence_pump_task.cancel()
            try:
                await self.silence_pump_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                LOG.warning("Exception while awaiting silence_pump_task: %s", e)
            self.silence_pump_task = None
        if self.phrase_barge_task is not None:
            self.phrase_barge_task.cancel()
            try:
                await self.phrase_barge_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                LOG.warning("Exception while awaiting phrase_barge_task: %s", e)
            self.phrase_barge_task = None
        with contextlib.suppress(asyncio.QueueFull):
            self.phrase_audio_queue.put_nowait(None)
        if self.omni_ws is not None and not self.omni_ws.closed:
            await self.omni_ws.close()
        if self.http_session is not None and not self.http_session.closed:
            await self.http_session.close()
        if self.ingest_ws is not None and not self.ingest_ws.closed:
            with contextlib.suppress(Exception):
                await self.ingest_ws.close()
        if self.egress_ws is not None and not self.egress_ws.closed:
            with contextlib.suppress(Exception):
                await self.egress_ws.close()


class SessionRegistry:
    def __init__(self, cfg: OrchestratorConfig) -> None:
        self.cfg = cfg
        self._sessions: Dict[str, OrchestratorSession] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, call_id: str, params: Dict[str, str], remote: str) -> OrchestratorSession:
        async with self._lock:
            session = self._sessions.get(call_id)
            if session is None or session.closed or session.is_idle(time.monotonic(), self.cfg.session_idle_sec):
                # Close old session before replacing it to avoid resource leak
                if session is not None:
                    try:
                        await session.close()
                    except Exception as e:
                        LOG.warning("Failed to close idle session %s: %s", call_id, e)
                session = OrchestratorSession(call_id, self.cfg, params, remote)
                self._sessions[call_id] = session
            else:
                session.merge_params(params)
            return session

    async def cleanup_idle(self) -> None:
        now = time.monotonic()
        stale: Dict[str, OrchestratorSession] = {}
        async with self._lock:
            for call_id, session in list(self._sessions.items()):
                if session.is_idle(now, self.cfg.session_idle_sec):
                    stale[call_id] = session
                    del self._sessions[call_id]
        for call_id, session in stale.items():
            LOG.info("[%s] idle cleanup", call_id)
            await session.close(reason="idle timeout")

    async def close_all(self) -> None:
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            await session.close(reason="shutdown")

    def count(self) -> int:
        return len(self._sessions)


def _require_call_id(call_id: str) -> str:
    call_id = str(call_id or "").strip()
    if not call_id:
        raise web.HTTPBadRequest(text="call_id is required in URL path")
    return call_id


async def ws_ingest(request: web.Request) -> web.WebSocketResponse:
    reg: SessionRegistry = request.app["sessions"]
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    call_id = "-"
    try:
        call_id = _require_call_id(request.match_info.get("call_id"))
        params = _extract_request_params(request)
        LOG.info("[%s] ingest websocket accepted remote=%s", call_id, request.remote or "-")
        session = await reg.get_or_create(call_id, params, request.remote or "unknown")
        await session.handle_ingest(ws)
    except web.HTTPException as exc:
        text = exc.text or str(exc) or ""
        await ws.send_str(json.dumps({"error": text}))
        await ws.close(code=1008, message=text.encode("utf-8", errors="ignore") if text else b"error")
    except Exception as exc:
        LOG.exception("[%s] ingest failed: %s", call_id, exc)
        if not ws.closed:
            await ws.close(code=1011, message=b"ingest failed")
    finally:
        if not ws.closed:
            await ws.close()
    return ws


async def ws_egress(request: web.Request) -> web.WebSocketResponse:
    reg: SessionRegistry = request.app["sessions"]
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    call_id = "-"
    try:
        call_id = _require_call_id(request.match_info.get("call_id"))
        params = _extract_request_params(request)
        LOG.info("[%s] egress websocket accepted remote=%s", call_id, request.remote or "-")
        session = await reg.get_or_create(call_id, params, request.remote or "unknown")
        await session.handle_egress(ws)
    except web.HTTPException as exc:
        await ws.send_str(json.dumps({"error": exc.text}))
        await ws.close(code=1008, message=exc.text.encode("utf-8", errors="ignore"))
    except Exception as exc:
        LOG.exception("[%s] egress failed: %s", call_id, exc)
        if not ws.closed:
            await ws.close(code=1011, message=b"egress failed")
    finally:
        if not ws.closed:
            await ws.close()
    return ws


async def health(request: web.Request) -> web.Response:
    reg: SessionRegistry = request.app["sessions"]
    return web.json_response({"status": "ok", "active_sessions": reg.count()})


async def _cleanup_worker(app: web.Application) -> None:
    cfg: OrchestratorConfig = app["cfg"]
    reg: SessionRegistry = app["sessions"]
    interval = max(5.0, min(30.0, cfg.session_idle_sec / 2.0))
    try:
        while True:
            await asyncio.sleep(interval)
            await reg.cleanup_idle()
    except asyncio.CancelledError:
        return


async def on_startup(app: web.Application) -> None:
    app["cleanup_task"] = asyncio.create_task(_cleanup_worker(app), name="orchestrator-cleanup")


async def on_cleanup(app: web.Application) -> None:
    task: Optional[asyncio.Task] = app.get("cleanup_task")
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    reg: SessionRegistry = app["sessions"]
    await reg.close_all()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Split bridge session orchestrator")
    parser.add_argument("--host", default=os.getenv("ORCH_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("ORCH_PORT", "8101")))
    parser.add_argument(
        "--omnicortex-voice-ws",
        default=os.getenv("OMNICORTEX_VOICE_WS", DEFAULT_UPSTREAM_CHAT_WS),
    )
    parser.add_argument("--default-agent-id", default=os.getenv("VOICE_GATEWAY_AGENT_ID", DEFAULT_AGENT_ID))
    parser.add_argument("--default-token", default=os.getenv("VOICE_GATEWAY_TOKEN", DEFAULT_TOKEN))
    parser.add_argument("--default-voice-prompt", default=os.getenv("VOICE_GATEWAY_VOICE_PROMPT", "NATF0.pt"))
    parser.add_argument("--default-seed", default=os.getenv("VOICE_GATEWAY_SEED", "-1"))
    parser.add_argument("--default-context-query", default=os.getenv("VOICE_GATEWAY_CONTEXT_QUERY", ""))
    parser.add_argument("--inbound-mode", choices=["pcm16", "moshi"], default=os.getenv("VOICE_GATEWAY_INBOUND_MODE", "pcm16"))
    parser.add_argument("--outbound-mode", choices=["pcm16", "moshi"], default=os.getenv("VOICE_GATEWAY_OUTBOUND_MODE", "pcm16"))
    parser.add_argument(
        "--fs-input-codec",
        choices=["pcm16", "pcmu", "pcma"],
        default=os.getenv("VOICE_GATEWAY_FS_INPUT_CODEC", "pcm16").strip().lower(),
    )
    parser.add_argument("--fs-sample-rate", type=int, default=int(os.getenv("VOICE_GATEWAY_FS_SR", "8000")))
    parser.add_argument("--moshi-sample-rate", type=int, default=int(os.getenv("VOICE_GATEWAY_MOSHI_SR", "24000")))
    parser.add_argument("--forward-text-frames", dest="forward_text_frames", action="store_true")
    parser.add_argument("--no-forward-text-frames", dest="forward_text_frames", action="store_false")
    parser.set_defaults(forward_text_frames=_to_bool(os.getenv("VOICE_GATEWAY_FORWARD_TEXT_FRAMES", "1")))
    parser.add_argument("--upstream-ssl-verify", action="store_true", default=_to_bool(os.getenv("VOICE_GATEWAY_UPSTREAM_SSL_VERIFY", "0")))
    parser.add_argument("--upstream-timeout-sec", type=float, default=float(os.getenv("VOICE_GATEWAY_TIMEOUT_SEC", "1800")))
    parser.add_argument("--session-idle-sec", type=float, default=float(os.getenv("VOICE_GATEWAY_SESSION_IDLE_SEC", "45")))
    parser.add_argument("--outbound-queue-max", type=int, default=int(os.getenv("VOICE_GATEWAY_OUTBOUND_QUEUE_MAX", "400")))
    parser.add_argument("--barge-in-enabled", action="store_true", default=_to_bool(os.getenv("VOICE_GATEWAY_BARGE_IN", "1")))
    parser.add_argument("--barge-in-rms-threshold", type=float, default=float(os.getenv("VOICE_GATEWAY_BARGE_IN_RMS", "0.02")))
    parser.add_argument("--barge-in-min-interval-sec", type=float, default=float(os.getenv("VOICE_GATEWAY_BARGE_IN_MIN_INTERVAL_SEC", "0.35")))
    parser.add_argument("--barge-in-send-interrupt", action="store_true", default=_to_bool(os.getenv("VOICE_GATEWAY_BARGE_IN_SEND_INTERRUPT", "1")))
    parser.add_argument("--barge-in-min-audio-sec", type=float, default=float(os.getenv("VOICE_GATEWAY_BARGE_IN_MIN_AUDIO_SEC", "0.8")))
    parser.add_argument("--barge-in-max-audio-sec", type=float, default=float(os.getenv("VOICE_GATEWAY_BARGE_IN_MAX_AUDIO_SEC", "2.5")))
    parser.add_argument("--barge-in-check-interval-sec", type=float, default=float(os.getenv("VOICE_GATEWAY_BARGE_IN_CHECK_INTERVAL_SEC", "0.8")))
    parser.add_argument("--silence-pump-enabled", action="store_true", default=_to_bool(os.getenv("VOICE_GATEWAY_SILENCE_PUMP", "1")))
    parser.add_argument("--silence-frame-ms", type=int, default=int(os.getenv("VOICE_GATEWAY_SILENCE_FRAME_MS", "20")))
    parser.add_argument("--silence-skip-recent-sec", type=float, default=float(os.getenv("VOICE_GATEWAY_SILENCE_SKIP_RECENT_SEC", "0.025")))
    parser.add_argument("--log-level", default=os.getenv("VOICE_GATEWAY_LOG_LEVEL", "INFO"))
    parser.add_argument("--ssl-cert", default=os.getenv("VOICE_GATEWAY_SSL_CERT", ""))
    parser.add_argument("--ssl-key", default=os.getenv("VOICE_GATEWAY_SSL_KEY", ""))
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = OrchestratorConfig(
        host=args.host,
        port=args.port,
        omnicortex_voice_ws=args.omnicortex_voice_ws,
        default_agent_id=args.default_agent_id,
        default_token=args.default_token,
        default_voice_prompt=args.default_voice_prompt,
        default_seed=args.default_seed,
        default_context_query=args.default_context_query,
        inbound_mode=args.inbound_mode,
        outbound_mode=args.outbound_mode,
        fs_input_codec=args.fs_input_codec,
        fs_sample_rate=args.fs_sample_rate,
        moshi_sample_rate=args.moshi_sample_rate,
        forward_text_frames=args.forward_text_frames,
        upstream_ssl_verify=args.upstream_ssl_verify,
        upstream_timeout_sec=args.upstream_timeout_sec,
        session_idle_sec=max(10.0, args.session_idle_sec),
        outbound_queue_max=max(50, args.outbound_queue_max),
        barge_in_enabled=args.barge_in_enabled,
        barge_in_rms_threshold=max(0.0, args.barge_in_rms_threshold),
        barge_in_min_interval_sec=max(0.05, args.barge_in_min_interval_sec),
        barge_in_send_interrupt=args.barge_in_send_interrupt,
        barge_in_min_audio_sec=max(0.2, args.barge_in_min_audio_sec),
        barge_in_max_audio_sec=max(args.barge_in_min_audio_sec, args.barge_in_max_audio_sec),
        barge_in_check_interval_sec=max(0.1, args.barge_in_check_interval_sec),
        silence_pump_enabled=args.silence_pump_enabled,
        silence_frame_ms=max(10, args.silence_frame_ms),
        silence_skip_recent_sec=max(0.0, args.silence_skip_recent_sec),
    )

    app = web.Application()
    app["cfg"] = cfg
    app["sessions"] = SessionRegistry(cfg)
    app.router.add_get("/ingest/{call_id}", ws_ingest)
    app.router.add_get("/egress/{call_id}", ws_egress)
    app.router.add_get("/health", health)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    ssl_context = None
    if args.ssl_cert or args.ssl_key:
        if not args.ssl_cert or not args.ssl_key:
            raise RuntimeError("Both --ssl-cert and --ssl-key are required for TLS")
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(args.ssl_cert, args.ssl_key)

    LOG.info(
        "starting orchestrator host=%s port=%s upstream=%s inbound_mode=%s fs_input_codec=%s silence_pump=%s forward_text=%s",
        cfg.host,
        cfg.port,
        cfg.omnicortex_voice_ws,
        cfg.inbound_mode,
        cfg.fs_input_codec,
        cfg.silence_pump_enabled,
        cfg.forward_text_frames,
    )
    web.run_app(app, host=cfg.host, port=cfg.port, ssl_context=ssl_context)


if __name__ == "__main__":
    main()
