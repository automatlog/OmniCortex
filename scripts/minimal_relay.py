from __future__ import annotations

import argparse
import asyncio
import logging
import ssl
import struct
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import urlencode

import aiohttp
import numpy as np
import opuslib
from aiohttp import web


LOG = logging.getLogger("minimal_relay")

FRAME_HANDSHAKE = 0x00
FRAME_AUDIO = 0x01
FRAME_TEXT = 0x02
FRAME_CTRL = 0x03


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def pcm16_to_f32(payload: bytes) -> np.ndarray:
    if not payload:
        return np.zeros((0,), dtype=np.float32)
    return np.frombuffer(payload, dtype="<i2").astype(np.float32) / 32768.0


def f32_to_pcm16(samples: np.ndarray) -> bytes:
    return (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def resample_linear(samples: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr or samples.size == 0:
        return samples.astype(np.float32, copy=False)
    dst_len = int(round(samples.shape[0] * float(dst_sr) / float(src_sr)))
    if dst_len <= 1:
        return np.zeros((0,), dtype=np.float32)
    src_x = np.linspace(0.0, 1.0, num=samples.shape[0], endpoint=True)
    dst_x = np.linspace(0.0, 1.0, num=dst_len, endpoint=True)
    return np.interp(dst_x, src_x, samples).astype(np.float32)


_OGG_CRC_TABLE = []
for i in range(256):
    r = i << 24
    for _ in range(8):
        r = ((r << 1) ^ 0x04C11DB7) if r & 0x80000000 else (r << 1)
    _OGG_CRC_TABLE.append(r & 0xFFFFFFFF)


def _ogg_crc(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc = ((crc << 8) ^ _OGG_CRC_TABLE[((crc >> 24) ^ byte) & 0xFF]) & 0xFFFFFFFF
    return crc


class OggDemuxer:
    def __init__(self) -> None:
        self._buf = bytearray()
        self._pages_seen = 0

    def feed(self, data: bytes) -> list[bytes]:
        self._buf.extend(data)
        packets: list[bytes] = []
        while True:
            idx = bytes(self._buf).find(b"OggS")
            if idx < 0:
                break
            if idx > 0:
                self._buf = self._buf[idx:]
            if len(self._buf) < 27:
                break
            n_segments = self._buf[26]
            header_end = 27 + n_segments
            if len(self._buf) < header_end:
                break
            seg_table = self._buf[27:header_end]
            page_data_len = sum(seg_table)
            page_end = header_end + page_data_len
            if len(self._buf) < page_end:
                break
            self._pages_seen += 1
            if self._pages_seen > 2:
                offset = header_end
                packet = bytearray()
                for seg_len in seg_table:
                    packet.extend(self._buf[offset : offset + seg_len])
                    offset += seg_len
                    if seg_len < 255:
                        if packet:
                            packets.append(bytes(packet))
                        packet = bytearray()
            self._buf = self._buf[page_end:]
        return packets


class OggMuxer:
    def __init__(self, sample_rate: int = 24000, channels: int = 1) -> None:
        self._serial = 0x44726674
        self._page_seq = 0
        self._granule = 0
        self._sample_rate = sample_rate
        self._channels = channels
        self._started = False

    def _page(self, payload: bytes, granule: int, flags: int = 0) -> bytes:
        segments = []
        remaining = len(payload)
        while remaining >= 255:
            segments.append(255)
            remaining -= 255
        segments.append(remaining)
        buf = bytearray(27 + len(segments) + len(payload))
        struct.pack_into(
            "<4sBBqIIIB",
            buf,
            0,
            b"OggS",
            0,
            flags,
            granule,
            self._serial,
            self._page_seq,
            0,
            len(segments),
        )
        buf[27 : 27 + len(segments)] = bytes(segments)
        buf[27 + len(segments) :] = payload
        struct.pack_into("<I", buf, 22, _ogg_crc(bytes(buf)))
        self._page_seq += 1
        return bytes(buf)

    def encode(self, opus_packet: bytes, samples_per_frame_48k: int) -> bytes:
        out = bytearray()
        if not self._started:
            head = struct.pack("<8sBBHIhB", b"OpusHead", 1, self._channels, 312, self._sample_rate, 0, 0)
            out.extend(self._page(head, 0, flags=0x02))
            vendor = b"minimal-relay"
            tags = struct.pack("<8sI", b"OpusTags", len(vendor)) + vendor + struct.pack("<I", 0)
            out.extend(self._page(tags, 0))
            self._started = True
        self._granule += samples_per_frame_48k
        out.extend(self._page(opus_packet, self._granule))
        return bytes(out)


@dataclass
class Config:
    host: str
    port: int
    path: str
    health_path: str
    personaplex_ws: str
    voice_prompt: str
    text_prompt: str
    text_prompt_file: str
    seed: int
    fs_sample_rate: int
    personaplex_rate: int
    frame_ms: int
    max_decode_samples: int
    ssl_verify: bool
    connect_timeout_sec: float
    send_fs_connected_ack: bool


class MinimalRelayService:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.app = web.Application()
        self.app.cleanup_ctx.append(self._lifecycle)
        self.app.router.add_get(cfg.health_path, self.handle_health)
        self.app.router.add_get(cfg.path, self.handle_calls)
        normalized_path = cfg.path.rstrip("/") or "/"
        if normalized_path != cfg.path:
            self.app.router.add_get(normalized_path, self.handle_calls)
        if normalized_path != "/":
            self.app.router.add_get(normalized_path + "/", self.handle_calls)
            self.app.router.add_get("/", self.handle_calls)
        self.http: Optional[aiohttp.ClientSession] = None
        self.last_upstream_ok_at: Optional[float] = None
        self.last_upstream_error: str = ""
        self.active_calls = 0

    async def _lifecycle(self, app: web.Application):
        timeout = aiohttp.ClientTimeout(total=max(5.0, self.cfg.connect_timeout_sec))
        self.http = aiohttp.ClientSession(timeout=timeout)
        yield
        if self.http is not None:
            await self.http.close()
            self.http = None

    async def handle_health(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "ok",
                "active_calls": self.active_calls,
                "personaplex_ws": self.cfg.personaplex_ws,
                "last_upstream_ok_at": self.last_upstream_ok_at,
                "last_upstream_error": self.last_upstream_error or None,
            }
        )

    async def handle_calls(self, request: web.Request) -> web.StreamResponse:
        LOG.info(
            "incoming minimal relay request remote=%s path=%s upgrade=%s user-agent=%s",
            request.remote or "unknown",
            request.path_qs,
            request.headers.get("Upgrade"),
            request.headers.get("User-Agent"),
        )
        ws = web.WebSocketResponse(max_msg_size=16 * 1024 * 1024)
        await ws.prepare(request)
        self.active_calls += 1
        call = MinimalRelayCall(self, request, ws)
        try:
            await call.run()
        finally:
            self.active_calls -= 1
        return ws


class MinimalRelayCall:
    def __init__(self, service: MinimalRelayService, request: web.Request, fs_ws: web.WebSocketResponse) -> None:
        self.service = service
        self.cfg = service.cfg
        self.request = request
        self.fs_ws = fs_ws
        self.call_id = _normalize_text(request.query.get("call_uuid")) or "no-call-id"
        self.remote = request.remote or "unknown"
        self.upstream_ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.handshake_event = asyncio.Event()
        self.fs_send_lock = asyncio.Lock()
        self.closed = False
        self.last_real_fs_audio_at = 0.0
        self.input_ack_sent = False
        self.output_token_bytes = bytearray()
        self.ogg_mux = OggMuxer(self.cfg.personaplex_rate)
        self.ogg_demux = OggDemuxer()
        self.encoder = opuslib.Encoder(self.cfg.personaplex_rate, 1, opuslib.APPLICATION_VOIP)
        self.decoder = opuslib.Decoder(self.cfg.personaplex_rate, 1)
        self.opus_frame_samples = self.cfg.personaplex_rate * self.cfg.frame_ms // 1000
        self.opus_48k_frame = 48000 * self.cfg.frame_ms // 1000
        self.pcm_up_buffer = np.zeros((0,), dtype=np.float32)

    def log(self, message: str, *args: object, level: int = logging.INFO) -> None:
        LOG.log(level, "[%s] " + message, self.call_id, *args)

    def _prompt_text(self) -> str:
        if self.cfg.text_prompt_file:
            return _normalize_text(Path(self.cfg.text_prompt_file).read_text(encoding="utf-8"))
        request_prompt = _normalize_text(self.request.query.get("text_prompt"))
        return request_prompt or _normalize_text(self.cfg.text_prompt) or "You are a helpful assistant."

    async def run(self) -> None:
        self.log("accepted connection remote=%s path=%s", self.remote, self.request.path)
        try:
            await self._connect_upstream()
            tasks = [
                asyncio.create_task(self._fs_to_upstream_loop(), name="fs_to_upstream"),
                asyncio.create_task(self._upstream_to_fs_loop(), name="upstream_to_fs"),
                asyncio.create_task(self._silence_pump_loop(), name="silence_pump"),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            self.log(
                "task completion first_done=%s pending=%s",
                [task.get_name() for task in done],
                [task.get_name() for task in pending],
                level=logging.INFO,
            )
            for task in pending:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            for task in done:
                exc = task.exception()
                if exc is None:
                    self.log("task finished cleanly name=%s", task.get_name(), level=logging.INFO)
                else:
                    self.log("task finished with error name=%s err=%s", task.get_name(), exc, level=logging.ERROR)
                if exc:
                    raise exc
        except Exception as exc:
            self.service.last_upstream_error = str(exc)
            self.log("minimal relay failed: %s", exc, level=logging.ERROR)
            with suppress(Exception):
                await self.fs_ws.close(code=1011, message=b"minimal relay failed")
        finally:
            self.closed = True
            if self.upstream_ws is not None and not self.upstream_ws.closed:
                with suppress(Exception):
                    await self.upstream_ws.close()
            self.log("session closed")

    async def _connect_upstream(self) -> None:
        assert self.service.http is not None
        voice_prompt = _normalize_text(self.request.query.get("voice_prompt") or self.cfg.voice_prompt) or "NATF0.pt"
        params = {
            "voice_prompt": voice_prompt,
            "text_prompt": self._prompt_text(),
            "seed": str(self.cfg.seed),
        }
        separator = "&" if "?" in self.cfg.personaplex_ws else "?"
        upstream_url = f"{self.cfg.personaplex_ws}{separator}{urlencode(params)}"
        ssl_ctx = None
        if upstream_url.startswith("wss://") and not self.cfg.ssl_verify:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
        timeout = aiohttp.ClientTimeout(total=self.cfg.connect_timeout_sec)
        self.upstream_ws = await self.service.http.ws_connect(upstream_url, ssl=ssl_ctx, timeout=timeout)
        self.service.last_upstream_ok_at = time.time()
        self.service.last_upstream_error = ""
        self.log("connected upstream=%s", self.cfg.personaplex_ws)

    def _encode_and_wrap(self, pcm_f32_24k: np.ndarray) -> bytes:
        pcm16 = f32_to_pcm16(pcm_f32_24k)
        opus_packet = self.encoder.encode(pcm16, self.opus_frame_samples)
        return bytes([FRAME_AUDIO]) + self.ogg_mux.encode(opus_packet, self.opus_48k_frame)

    async def _send_pcm_to_upstream(self, pcm16_bytes: bytes) -> None:
        assert self.upstream_ws is not None
        pcm_f32 = pcm16_to_f32(pcm16_bytes)
        pcm_24k = resample_linear(pcm_f32, self.cfg.fs_sample_rate, self.cfg.personaplex_rate)
        if pcm_24k.size == 0:
            return
        self.pcm_up_buffer = np.concatenate([self.pcm_up_buffer, pcm_24k])
        while self.pcm_up_buffer.shape[0] >= self.opus_frame_samples:
            frame = self.pcm_up_buffer[: self.opus_frame_samples]
            self.pcm_up_buffer = self.pcm_up_buffer[self.opus_frame_samples :]
            await self.upstream_ws.send_bytes(self._encode_and_wrap(frame))

    async def _send_pcm_to_fs(self, pcm16_bytes: bytes) -> None:
        if not pcm16_bytes or self.fs_ws.closed:
            return
        async with self.fs_send_lock:
            await self.fs_ws.send_bytes(pcm16_bytes)

    async def _fs_to_upstream_loop(self) -> None:
        await self.handshake_event.wait()
        async for msg in self.fs_ws:
            if msg.type in (web.WSMsgType.CLOSE, web.WSMsgType.CLOSED):
                return
            if msg.type == web.WSMsgType.ERROR:
                raise RuntimeError(f"FreeSWITCH websocket error: {self.fs_ws.exception()}")
            if msg.type == web.WSMsgType.TEXT:
                self.log("FreeSWITCH text=%s", msg.data, level=logging.DEBUG)
                if self.cfg.send_fs_connected_ack and not self.input_ack_sent:
                    self.input_ack_sent = True
                    await self.fs_ws.send_str('{"type":"connected","protocol":"audio"}')
                continue
            if msg.type != web.WSMsgType.BINARY:
                continue
            data = bytes(msg.data)
            if not data:
                continue
            self.last_real_fs_audio_at = time.monotonic()
            await self._send_pcm_to_upstream(data)

    async def _silence_pump_loop(self) -> None:
        await self.handshake_event.wait()
        tick = self.cfg.frame_ms / 1000.0
        silence = np.zeros((self.opus_frame_samples,), dtype=np.float32)
        while not self.closed:
            now = time.monotonic()
            if now - self.last_real_fs_audio_at >= (tick + 0.005):
                assert self.upstream_ws is not None
                await self.upstream_ws.send_bytes(self._encode_and_wrap(silence))
            await asyncio.sleep(tick)

    async def _decode_upstream_audio(self, payload: bytes) -> bytes:
        pcm_out = bytearray()
        for packet in self.ogg_demux.feed(payload):
            pcm16_bytes = self.decoder.decode(packet, self.cfg.max_decode_samples)
            pcm_f32 = pcm16_to_f32(pcm16_bytes)
            resampled = resample_linear(pcm_f32, self.cfg.personaplex_rate, self.cfg.fs_sample_rate)
            pcm_out.extend(f32_to_pcm16(resampled))
        return bytes(pcm_out)

    async def _upstream_to_fs_loop(self) -> None:
        assert self.upstream_ws is not None
        async for msg in self.upstream_ws:
            if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                return
            if msg.type == aiohttp.WSMsgType.ERROR:
                raise RuntimeError(f"Upstream websocket error: {self.upstream_ws.exception()}")
            if msg.type != aiohttp.WSMsgType.BINARY:
                continue
            data = bytes(msg.data)
            if not data:
                continue
            kind = data[0]
            payload = data[1:]
            if kind == FRAME_HANDSHAKE:
                self.log("upstream handshake")
                self.handshake_event.set()
                continue
            if kind == FRAME_AUDIO and payload:
                pcm16 = await self._decode_upstream_audio(payload)
                if pcm16:
                    await self._send_pcm_to_fs(pcm16)
                continue
            if kind == FRAME_TEXT:
                self.output_token_bytes.extend(payload)
                try:
                    token = self.output_token_bytes.decode("utf-8")
                    self.output_token_bytes.clear()
                except UnicodeDecodeError:
                    if len(self.output_token_bytes) < 8:
                        continue
                    token = self.output_token_bytes.decode("utf-8", errors="replace")
                    self.output_token_bytes.clear()
                self.log("upstream text=%s", token.replace("\n", "\\n"), level=logging.DEBUG)
                continue
            if kind == FRAME_CTRL:
                text = payload.decode("utf-8", errors="replace")
                self.log("upstream ctrl=%s", text, level=logging.DEBUG)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minimal FreeSWITCH <-> PersonaPlex relay")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8012)
    parser.add_argument("--path", default="/calls")
    parser.add_argument("--health-path", default="/health")
    parser.add_argument("--personaplex-ws", default="ws://127.0.0.1:8998/api/chat")
    parser.add_argument("--voice-prompt", default="NATF0.pt")
    parser.add_argument("--text-prompt", default="You are a helpful assistant.")
    parser.add_argument("--text-prompt-file", default="")
    parser.add_argument("--seed", type=int, default=-1)
    parser.add_argument("--fs-sample-rate", type=int, default=16000)
    parser.add_argument("--personaplex-rate", type=int, default=24000)
    parser.add_argument("--frame-ms", type=int, default=20)
    parser.add_argument("--max-decode-samples", type=int, default=2880)
    parser.add_argument("--connect-timeout-sec", type=float, default=20.0)
    parser.add_argument("--ssl-verify", action="store_true", default=False)
    parser.add_argument("--send-fs-connected-ack", action="store_true", default=False)
    parser.add_argument("--log-level", default="INFO")
    return parser


def build_config(args: argparse.Namespace) -> Config:
    return Config(
        host=args.host,
        port=args.port,
        path=args.path,
        health_path=args.health_path,
        personaplex_ws=args.personaplex_ws,
        voice_prompt=args.voice_prompt,
        text_prompt=args.text_prompt,
        text_prompt_file=args.text_prompt_file,
        seed=args.seed,
        fs_sample_rate=args.fs_sample_rate,
        personaplex_rate=args.personaplex_rate,
        frame_ms=args.frame_ms,
        max_decode_samples=args.max_decode_samples,
        ssl_verify=args.ssl_verify,
        connect_timeout_sec=args.connect_timeout_sec,
        send_fs_connected_ack=args.send_fs_connected_ack,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    cfg = build_config(args)
    LOG.info(
        "starting minimal relay host=%s port=%s path=%s upstream=%s fs_rate=%s",
        cfg.host,
        cfg.port,
        cfg.path,
        cfg.personaplex_ws,
        cfg.fs_sample_rate,
    )
    service = MinimalRelayService(cfg)
    web.run_app(service.app, host=cfg.host, port=cfg.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
