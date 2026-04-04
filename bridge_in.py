#!/usr/bin/env python3
"""
bridge_in.py

Inbound telephony bridge:
- Accepts media websocket from FreeSWITCH/dialer on /listen
- Forwards frames to brain_orchestrator /ingest/{call_id}
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import json
import logging
import os
import ssl
import urllib.parse
from typing import Dict, Optional, Tuple

import aiohttp
from aiohttp import web

try:
    import audioop  # Deprecated in newer Python, still available on most runtimes.
except Exception:  # pragma: no cover - best effort compatibility
    audioop = None


LOG = logging.getLogger("bridge_in")

DEFAULT_ORCH_INGEST_WS = "ws://127.0.0.1:8101/ingest"


def _to_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_call_id(request: web.Request) -> str:
    # Preferred: explicit query key from dialplan.
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
    raise web.HTTPBadRequest(text="call UUID missing (use call_uuid query param or /freeswitch/{call_id})")


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


def _get_nested(mapping: Dict[str, object], path: Tuple[str, ...]) -> Optional[object]:
    node: object = mapping
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _codec_hint(event_obj: Dict[str, object]) -> str:
    for path in (
        ("codec",),
        ("encoding",),
        ("format",),
        ("media", "codec"),
        ("media", "encoding"),
        ("audio", "codec"),
        ("audio", "encoding"),
        ("stream", "codec"),
        ("stream", "encoding"),
    ):
        value = _get_nested(event_obj, path)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    return ""


def _decode_fs_audio_bytes(audio_bytes: bytes, codec: str) -> bytes:
    normalized_codec = str(codec or "").strip().upper()
    if not audio_bytes or not normalized_codec or normalized_codec in {"PCM16", "L16", "LINEAR16"}:
        return audio_bytes
    if audioop is None:
        return audio_bytes
    if normalized_codec in {"PCMU", "MULAW", "G711U", "G.711U"}:
        return audioop.ulaw2lin(audio_bytes, 2)
    if normalized_codec in {"PCMA", "ALAW", "G711A", "G.711A"}:
        return audioop.alaw2lin(audio_bytes, 2)
    return audio_bytes


def _decode_text_media_payload(payload_text: str, default_codec: str) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Decode possible JSON media payloads from FreeSWITCH/mod_audio_fork-like sources.
    Returns: (audio_bytes_or_none, event_type_or_none)
    """
    try:
        parsed = json.loads(payload_text)
    except Exception:
        return None, None

    if not isinstance(parsed, dict):
        return None, None

    event_type_raw = parsed.get("event") or parsed.get("type") or parsed.get("message")
    event_type = str(event_type_raw).strip().lower() if event_type_raw is not None else None

    raw_payload: Optional[object] = None
    for path in (
        ("media", "payload"),
        ("audio", "payload"),
        ("payload",),
        ("media", "data"),
        ("audio", "data"),
        ("data",),
        ("chunk",),
    ):
        candidate = _get_nested(parsed, path)
        if candidate is not None:
            raw_payload = candidate
            break

    if raw_payload is None:
        return None, event_type

    decoded: Optional[bytes] = None
    if isinstance(raw_payload, str):
        text = raw_payload.strip()
        if not text:
            return None, event_type
        try:
            decoded = base64.b64decode(text, validate=False)
        except Exception:
            return None, event_type
    elif isinstance(raw_payload, list):
        try:
            decoded = bytes(int(x) & 0xFF for x in raw_payload)
        except Exception:
            return None, event_type
    elif isinstance(raw_payload, (bytes, bytearray)):
        decoded = bytes(raw_payload)

    if not decoded:
        return None, event_type

    codec = _codec_hint(parsed) or default_codec
    try:
        decoded = _decode_fs_audio_bytes(decoded, codec)
    except Exception:
        pass

    return decoded, event_type


async def _drain_upstream(ws: aiohttp.ClientWebSocketResponse, call_id: str) -> None:
    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.ERROR:
            raise RuntimeError(f"upstream ingest ws error: {ws.exception()}")
        if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
            break
        if msg.type == aiohttp.WSMsgType.TEXT:
            LOG.debug("[%s] orchestrator ingest text: %s", call_id, msg.data)


async def ws_listen(request: web.Request) -> web.WebSocketResponse:
    cfg = request.app["cfg"]
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    call_id = "-"
    try:
        call_id = _resolve_call_id(request)
        target = _build_orchestrator_url(cfg["orchestrator_ingest_ws"], call_id, dict(request.query))
        headers = _build_orchestrator_headers(dict(request.query))
        remote = request.remote or "-"

        LOG.info(
            "[%s] bridge_in accepted remote=%s path=%s",
            call_id,
            remote,
            request.path,
        )

        timeout = aiohttp.ClientTimeout(total=cfg["upstream_timeout_sec"])
        ssl_ctx: object = False
        if target.startswith("wss://"):
            if cfg["upstream_ssl_verify"]:
                ssl_ctx = True
            else:
                ssl_ctx = ssl.create_default_context()
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE

        LOG.info("[%s] bridge_in connect orchestrator=%s", call_id, target)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(target, ssl=ssl_ctx, headers=headers or None) as upstream:
                upstream_drain = asyncio.create_task(_drain_upstream(upstream, call_id))
                forwarded_binary = 0
                forwarded_text_media = 0
                forwarded_text_control = 0
                dropped_text_control = 0
                try:
                    async for msg in ws:
                        if msg.type == web.WSMsgType.ERROR:
                            raise RuntimeError(f"listen ws error: {ws.exception()}")
                        if msg.type in (web.WSMsgType.CLOSE, web.WSMsgType.CLOSED):
                            break
                        if msg.type == web.WSMsgType.BINARY:
                            payload = bytes(msg.data)
                            if not payload:
                                continue
                            payload = _decode_fs_audio_bytes(payload, cfg["fs_input_codec"])
                            await upstream.send_bytes(payload)
                            forwarded_binary += 1
                            if forwarded_binary <= 3 or forwarded_binary % 100 == 0:
                                LOG.info(
                                    "[%s] bridge_in forwarded binary frames=%d (last=%d bytes)",
                                    call_id,
                                    forwarded_binary,
                                    len(payload),
                                )
                        elif msg.type == web.WSMsgType.TEXT:
                            text_data = str(msg.data)
                            audio_payload, event_type = _decode_text_media_payload(
                                text_data,
                                cfg["fs_input_codec"],
                            )
                            if audio_payload:
                                await upstream.send_bytes(audio_payload)
                                forwarded_binary += 1
                                forwarded_text_media += 1
                                if forwarded_text_media == 1 or forwarded_text_media % 100 == 0:
                                    LOG.info(
                                        "[%s] bridge_in decoded text-media frames=%d (last=%d bytes event=%s)",
                                        call_id,
                                        forwarded_text_media,
                                        len(audio_payload),
                                        event_type or "-",
                                    )
                                continue
                            if event_type:
                                LOG.debug("[%s] bridge_in control event=%s", call_id, event_type)
                                dropped_text_control += 1
                                continue
                            if cfg["forward_control_text"]:
                                await upstream.send_str(text_data)
                                forwarded_text_control += 1
                            else:
                                dropped_text_control += 1
                finally:
                    LOG.info(
                        "[%s] bridge_in summary binary=%d text_media=%d text_control=%d text_dropped=%d",
                        call_id,
                        forwarded_binary,
                        forwarded_text_media,
                        forwarded_text_control,
                        dropped_text_control,
                    )
                    upstream_drain.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await upstream_drain
    except web.HTTPException as exc:
        LOG.warning("bridge_in rejected websocket: %s (path=%s query=%s)", exc.text, request.path, request.query_string)
        await ws.send_str(exc.text)
        await ws.close(code=1008, message=exc.text.encode("utf-8", errors="ignore"))
    except Exception as exc:
        LOG.exception("[%s] bridge_in failed: %s", call_id, exc)
        if not ws.closed:
            await ws.close(code=1011, message=b"bridge_in failed")
    finally:
        if not ws.closed:
            await ws.close()
    return ws


async def health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inbound telephony websocket bridge")
    parser.add_argument("--host", default=os.getenv("BRIDGE_IN_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("BRIDGE_IN_PORT", "8001")))
    parser.add_argument("--endpoint", default=os.getenv("BRIDGE_IN_ENDPOINT", "/freeswitch"))
    parser.add_argument(
        "--orchestrator-ingest-ws",
        default=os.getenv("ORCH_INGEST_WS", DEFAULT_ORCH_INGEST_WS),
    )
    parser.add_argument("--upstream-timeout-sec", type=float, default=float(os.getenv("VOICE_GATEWAY_TIMEOUT_SEC", "1800")))
    parser.add_argument("--upstream-ssl-verify", action="store_true", default=_to_bool(os.getenv("VOICE_GATEWAY_UPSTREAM_SSL_VERIFY", "0")))
    parser.add_argument(
        "--fs-input-codec",
        choices=["pcmu", "pcma", "pcm16"],
        default=os.getenv("BRIDGE_IN_FS_INPUT_CODEC", "pcmu").strip().lower(),
        help="Codec received from FreeSWITCH audio_fork before forwarding to orchestrator.",
    )
    parser.add_argument(
        "--forward-control-text",
        action="store_true",
        default=_to_bool(os.getenv("BRIDGE_IN_FORWARD_CONTROL_TEXT", "0")),
        help="Forward non-media text frames upstream (off by default for FS media forks).",
    )
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
        "orchestrator_ingest_ws": args.orchestrator_ingest_ws,
        "upstream_timeout_sec": args.upstream_timeout_sec,
        "upstream_ssl_verify": args.upstream_ssl_verify,
        "fs_input_codec": args.fs_input_codec,
        "forward_control_text": args.forward_control_text,
    }
    app.router.add_get(args.endpoint, ws_listen)
    app.router.add_get(f"{args.endpoint}/{{call_id}}", ws_listen)
    app.router.add_get("/health", health)

    ssl_context = None
    if args.ssl_cert or args.ssl_key:
        if not args.ssl_cert or not args.ssl_key:
            raise RuntimeError("Both --ssl-cert and --ssl-key are required for TLS")
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(args.ssl_cert, args.ssl_key)

    LOG.info(
        "starting bridge_in host=%s port=%s endpoint=%s orchestrator=%s fs_input_codec=%s",
        args.host,
        args.port,
        args.endpoint,
        args.orchestrator_ingest_ws,
        args.fs_input_codec,
    )
    web.run_app(app, host=args.host, port=args.port, ssl_context=ssl_context)


if __name__ == "__main__":
    main()
