#!/usr/bin/env python3
"""
Two-leg Voice Gateway: FreeSWITCH/media WS <-> OmniCortex /voice/ws.

This variant splits telephony I/O into two websocket legs per call:
  - /listen?call_uuid=... : inbound audio from telephony -> OmniCortex
  - /speak?call_uuid=...  : outbound audio from OmniCortex -> telephony

Use this when your media side sends and receives audio on separate bridges.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
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


LOG = logging.getLogger("voice_gateway_two_leg")

FRAME_HANDSHAKE = 0x00
FRAME_AUDIO = 0x01
FRAME_TEXT = 0x02
FRAME_CTRL = 0x03

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


@dataclass
class GatewayConfig:
    host: str
    port: int
    listen_endpoint: str
    speak_endpoint: str
    omnicortex_voice_ws: str
    default_agent_id: str
    default_token: str
    default_voice_prompt: str
    default_seed: str
    default_context_query: str
    inbound_mode: str
    outbound_mode: str
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


class TwoLegSession:
    def __init__(
        self,
        call_id: str,
        cfg: GatewayConfig,
        query: Dict[str, str],
        remote: str,
    ) -> None:
        self.call_id = call_id
        self.cfg = cfg
        self.remote = remote
        self.query: Dict[str, str] = {k: str(v) for k, v in query.items() if v is not None}
        self.last_activity = time.monotonic()

        self.listen_ws: Optional[web.WebSocketResponse] = None
        self.speak_ws: Optional[web.WebSocketResponse] = None
        self.omni_ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.http_session: Optional[aiohttp.ClientSession] = None
        self.upstream_reader_task: Optional[asyncio.Task] = None

        self.outbound_queue: asyncio.Queue[OutboundItem] = asyncio.Queue(
            maxsize=max(1, cfg.outbound_queue_max)
        )
        self.opus_writer = sphn.OpusStreamWriter(cfg.moshi_sample_rate)
        self.opus_reader = sphn.OpusStreamReader(cfg.moshi_sample_rate)
        self._connect_lock = asyncio.Lock()
        self._closed = False
        self._last_barge_in = 0.0

        self.frames_in = 0
        self.frames_out = 0
        self.frames_dropped = 0

    @property
    def closed(self) -> bool:
        return self._closed

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    def merge_query(self, query: Dict[str, str]) -> None:
        for key, value in query.items():
            if value is None:
                continue
            text = str(value).strip()
            if text and not self.query.get(key):
                self.query[key] = text

    def _build_upstream_url(self) -> str:
        q = self.query
        agent_id = (q.get("agent_id") or self.cfg.default_agent_id).strip()
        if not agent_id:
            raise web.HTTPBadRequest(text="agent_id is required (query or --default-agent-id)")
        token = (q.get("token") or self.cfg.default_token).strip()
        if not token:
            raise web.HTTPBadRequest(text="token is required (query or --default-token)")

        voice_prompt = (q.get("voice_prompt") or self.cfg.default_voice_prompt).strip() or "NATF0.pt"
        seed = (q.get("seed") or self.cfg.default_seed).strip() or "-1"
        context_query = (q.get("context_query") or self.cfg.default_context_query).strip()
        x_user_id = (q.get("x_user_id") or "").strip()

        params = {
            "agent_id": agent_id,
            "token": token,
            "voice_prompt": voice_prompt,
            "seed": seed,
        }
        if context_query:
            params["context_query"] = context_query
        if x_user_id:
            params["x_user_id"] = x_user_id

        sep = "&" if "?" in self.cfg.omnicortex_voice_ws else "?"
        return f"{self.cfg.omnicortex_voice_ws}{sep}{urllib.parse.urlencode(params)}"

    async def ensure_upstream(self) -> None:
        if self._closed:
            raise RuntimeError("session closed")
        async with self._connect_lock:
            if self.omni_ws is not None and not self.omni_ws.closed:
                return

            upstream_url = self._build_upstream_url()
            timeout = aiohttp.ClientTimeout(total=self.cfg.upstream_timeout_sec)
            ssl_ctx = None
            if upstream_url.startswith("wss://") and not self.cfg.upstream_ssl_verify:
                ssl_ctx = ssl.create_default_context()
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE

            if self.http_session is None or self.http_session.closed:
                self.http_session = aiohttp.ClientSession(timeout=timeout)
            self.omni_ws = await self.http_session.ws_connect(upstream_url, ssl=ssl_ctx)
            LOG.info("[%s] upstream connected remote=%s url=%s", self.call_id, self.remote, upstream_url)
            self.upstream_reader_task = asyncio.create_task(
                self._upstream_reader_loop(),
                name=f"two-leg-upstream-{self.call_id}",
            )

    async def _enqueue_outbound(self, item: OutboundItem) -> None:
        if self._closed:
            return
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
        try:
            await self.omni_ws.send_bytes(bytes([FRAME_CTRL]) + payload)
        except Exception as exc:
            LOG.debug("[%s] interrupt send failed: %s", self.call_id, exc)

    async def _maybe_handle_barge_in(self, pcm_fs: np.ndarray) -> None:
        if not self.cfg.barge_in_enabled:
            return
        level = _rms(pcm_fs)
        if level < self.cfg.barge_in_rms_threshold:
            return
        now = time.monotonic()
        if now - self._last_barge_in < self.cfg.barge_in_min_interval_sec:
            return
        self._last_barge_in = now
        dropped = self._flush_outbound()
        if dropped > 0:
            LOG.info("[%s] barge-in: dropped=%d rms=%.4f", self.call_id, dropped, level)
            if self.cfg.barge_in_send_interrupt:
                await self._send_interrupt()

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
                    LOG.info("[%s] upstream handshake", self.call_id)
                    continue

                if kind == FRAME_TEXT:
                    text = payload.decode("utf-8", errors="ignore")
                    if self.cfg.forward_text_frames:
                        await self._enqueue_outbound(text)
                    else:
                        LOG.debug("[%s] upstream text: %s", self.call_id, text)
                    continue

                if kind == FRAME_CTRL:
                    LOG.debug(
                        "[%s] upstream ctrl: %s",
                        self.call_id,
                        payload.decode("utf-8", errors="ignore"),
                    )
                    continue

                if kind != FRAME_AUDIO:
                    LOG.warning("[%s] upstream unknown frame kind=%s", self.call_id, kind)
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
            await self.close(reason="upstream closed")

    async def handle_listen(self, ws: web.WebSocketResponse) -> None:
        if self.listen_ws is not None and not self.listen_ws.closed and self.listen_ws is not ws:
            await self.listen_ws.close(code=1000, message=b"listen leg replaced")
        self.listen_ws = ws
        self.touch()
        await self.ensure_upstream()

        assert self.omni_ws is not None
        try:
            async for msg in ws:
                self.touch()
                if msg.type == web.WSMsgType.ERROR:
                    raise RuntimeError(f"listen ws error: {ws.exception()}")
                if msg.type in (web.WSMsgType.CLOSE, web.WSMsgType.CLOSED):
                    break
                if msg.type == web.WSMsgType.TEXT:
                    LOG.debug("[%s] listen text: %s", self.call_id, msg.data)
                    continue
                if msg.type != web.WSMsgType.BINARY:
                    continue

                data = bytes(msg.data)
                if not data:
                    continue

                if self.cfg.inbound_mode == "moshi":
                    if data[0] in (FRAME_HANDSHAKE, FRAME_AUDIO, FRAME_TEXT, FRAME_CTRL):
                        await self.omni_ws.send_bytes(data)
                    else:
                        await self.omni_ws.send_bytes(bytes([FRAME_AUDIO]) + data)
                    self.frames_in += 1
                    continue

                pcm_fs = _int16_bytes_to_float32(data)
                await self._maybe_handle_barge_in(pcm_fs)
                pcm_moshi = _resample_linear(pcm_fs, self.cfg.fs_sample_rate, self.cfg.moshi_sample_rate)
                if pcm_moshi.size == 0:
                    continue
                self.opus_writer.append_pcm(pcm_moshi)
                while True:
                    opus_payload = self.opus_writer.read_bytes()
                    if not opus_payload:
                        break
                    await self.omni_ws.send_bytes(bytes([FRAME_AUDIO]) + opus_payload)
                    self.frames_in += 1
        finally:
            if self.listen_ws is ws:
                self.listen_ws = None
            self.touch()

    async def _speak_send_loop(self, ws: web.WebSocketResponse) -> None:
        while not ws.closed and not self._closed:
            try:
                item = await asyncio.wait_for(self.outbound_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if isinstance(item, bytes):
                await ws.send_bytes(item)
            else:
                await ws.send_str(item)

    async def _speak_receive_loop(self, ws: web.WebSocketResponse) -> None:
        async for msg in ws:
            if msg.type == web.WSMsgType.ERROR:
                raise RuntimeError(f"speak ws error: {ws.exception()}")
            if msg.type in (web.WSMsgType.CLOSE, web.WSMsgType.CLOSED):
                break
            # We ignore any client messages on speak leg.
            self.touch()

    async def handle_speak(self, ws: web.WebSocketResponse) -> None:
        if self.speak_ws is not None and not self.speak_ws.closed and self.speak_ws is not ws:
            await self.speak_ws.close(code=1000, message=b"speak leg replaced")
        self.speak_ws = ws
        self.touch()
        await self.ensure_upstream()

        sender = asyncio.create_task(self._speak_send_loop(ws), name=f"two-leg-send-{self.call_id}")
        receiver = asyncio.create_task(self._speak_receive_loop(ws), name=f"two-leg-recv-{self.call_id}")
        done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc:
                raise exc

        if self.speak_ws is ws:
            self.speak_ws = None
        self.touch()

    def is_idle(self, now: float, idle_sec: float) -> bool:
        listen_alive = self.listen_ws is not None and not self.listen_ws.closed
        speak_alive = self.speak_ws is not None and not self.speak_ws.closed
        return (not listen_alive) and (not speak_alive) and (now - self.last_activity >= idle_sec)

    async def close(self, reason: str) -> None:
        if self._closed:
            return
        self._closed = True
        LOG.info(
            "[%s] closing reason=%s in=%d out=%d dropped=%d",
            self.call_id,
            reason,
            self.frames_in,
            self.frames_out,
            self.frames_dropped,
        )
        if self.upstream_reader_task is not None:
            self.upstream_reader_task.cancel()
            self.upstream_reader_task = None
        if self.omni_ws is not None and not self.omni_ws.closed:
            await self.omni_ws.close()
        if self.http_session is not None and not self.http_session.closed:
            await self.http_session.close()
        if self.listen_ws is not None and not self.listen_ws.closed:
            with contextlib.suppress(Exception):
                await self.listen_ws.close()
        if self.speak_ws is not None and not self.speak_ws.closed:
            with contextlib.suppress(Exception):
                await self.speak_ws.close()


class SessionRegistry:
    def __init__(self, cfg: GatewayConfig) -> None:
        self.cfg = cfg
        self._sessions: Dict[str, TwoLegSession] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, call_id: str, query: Dict[str, str], remote: str) -> TwoLegSession:
        async with self._lock:
            session = self._sessions.get(call_id)
            if session is None or session.closed or session.is_idle(time.monotonic(), self.cfg.session_idle_sec):
                # Explicitly close the old session if it exists to clean up resources
                if session is not None:
                    await session.close()
                session = TwoLegSession(call_id=call_id, cfg=self.cfg, query=query, remote=remote)
                self._sessions[call_id] = session
            else:
                session.merge_query(query)
            return session

    async def cleanup_idle(self) -> None:
        now = time.monotonic()
        stale: Dict[str, TwoLegSession] = {}
        async with self._lock:
            for call_id, session in list(self._sessions.items()):
                if session.is_idle(now, self.cfg.session_idle_sec):
                    stale[call_id] = session
                    del self._sessions[call_id]
        for call_id, session in stale.items():
            LOG.info("[%s] removing idle session", call_id)
            await session.close(reason="idle timeout")

    async def close_all(self) -> None:
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            await session.close(reason="shutdown")

    def active_count(self) -> int:
        return len(self._sessions)


def _require_call_uuid(request: web.Request) -> str:
    call_id = str(request.query.get("call_uuid") or "").strip()
    if not call_id:
        raise web.HTTPBadRequest(text="call_uuid is required for two-leg mode")
    return call_id


async def ws_listen(request: web.Request) -> web.WebSocketResponse:
    cfg: GatewayConfig = request.app["cfg"]
    reg: SessionRegistry = request.app["sessions"]
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    call_id = ""
    try:
        call_id = _require_call_uuid(request)
        session = await reg.get_or_create(call_id, dict(request.query), request.remote or "unknown")
        await session.handle_listen(ws)
    except web.HTTPException as exc:
        await ws.send_str(json.dumps({"error": exc.text}))
        await ws.close(code=1008, message=exc.text.encode("utf-8", errors="ignore"))
    except Exception as exc:
        LOG.exception("[%s] listen failed: %s", call_id or "-", exc)
        if not ws.closed:
            await ws.close(code=1011, message=b"listen bridge failed")
    finally:
        if not ws.closed:
            await ws.close()
    return ws


async def ws_speak(request: web.Request) -> web.WebSocketResponse:
    cfg: GatewayConfig = request.app["cfg"]
    reg: SessionRegistry = request.app["sessions"]
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    call_id = ""
    try:
        call_id = _require_call_uuid(request)
        session = await reg.get_or_create(call_id, dict(request.query), request.remote or "unknown")
        await session.handle_speak(ws)
    except web.HTTPException as exc:
        await ws.send_str(json.dumps({"error": exc.text}))
        await ws.close(code=1008, message=exc.text.encode("utf-8", errors="ignore"))
    except Exception as exc:
        LOG.exception("[%s] speak failed: %s", call_id or "-", exc)
        if not ws.closed:
            await ws.close(code=1011, message=b"speak bridge failed")
    finally:
        if not ws.closed:
            await ws.close()
    return ws


async def health(request: web.Request) -> web.Response:
    reg: SessionRegistry = request.app["sessions"]
    return web.json_response({"status": "ok", "active_sessions": reg.active_count()})


async def cleanup_worker(app: web.Application) -> None:
    cfg: GatewayConfig = app["cfg"]
    reg: SessionRegistry = app["sessions"]
    interval = max(5.0, min(30.0, cfg.session_idle_sec / 2.0))
    try:
        while True:
            await asyncio.sleep(interval)
            await reg.cleanup_idle()
    except asyncio.CancelledError:
        return


async def on_startup(app: web.Application) -> None:
    app["cleanup_task"] = asyncio.create_task(cleanup_worker(app), name="two-leg-cleanup")


async def on_cleanup(app: web.Application) -> None:
    task: Optional[asyncio.Task] = app.get("cleanup_task")
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    reg: SessionRegistry = app["sessions"]
    await reg.close_all()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Two-leg FreeSWITCH/media websocket bridge (/listen + /speak)"
    )
    parser.add_argument("--host", default=os.getenv("VOICE_GATEWAY_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("VOICE_GATEWAY_PORT", "8099")))
    parser.add_argument("--listen-endpoint", default=os.getenv("VOICE_GATEWAY_LISTEN_ENDPOINT", "/listen"))
    parser.add_argument("--speak-endpoint", default=os.getenv("VOICE_GATEWAY_SPEAK_ENDPOINT", "/speak"))

    parser.add_argument(
        "--omnicortex-voice-ws",
        default=os.getenv("OMNICORTEX_VOICE_WS", "ws://127.0.0.1:8000/voice/ws"),
        help="Upstream OmniCortex websocket endpoint",
    )
    parser.add_argument("--default-agent-id", default=os.getenv("VOICE_GATEWAY_AGENT_ID", ""))
    parser.add_argument("--default-token", default=os.getenv("VOICE_GATEWAY_TOKEN", ""))
    parser.add_argument("--default-voice-prompt", default=os.getenv("VOICE_GATEWAY_VOICE_PROMPT", "NATF0.pt"))
    parser.add_argument("--default-seed", default=os.getenv("VOICE_GATEWAY_SEED", "-1"))
    parser.add_argument("--default-context-query", default=os.getenv("VOICE_GATEWAY_CONTEXT_QUERY", ""))

    parser.add_argument(
        "--inbound-mode",
        choices=["pcm16", "moshi"],
        default=os.getenv("VOICE_GATEWAY_INBOUND_MODE", "pcm16"),
        help="Format received on /listen",
    )
    parser.add_argument(
        "--outbound-mode",
        choices=["pcm16", "moshi"],
        default=os.getenv("VOICE_GATEWAY_OUTBOUND_MODE", "pcm16"),
        help="Format sent on /speak",
    )
    parser.add_argument("--fs-sample-rate", type=int, default=int(os.getenv("VOICE_GATEWAY_FS_SR", "8000")))
    parser.add_argument("--moshi-sample-rate", type=int, default=int(os.getenv("VOICE_GATEWAY_MOSHI_SR", "24000")))
    parser.add_argument(
        "--forward-text-frames",
        action="store_true",
        default=_to_bool(os.getenv("VOICE_GATEWAY_FORWARD_TEXT_FRAMES", "0")),
    )
    parser.add_argument(
        "--upstream-ssl-verify",
        action="store_true",
        default=_to_bool(os.getenv("VOICE_GATEWAY_UPSTREAM_SSL_VERIFY", "0")),
    )
    parser.add_argument("--upstream-timeout-sec", type=float, default=float(os.getenv("VOICE_GATEWAY_TIMEOUT_SEC", "1800")))
    parser.add_argument("--session-idle-sec", type=float, default=float(os.getenv("VOICE_GATEWAY_SESSION_IDLE_SEC", "45")))
    parser.add_argument("--outbound-queue-max", type=int, default=int(os.getenv("VOICE_GATEWAY_OUTBOUND_QUEUE_MAX", "400")))
    parser.add_argument("--barge-in-enabled", action="store_true", default=_to_bool(os.getenv("VOICE_GATEWAY_BARGE_IN", "1")))
    parser.add_argument(
        "--barge-in-rms-threshold",
        type=float,
        default=float(os.getenv("VOICE_GATEWAY_BARGE_IN_RMS", "0.02")),
    )
    parser.add_argument(
        "--barge-in-min-interval-sec",
        type=float,
        default=float(os.getenv("VOICE_GATEWAY_BARGE_IN_MIN_INTERVAL_SEC", "0.35")),
    )
    parser.add_argument(
        "--barge-in-send-interrupt",
        action="store_true",
        default=_to_bool(os.getenv("VOICE_GATEWAY_BARGE_IN_SEND_INTERRUPT", "1")),
    )
    parser.add_argument("--ssl-cert", default=os.getenv("VOICE_GATEWAY_SSL_CERT", ""))
    parser.add_argument("--ssl-key", default=os.getenv("VOICE_GATEWAY_SSL_KEY", ""))
    parser.add_argument("--log-level", default=os.getenv("VOICE_GATEWAY_LOG_LEVEL", "INFO"))
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = GatewayConfig(
        host=args.host,
        port=args.port,
        listen_endpoint=args.listen_endpoint,
        speak_endpoint=args.speak_endpoint,
        omnicortex_voice_ws=args.omnicortex_voice_ws,
        default_agent_id=args.default_agent_id,
        default_token=args.default_token,
        default_voice_prompt=args.default_voice_prompt,
        default_seed=args.default_seed,
        default_context_query=args.default_context_query,
        inbound_mode=args.inbound_mode,
        outbound_mode=args.outbound_mode,
        fs_sample_rate=args.fs_sample_rate,
        moshi_sample_rate=args.moshi_sample_rate,
        forward_text_frames=args.forward_text_frames,
        upstream_ssl_verify=args.upstream_ssl_verify,
        upstream_timeout_sec=args.upstream_timeout_sec,
        session_idle_sec=args.session_idle_sec,
        outbound_queue_max=max(50, args.outbound_queue_max),
        barge_in_enabled=args.barge_in_enabled,
        barge_in_rms_threshold=max(0.0, args.barge_in_rms_threshold),
        barge_in_min_interval_sec=max(0.05, args.barge_in_min_interval_sec),
        barge_in_send_interrupt=args.barge_in_send_interrupt,
    )

    app = web.Application()
    app["cfg"] = cfg
    app["sessions"] = SessionRegistry(cfg)
    app.router.add_get(cfg.listen_endpoint, ws_listen)
    app.router.add_get(cfg.speak_endpoint, ws_speak)
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
        "starting two-leg gateway host=%s port=%s listen=%s speak=%s upstream=%s inbound=%s outbound=%s barge_in=%s",
        cfg.host,
        cfg.port,
        cfg.listen_endpoint,
        cfg.speak_endpoint,
        cfg.omnicortex_voice_ws,
        cfg.inbound_mode,
        cfg.outbound_mode,
        cfg.barge_in_enabled,
    )
    web.run_app(app, host=cfg.host, port=cfg.port, ssl_context=ssl_context)


if __name__ == "__main__":
    main()
