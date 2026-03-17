#!/usr/bin/env python3
"""
Voice Gateway: FreeSWITCH WS <-> OmniCortex /voice/ws bridge.

Expected flow:
1) FreeSWITCH (or your dialer media gateway) connects to /calls over WS/WSS.
2) This service opens upstream WS to OmniCortex /voice/ws.
3) Audio is bridged in both directions:
   - Inbound from FS:
     - mode=pcm16 (default): raw mono PCM16-LE bytes.
     - mode=moshi: already in Moshi frame format (0x01 + opus payload).
   - Upstream from OmniCortex/Moshi:
     - kind 0x01: opus audio payload.
     - kind 0x02/0x03: text/control frames (logged).

Notes:
- For pcm16 mode, this gateway transcodes PCM16 <-> Opus using sphn.
- Sample-rate conversion uses linear interpolation (good enough for real-time bridge).
- Run this in a Python environment that has: aiohttp, numpy, sphn.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import ssl
import urllib.parse
import uuid
from dataclasses import dataclass
from typing import Optional

import aiohttp
import numpy as np
import sphn
from aiohttp import web


LOG = logging.getLogger("voice_gateway")

FRAME_HANDSHAKE = 0x00
FRAME_AUDIO = 0x01
FRAME_TEXT = 0x02
FRAME_CTRL = 0x03


def _to_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float32_to_int16_bytes(samples: np.ndarray) -> bytes:
    clipped = np.clip(samples, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16).tobytes()


def _int16_bytes_to_float32(payload: bytes) -> np.ndarray:
    if not payload:
        return np.zeros((0,), dtype=np.float32)
    arr = np.frombuffer(payload, dtype=np.int16).astype(np.float32)
    return arr / 32768.0


def _resample_linear(samples: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr or samples.size == 0:
        return samples.astype(np.float32, copy=False)
    src_len = samples.shape[0]
    dst_len = int(round(src_len * float(dst_sr) / float(src_sr)))
    if dst_len <= 1:
        return np.zeros((0,), dtype=np.float32)
    src_x = np.linspace(0.0, 1.0, num=src_len, endpoint=True)
    dst_x = np.linspace(0.0, 1.0, num=dst_len, endpoint=True)
    out = np.interp(dst_x, src_x, samples).astype(np.float32)
    return out


@dataclass
class GatewayConfig:
    host: str
    port: int
    endpoint: str
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


class BridgeSession:
    def __init__(self, fs_ws: web.WebSocketResponse, cfg: GatewayConfig, request: web.Request) -> None:
        self.fs_ws = fs_ws
        self.cfg = cfg
        self.request = request
        self.call_id = request.query.get("call_uuid") or str(uuid.uuid4())
        self.closed = False
        self.client = request.remote or "unknown"

        self.opus_writer = sphn.OpusStreamWriter(cfg.moshi_sample_rate)
        self.opus_reader = sphn.OpusStreamReader(cfg.moshi_sample_rate)
        self.omni_ws: Optional[aiohttp.ClientWebSocketResponse] = None

    def _build_upstream_url(self) -> str:
        q = self.request.query

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

    async def run(self) -> None:
        upstream_url = self._build_upstream_url()
        LOG.info("[%s] connect fs=%s upstream=%s", self.call_id, self.client, upstream_url)

        timeout = aiohttp.ClientTimeout(total=self.cfg.upstream_timeout_sec)
        ssl_ctx = None
        if upstream_url.startswith("wss://") and not self.cfg.upstream_ssl_verify:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(upstream_url, ssl=ssl_ctx) as omni_ws:
                self.omni_ws = omni_ws
                tasks = [
                    asyncio.create_task(self._fs_to_omni_loop()),
                    asyncio.create_task(self._omni_to_fs_loop()),
                ]
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                for task in done:
                    exc = task.exception()
                    if exc:
                        raise exc

    async def _fs_to_omni_loop(self) -> None:
        assert self.omni_ws is not None
        async for msg in self.fs_ws:
            if msg.type == web.WSMsgType.ERROR:
                raise RuntimeError(f"FS websocket error: {self.fs_ws.exception()}")
            if msg.type in (web.WSMsgType.CLOSE, web.WSMsgType.CLOSED):
                break
            if msg.type == web.WSMsgType.TEXT:
                LOG.debug("[%s] fs text: %s", self.call_id, msg.data)
                continue
            if msg.type != web.WSMsgType.BINARY:
                continue

            data = bytes(msg.data)
            if not data:
                continue

            if self.cfg.inbound_mode == "moshi":
                # Pass-through if already framed, otherwise wrap as audio frame.
                if data[0] in (FRAME_HANDSHAKE, FRAME_AUDIO, FRAME_TEXT, FRAME_CTRL):
                    await self.omni_ws.send_bytes(data)
                else:
                    await self.omni_ws.send_bytes(bytes([FRAME_AUDIO]) + data)
                continue

            # inbound_mode == pcm16: raw PCM16 mono LE -> Opus -> Moshi frame 0x01
            pcm_fs = _int16_bytes_to_float32(data)
            pcm_moshi = _resample_linear(pcm_fs, self.cfg.fs_sample_rate, self.cfg.moshi_sample_rate)
            if pcm_moshi.size == 0:
                continue
            self.opus_writer.append_pcm(pcm_moshi)

            while True:
                opus_payload = self.opus_writer.read_bytes()
                if not opus_payload:
                    break
                await self.omni_ws.send_bytes(bytes([FRAME_AUDIO]) + opus_payload)

    async def _omni_to_fs_loop(self) -> None:
        assert self.omni_ws is not None
        async for msg in self.omni_ws:
            if msg.type == aiohttp.WSMsgType.ERROR:
                raise RuntimeError(f"Omni websocket error: {self.omni_ws.exception()}")
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
                LOG.info("[%s] upstream handshake received", self.call_id)
                continue

            if kind == FRAME_TEXT:
                if self.cfg.forward_text_frames:
                    await self.fs_ws.send_str(payload.decode("utf-8", errors="ignore"))
                else:
                    LOG.debug("[%s] upstream text: %s", self.call_id, payload.decode("utf-8", errors="ignore"))
                continue

            if kind == FRAME_CTRL:
                LOG.debug("[%s] upstream ctrl: %s", self.call_id, payload.decode("utf-8", errors="ignore"))
                continue

            if kind != FRAME_AUDIO:
                LOG.warning("[%s] unknown upstream frame kind=%s", self.call_id, kind)
                continue

            if self.cfg.outbound_mode == "moshi":
                await self.fs_ws.send_bytes(data)
                continue

            # outbound_mode == pcm16: Opus payload -> PCM float -> resample -> PCM16
            self.opus_reader.append_bytes(payload)
            pcm_moshi = self.opus_reader.read_pcm()
            if pcm_moshi is None:
                continue
            if isinstance(pcm_moshi, np.ndarray):
                arr = pcm_moshi
            else:
                arr = np.asarray(pcm_moshi)
            if arr.size == 0:
                continue
            # sphn may return shape (T,) or (C,T); normalize to mono (T,)
            if arr.ndim == 2:
                arr = arr[0]
            arr = arr.astype(np.float32, copy=False)
            pcm_fs = _resample_linear(arr, self.cfg.moshi_sample_rate, self.cfg.fs_sample_rate)
            await self.fs_ws.send_bytes(_float32_to_int16_bytes(pcm_fs))


async def ws_calls(request: web.Request) -> web.WebSocketResponse:
    cfg: GatewayConfig = request.app["cfg"]
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    session = BridgeSession(ws, cfg, request)
    try:
        await session.run()
    except web.HTTPException as exc:
        LOG.warning("[%s] bad request: %s", session.call_id, exc.text)
        if not ws.closed:
            await ws.send_str(json.dumps({"error": exc.text}))
            await ws.close(code=1008, message=exc.text.encode("utf-8", errors="ignore"))
    except Exception as exc:
        LOG.exception("[%s] bridge failed: %s", session.call_id, exc)
        if not ws.closed:
            await ws.close(code=1011, message=b"bridge failed")
    finally:
        if not ws.closed:
            await ws.close()
        LOG.info("[%s] disconnected", session.call_id)
    return ws


async def health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FreeSWITCH <-> OmniCortex voice websocket bridge")
    parser.add_argument("--host", default=os.getenv("VOICE_GATEWAY_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("VOICE_GATEWAY_PORT", "8099")))
    parser.add_argument("--endpoint", default=os.getenv("VOICE_GATEWAY_ENDPOINT", "/calls"))

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
        help="Format received from /calls client",
    )
    parser.add_argument(
        "--outbound-mode",
        choices=["pcm16", "moshi"],
        default=os.getenv("VOICE_GATEWAY_OUTBOUND_MODE", "pcm16"),
        help="Format sent to /calls client",
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
        help="Enable TLS verification for wss upstream",
    )
    parser.add_argument("--upstream-timeout-sec", type=float, default=float(os.getenv("VOICE_GATEWAY_TIMEOUT_SEC", "1800")))
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
        endpoint=args.endpoint,
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
    )

    app = web.Application()
    app["cfg"] = cfg
    app.router.add_get(cfg.endpoint, ws_calls)
    app.router.add_get("/health", health)

    ssl_context = None
    if args.ssl_cert or args.ssl_key:
        if not args.ssl_cert or not args.ssl_key:
            raise RuntimeError("Both --ssl-cert and --ssl-key are required for TLS")
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(args.ssl_cert, args.ssl_key)

    LOG.info(
        "starting gateway host=%s port=%s endpoint=%s upstream=%s inbound=%s outbound=%s",
        cfg.host,
        cfg.port,
        cfg.endpoint,
        cfg.omnicortex_voice_ws,
        cfg.inbound_mode,
        cfg.outbound_mode,
    )
    web.run_app(app, host=cfg.host, port=cfg.port, ssl_context=ssl_context)


if __name__ == "__main__":
    main()
