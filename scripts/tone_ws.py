from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Optional

import numpy as np
from aiohttp import web


LOG = logging.getLogger("tone_ws")


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


@dataclass
class Config:
    host: str
    port: int
    path: str
    health_path: str
    sample_rate: int
    frame_ms: int
    tone_hz: float
    amplitude: float
    start_delay_ms: int
    send_fs_connected_ack: bool
    wait_for_input: bool
    log_every: int


class ToneService:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.app = web.Application()
        self.app.router.add_get(cfg.health_path, self.handle_health)
        self.app.router.add_get(cfg.path, self.handle_calls)
        normalized_path = cfg.path.rstrip("/") or "/"
        if normalized_path != cfg.path:
            self.app.router.add_get(normalized_path, self.handle_calls)
        if normalized_path != "/":
            self.app.router.add_get(normalized_path + "/", self.handle_calls)
            if cfg.health_path != "/":
                self.app.router.add_get("/", self.handle_calls)
        self.active_calls = 0

    async def handle_health(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "ok",
                "active_calls": self.active_calls,
                "sample_rate": self.cfg.sample_rate,
                "frame_ms": self.cfg.frame_ms,
                "tone_hz": self.cfg.tone_hz,
                "amplitude": self.cfg.amplitude,
            }
        )

    async def handle_calls(self, request: web.Request) -> web.StreamResponse:
        LOG.info(
            "incoming tone request remote=%s path=%s upgrade=%s user-agent=%s",
            request.remote or "unknown",
            request.path_qs,
            request.headers.get("Upgrade"),
            request.headers.get("User-Agent"),
        )
        ws = web.WebSocketResponse(max_msg_size=16 * 1024 * 1024)
        await ws.prepare(request)
        self.active_calls += 1
        call = ToneCall(self, request, ws)
        try:
            await call.run()
        finally:
            self.active_calls -= 1
        return ws


class ToneCall:
    def __init__(self, service: ToneService, request: web.Request, fs_ws: web.WebSocketResponse) -> None:
        self.service = service
        self.cfg = service.cfg
        self.request = request
        self.fs_ws = fs_ws
        self.call_id = _normalize_text(request.query.get("call_uuid")) or "no-call-id"
        self.remote = request.remote or "unknown"
        self.closed = False
        self.started = False
        self.input_ack_sent = False
        self.start_event = asyncio.Event()
        self.fs_send_lock = asyncio.Lock()
        self.frames_sent = 0
        self.bytes_sent = 0
        self.frames_rx = 0
        self.bytes_rx = 0

        self.samples_per_frame = self.cfg.sample_rate * self.cfg.frame_ms // 1000
        self.phase = 0.0
        self.phase_step = (2.0 * math.pi * self.cfg.tone_hz) / float(self.cfg.sample_rate)

        if not self.cfg.wait_for_input:
            self.start_event.set()

    def log(self, message: str, *args: object, level: int = logging.INFO) -> None:
        LOG.log(level, "[%s] " + message, self.call_id, *args)

    def _generate_frame(self) -> bytes:
        indices = self.phase + self.phase_step * np.arange(self.samples_per_frame, dtype=np.float32)
        samples = (self.cfg.amplitude * np.sin(indices)).astype(np.float32)
        self.phase = float((self.phase + self.phase_step * self.samples_per_frame) % (2.0 * math.pi))
        return (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()

    async def _send_pcm_to_fs(self, pcm16_bytes: bytes) -> None:
        if self.fs_ws.closed or not pcm16_bytes:
            return
        async with self.fs_send_lock:
            await self.fs_ws.send_bytes(pcm16_bytes)
        self.frames_sent += 1
        self.bytes_sent += len(pcm16_bytes)
        if self.frames_sent == 1 or (self.cfg.log_every > 0 and self.frames_sent % self.cfg.log_every == 0):
            self.log(
                "sent tone frame count=%s chunk_bytes=%s total_bytes=%s",
                self.frames_sent,
                len(pcm16_bytes),
                self.bytes_sent,
            )

    async def _recv_loop(self) -> None:
        async for msg in self.fs_ws:
            if msg.type in (web.WSMsgType.CLOSE, web.WSMsgType.CLOSED):
                return
            if msg.type == web.WSMsgType.ERROR:
                raise RuntimeError(f"FreeSWITCH websocket error: {self.fs_ws.exception()}")
            if msg.type == web.WSMsgType.TEXT:
                if not self.started:
                    self.started = True
                    self.start_event.set()
                    self.log("media start triggered by text frame")
                self.log("FreeSWITCH text=%s", msg.data, level=logging.DEBUG)
                if self.cfg.send_fs_connected_ack and not self.input_ack_sent:
                    self.input_ack_sent = True
                    await self.fs_ws.send_str(json.dumps({"type": "connected", "protocol": "audio"}))
                    self.log("sent connected ack")
                continue
            if msg.type != web.WSMsgType.BINARY:
                continue
            payload = bytes(msg.data)
            if not payload:
                continue
            if not self.started:
                self.started = True
                self.start_event.set()
                self.log("media start triggered by binary frame")
            self.frames_rx += 1
            self.bytes_rx += len(payload)
            if self.frames_rx == 1 or (self.cfg.log_every > 0 and self.frames_rx % self.cfg.log_every == 0):
                self.log(
                    "received fs audio count=%s chunk_bytes=%s total_bytes=%s",
                    self.frames_rx,
                    len(payload),
                    self.bytes_rx,
                )

    async def _send_loop(self) -> None:
        await self.start_event.wait()
        if self.cfg.start_delay_ms > 0:
            await asyncio.sleep(self.cfg.start_delay_ms / 1000.0)

        tick = self.cfg.frame_ms / 1000.0
        next_deadline = time.monotonic()
        while not self.closed and not self.fs_ws.closed:
            await self._send_pcm_to_fs(self._generate_frame())
            next_deadline += tick
            sleep_for = next_deadline - time.monotonic()
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
            else:
                next_deadline = time.monotonic()

    async def run(self) -> None:
        self.log(
            "accepted connection remote=%s path=%s sample_rate=%s frame_ms=%s tone_hz=%s amplitude=%.3f",
            self.remote,
            self.request.path,
            self.cfg.sample_rate,
            self.cfg.frame_ms,
            self.cfg.tone_hz,
            self.cfg.amplitude,
        )
        send_task = asyncio.create_task(self._send_loop(), name="tone_send")
        recv_task = asyncio.create_task(self._recv_loop(), name="tone_recv")
        try:
            done, pending = await asyncio.wait(
                [send_task, recv_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            self.log(
                "task completion first_done=%s pending=%s",
                [task.get_name() for task in done],
                [task.get_name() for task in pending],
            )
            for task in pending:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            for task in done:
                exc = task.exception()
                if exc is None:
                    self.log("task finished cleanly name=%s", task.get_name())
                else:
                    self.log("task finished with error name=%s err=%s", task.get_name(), exc, level=logging.ERROR)
                if exc:
                    raise exc
        finally:
            self.closed = True
            with suppress(Exception):
                await self.fs_ws.close()
            self.log(
                "session closed frames_sent=%s bytes_sent=%s frames_rx=%s bytes_rx=%s",
                self.frames_sent,
                self.bytes_sent,
                self.frames_rx,
                self.bytes_rx,
            )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minimal 16 kHz PCM tone websocket server for FreeSWITCH playback tests")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--path", default="/calls")
    parser.add_argument("--health-path", default="/healthz")
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--frame-ms", type=int, default=20)
    parser.add_argument("--tone-hz", type=float, default=1000.0)
    parser.add_argument("--amplitude", type=float, default=0.20)
    parser.add_argument("--start-delay-ms", type=int, default=0)
    parser.add_argument("--send-fs-connected-ack", action="store_true")
    parser.add_argument("--wait-for-input", action="store_true")
    parser.add_argument("--log-every", type=int, default=50)
    parser.add_argument("--debug", action="store_true")
    return parser


def _validate_config(args: argparse.Namespace) -> Config:
    if args.sample_rate <= 0:
        raise SystemExit("--sample-rate must be > 0")
    if args.frame_ms <= 0:
        raise SystemExit("--frame-ms must be > 0")
    if args.tone_hz <= 0:
        raise SystemExit("--tone-hz must be > 0")
    if not (0.0 < args.amplitude <= 1.0):
        raise SystemExit("--amplitude must be in the range (0, 1]")
    if args.start_delay_ms < 0:
        raise SystemExit("--start-delay-ms must be >= 0")
    samples_per_frame = args.sample_rate * args.frame_ms // 1000
    if samples_per_frame <= 0:
        raise SystemExit("sample_rate/frame_ms combination produced an empty frame")
    return Config(
        host=args.host,
        port=args.port,
        path=args.path,
        health_path=args.health_path,
        sample_rate=args.sample_rate,
        frame_ms=args.frame_ms,
        tone_hz=args.tone_hz,
        amplitude=args.amplitude,
        start_delay_ms=args.start_delay_ms,
        send_fs_connected_ack=args.send_fs_connected_ack,
        wait_for_input=args.wait_for_input,
        log_every=args.log_every,
    )


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    cfg = _validate_config(args)
    app = ToneService(cfg).app
    LOG.info(
        "starting tone websocket host=%s port=%s path=%s sample_rate=%s frame_ms=%s tone_hz=%s amplitude=%.3f",
        cfg.host,
        cfg.port,
        cfg.path,
        cfg.sample_rate,
        cfg.frame_ms,
        cfg.tone_hz,
        cfg.amplitude,
    )
    web.run_app(app, host=cfg.host, port=cfg.port)


if __name__ == "__main__":
    main()
