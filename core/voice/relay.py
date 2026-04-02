from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import ssl
import struct
import tempfile
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlencode

import aiohttp
import numpy as np
from aiohttp import web

try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    edge_tts = None
    HAS_EDGE_TTS = False

try:
    import opuslib
    HAS_OPUSLIB = True
except ImportError:
    opuslib = None
    HAS_OPUSLIB = False

try:
    from core.voice.asr_engine import get_asr_engine
    HAS_LOCAL_ASR = True
except Exception:
    get_asr_engine = None
    HAS_LOCAL_ASR = False


LOG = logging.getLogger("relay")

FRAME_HANDSHAKE = 0x00
FRAME_AUDIO = 0x01
FRAME_TEXT = 0x02
FRAME_CTRL = 0x03

DEFAULT_STOP_PHRASES = [
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
DEFAULT_BACKCHANNELS = ["hmm", "okay", "right", "I got it"]
DEFAULT_INCOMPLETE_ENDINGS = {"the", "about", "current", "kind", "your", "for", "to"}
DEFAULT_GREETING_WORDS = {"hi", "hello", "hey", "hola", "namaste", "good", "morning", "evening"}


@dataclass
class PromptPackage:
    system_prompt: str
    initial_greeting: str = ""
    voice_prompt: str = "NATF0.pt"
    source: str = "static"
    agent_id: str = ""
    preset_name: str = ""


@dataclass
class SpeechRequest:
    text: str
    revision: int
    kind: str
    phrase_key: Optional[str] = None


@dataclass
class DirectRelayConfig:
    host: str
    port: int
    path: str
    health_path: str
    personaplex_ws: str
    personaplex_ssl_verify: bool
    fs_sample_rate: int
    personaplex_rate: int
    frame_ms: int
    max_decode_samples: int
    seed: int
    connect_timeout_sec: float
    health_probe_timeout_sec: float
    voice_prompt: str
    text_prompt: str
    text_prompt_file: str
    initial_greeting: str
    preset_file: str
    preset_name: str
    proactive_greeting: bool
    upstream_initial_greeting: bool
    omnicortex_api_base: str
    omnicortex_bearer: str
    omnicortex_user_id: str
    omnicortex_agent_id: str
    omnicortex_fetch_enabled: bool
    prompt_request_timeout_sec: float
    tts_enabled: bool
    tts_voice: str
    tts_dir: str
    tts_fallback_delay_sec: float
    tts_flush_after_sec: float
    backchannel_enabled: bool
    backchannel_phrases: List[str]
    backchannel_min_speech_sec: float
    backchannel_cooldown_sec: float
    stop_phrases: List[str]
    vad_energy_threshold: float
    vad_brief_pause_ms: int
    vad_utterance_end_ms: int
    vad_brief_factor: float
    vad_end_factor: float
    partial_grace_ms: int
    partial_incomplete_endings: set[str]
    local_asr_enabled: bool
    asr_min_audio_sec: float
    asr_recheck_sec: float
    greeting_words: set[str]
    response_idle_sec: float
    max_utterance_sec: float
    log_text_frames: bool
    send_fs_connected_ack: bool
    native_audio_only: bool


class UpstreamUnavailable(RuntimeError):
    pass


class PromptResolutionError(RuntimeError):
    pass


def _to_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _split_csv(value: Optional[str], default: Sequence[str]) -> List[str]:
    if not value:
        return [item for item in default]
    parts = [part.strip() for part in str(value).split(",")]
    return [part for part in parts if part]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_phrase_text(value: str) -> str:
    return re.sub(r"[^a-z0-9\s]+", " ", str(value or "").lower()).strip()


def match_stop_phrase(text: str, stop_phrases: Sequence[str]) -> str:
    normalized = f" {_normalize_phrase_text(text)} "
    for phrase in sorted(stop_phrases, key=lambda item: len(_normalize_phrase_text(item)), reverse=True):
        needle = _normalize_phrase_text(phrase)
        if needle and f" {needle} " in normalized:
            return phrase
    return ""


def looks_incomplete_partial(text: str, incomplete_endings: set[str]) -> bool:
    cleaned = _normalize_text(text)
    if not cleaned:
        return True
    if cleaned.endswith((".", "!", "?")):
        return False
    words = re.findall(r"[a-z0-9']+", cleaned.lower())
    if not words:
        return True
    return words[-1] in incomplete_endings


def is_greeting_only(text: str, greeting_words: set[str]) -> bool:
    words = re.findall(r"[a-z0-9']+", _normalize_text(text).lower())
    if not words:
        return False
    return all(word in greeting_words for word in words)


def detect_vad_state(
    buffer: np.ndarray,
    *,
    rate: int,
    base_threshold: float,
    brief_pause_ms: int,
    utterance_end_ms: int,
    brief_factor: float,
    end_factor: float,
) -> str:
    if buffer.size == 0:
        return "speaking"
    brief_samples = max(1, int(rate * brief_pause_ms / 1000))
    utterance_samples = max(1, int(rate * utterance_end_ms / 1000))
    if buffer.size >= utterance_samples:
        tail = buffer[-utterance_samples:]
        if float(np.mean(tail ** 2)) < (base_threshold * end_factor):
            return "utterance_end"
    if buffer.size >= brief_samples:
        tail = buffer[-brief_samples:]
        if float(np.mean(tail ** 2)) < (base_threshold * brief_factor):
            return "brief_pause"
    return "speaking"


def resample_linear(samples: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr or samples.size == 0:
        return samples.astype(np.float32, copy=False)
    dst_len = int(round(samples.shape[0] * float(dst_sr) / float(src_sr)))
    if dst_len <= 1:
        return np.zeros((0,), dtype=np.float32)
    src_x = np.linspace(0.0, 1.0, num=samples.shape[0], endpoint=True)
    dst_x = np.linspace(0.0, 1.0, num=dst_len, endpoint=True)
    return np.interp(dst_x, src_x, samples).astype(np.float32)


def pcm16_to_f32(payload: bytes) -> np.ndarray:
    if not payload:
        return np.zeros((0,), dtype=np.float32)
    return np.frombuffer(payload, dtype="<i2").astype(np.float32) / 32768.0


def f32_to_pcm16(samples: np.ndarray) -> bytes:
    return (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def extract_complete_sentences(buffer: str) -> Tuple[List[str], str]:
    sentences: List[str] = []
    cursor = 0
    while cursor < len(buffer):
        match_index = -1
        for idx, char in enumerate(buffer[cursor:], start=cursor):
            if char not in ".!?\n":
                continue
            if char == "." and 0 < idx < len(buffer) - 1:
                if buffer[idx - 1].isdigit() and buffer[idx + 1].isdigit():
                    continue
            match_index = idx
            break
        if match_index < 0:
            break
        sentence = buffer[cursor : match_index + 1].replace("\u2581", " ").strip()
        if sentence:
            sentences.append(sentence)
        cursor = match_index + 1
    return sentences, buffer[cursor:]


def build_prompt_with_greeting_note(
    prompt: str,
    greeting: str,
    proactive_greeting: bool,
    upstream_initial_greeting: bool,
) -> str:
    base = _normalize_text(prompt) or "You are a helpful assistant."
    if proactive_greeting and greeting:
        note = (
            f'\n\nOpening line already spoken to the caller: "{greeting}". '
            "Do not repeat that greeting. Continue the conversation naturally."
        )
        return (base + note).strip()
    if upstream_initial_greeting and greeting:
        note = (
            f'\n\nStart the call with this exact opening line: "{greeting}". '
            "After speaking that opening line once, continue the conversation naturally."
        )
        return (base + note).strip()
    return base


def _voice_prompt_from_detail(detail: Dict[str, Any]) -> str:
    logic = detail.get("logic") or {}
    voice_cfg = logic.get("voice") if isinstance(logic, dict) else {}
    for candidate in (
        voice_cfg.get("voice_prompt") if isinstance(voice_cfg, dict) else None,
        logic.get("voice_prompt") if isinstance(logic, dict) else None,
        detail.get("voice_prompt"),
    ):
        value = _normalize_text(str(candidate or ""))
        if value:
            return value
    return ""

_OGG_CRC_TABLE: List[int] = []
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

    def feed(self, data: bytes) -> List[bytes]:
        self._buf.extend(data)
        packets: List[bytes] = []
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
            vendor = b"direct-relay"
            tags = struct.pack("<8sI", b"OpusTags", len(vendor)) + vendor + struct.pack("<I", 0)
            out.extend(self._page(tags, 0))
            self._started = True
        self._granule += samples_per_frame_48k
        out.extend(self._page(opus_packet, self._granule))
        return bytes(out)


class PromptResolver:
    def __init__(self, cfg: DirectRelayConfig, http: aiohttp.ClientSession) -> None:
        self.cfg = cfg
        self.http = http
        self._preset_cache: Optional[Dict[str, Dict[str, Any]]] = None

    def _load_presets(self) -> Dict[str, Dict[str, Any]]:
        if self._preset_cache is not None:
            return self._preset_cache
        if not self.cfg.preset_file:
            self._preset_cache = {}
            return self._preset_cache
        data = json.loads(Path(self.cfg.preset_file).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise PromptResolutionError("Preset file must contain a JSON object.")
        self._preset_cache = {str(key): value for key, value in data.items() if isinstance(value, dict)}
        return self._preset_cache

    def _resolve_static(self, request: web.Request) -> Optional[PromptPackage]:
        requested_preset = _normalize_text(request.query.get("preset"))
        preset_name = requested_preset or _normalize_text(self.cfg.preset_name)
        system_prompt = _normalize_text(self.cfg.text_prompt)
        initial_greeting = _normalize_text(self.cfg.initial_greeting)
        voice_prompt = _normalize_text(request.query.get("voice_prompt") or self.cfg.voice_prompt) or "NATF0.pt"
        source = "static"
        if self.cfg.text_prompt_file:
            system_prompt = _normalize_text(Path(self.cfg.text_prompt_file).read_text(encoding="utf-8"))
            source = f"file:{self.cfg.text_prompt_file}"
        presets = self._load_presets()
        if preset_name and presets:
            preset = presets.get(preset_name)
            if preset is None:
                raise PromptResolutionError(f"Preset '{preset_name}' not found in {self.cfg.preset_file}")
            system_prompt = _normalize_text(str(preset.get("system_prompt") or preset.get("text_prompt") or system_prompt))
            initial_greeting = _normalize_text(str(preset.get("initial_greeting") or preset.get("greeting") or initial_greeting))
            voice_prompt = _normalize_text(str(preset.get("voice_prompt") or voice_prompt)) or "NATF0.pt"
            source = f"preset:{preset_name}"
        elif requested_preset:
            raise PromptResolutionError(f"Preset '{requested_preset}' not found in {self.cfg.preset_file}")
        if not system_prompt and not initial_greeting:
            return None
        return PromptPackage(
            system_prompt=system_prompt or "You are a helpful assistant.",
            initial_greeting=initial_greeting,
            voice_prompt=voice_prompt,
            source=source,
            preset_name=preset_name,
        )

    async def _fetch_agent_prompt(self, agent_id: str, bearer: str, user_id: str, static_prompt: Optional[PromptPackage]) -> PromptPackage:
        base = self.cfg.omnicortex_api_base.rstrip("/")
        if not base:
            raise PromptResolutionError("OMNICORTEX_API_BASE is not configured")
        headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
        if user_id:
            headers["X-User-Id"] = user_id
        timeout = aiohttp.ClientTimeout(total=self.cfg.prompt_request_timeout_sec)
        system_url = f"{base}/agents/{agent_id}/system-prompt"
        detail_url = f"{base}/agents/{agent_id}"
        async with self.http.get(system_url, headers=headers, timeout=timeout) as response:
            if response.status >= 400:
                raise PromptResolutionError(f"System prompt fetch failed: HTTP {response.status} {await response.text()}")
            prompt_payload = await response.json()
        detail_payload: Dict[str, Any] = {}
        async with self.http.get(detail_url, headers=headers, timeout=timeout) as response:
            if response.status < 400:
                detail_payload = await response.json()
        static = static_prompt or PromptPackage(system_prompt="You are a helpful assistant.")
        return PromptPackage(
            system_prompt=_normalize_text(str(prompt_payload.get("system_prompt") or static.system_prompt)),
            initial_greeting=_normalize_text(str(prompt_payload.get("initial_greeting") or static.initial_greeting)),
            voice_prompt=_normalize_text(_voice_prompt_from_detail(detail_payload) or static.voice_prompt) or "NATF0.pt",
            source="omnicortex_api",
            agent_id=agent_id,
            preset_name=static.preset_name,
        )

    async def resolve(self, request: web.Request) -> PromptPackage:
        static_prompt = self._resolve_static(request)
        agent_id = _normalize_text(request.query.get("agent_id") or self.cfg.omnicortex_agent_id)
        if agent_id and self.cfg.omnicortex_fetch_enabled:
            bearer = _normalize_text(
                request.headers.get("Authorization", "").replace("Bearer ", "")
                or request.query.get("omni_bearer")
                or self.cfg.omnicortex_bearer
            )
            user_id = _normalize_text(request.headers.get("X-User-Id") or request.query.get("x_user_id") or self.cfg.omnicortex_user_id)
            try:
                return await self._fetch_agent_prompt(agent_id, bearer, user_id, static_prompt)
            except Exception as exc:
                if static_prompt:
                    LOG.warning("Prompt fetch failed for agent_id=%s; falling back to static prompt: %s", agent_id, exc)
                    return static_prompt
                raise
        if static_prompt is None:
            raise PromptResolutionError("No prompt source configured. Provide static prompt config or enable OmniCortex fetch.")
        return static_prompt


class BackchannelCache:
    def __init__(self, cfg: DirectRelayConfig) -> None:
        self.cfg = cfg
        self._cache: Dict[str, bytes] = {}
        self._lock = asyncio.Lock()
        self._dir = Path(cfg.tts_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    async def get_pcm(self, phrase: str, cancel_event: asyncio.Event) -> bytes:
        async with self._lock:
            if phrase in self._cache:
                return self._cache[phrase]
            pcm = await synthesize_text_to_pcm(
                phrase,
                voice=self.cfg.tts_voice,
                sample_rate=self.cfg.fs_sample_rate,
                work_dir=self._dir,
                cancel_event=cancel_event,
            )
            self._cache[phrase] = pcm
            return pcm


async def _wait_process_or_cancel(process: asyncio.subprocess.Process, cancel_event: asyncio.Event) -> Tuple[int, bytes]:
    stderr_task = asyncio.create_task(process.stderr.read() if process.stderr else asyncio.sleep(0, result=b""))
    wait_task = asyncio.create_task(process.wait())
    cancel_task = asyncio.create_task(cancel_event.wait())
    done, _ = await asyncio.wait({wait_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED)
    if cancel_task in done:
        with suppress(ProcessLookupError):
            process.kill()
        await process.wait()
        stderr = await stderr_task
        wait_task.cancel()
        raise asyncio.CancelledError(f"process cancelled rc={process.returncode} stderr={stderr.decode(errors='ignore')}")
    cancel_task.cancel()
    rc = await wait_task
    stderr = await stderr_task
    return rc, stderr


async def synthesize_text_to_pcm(
    text: str,
    *,
    voice: str,
    sample_rate: int,
    work_dir: Path,
    cancel_event: asyncio.Event,
) -> bytes:
    if not HAS_EDGE_TTS:
        raise RuntimeError("edge-tts is not installed")
    work_dir.mkdir(parents=True, exist_ok=True)
    stem = f"relay_{uuid.uuid4().hex}"
    mp3_path = work_dir / f"{stem}.mp3"
    pcm_path = work_dir / f"{stem}.pcm"
    save_task = asyncio.create_task(edge_tts.Communicate(text, voice).save(str(mp3_path)))
    cancel_task = asyncio.create_task(cancel_event.wait())
    done, _ = await asyncio.wait({save_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED)
    if cancel_task in done:
        save_task.cancel()
        with suppress(asyncio.CancelledError):
            await save_task
        raise asyncio.CancelledError("edge-tts save cancelled")
    cancel_task.cancel()
    await save_task
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(mp3_path),
        "-ar",
        str(sample_rate),
        "-ac",
        "1",
        "-f",
        "s16le",
        str(pcm_path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        rc, stderr = await _wait_process_or_cancel(process, cancel_event)
        if rc != 0:
            raise RuntimeError(f"ffmpeg failed rc={rc}: {stderr.decode(errors='ignore').strip()}")
        return pcm_path.read_bytes()
    finally:
        for path in (mp3_path, pcm_path):
            with suppress(FileNotFoundError, OSError):
                path.unlink()


class DirectRelayService:
    def __init__(self, cfg: DirectRelayConfig) -> None:
        self.cfg = cfg
        self.app = web.Application()
        self.app["relay"] = self
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
        self.prompt_resolver: Optional[PromptResolver] = None
        self.backchannel_cache = BackchannelCache(cfg)
        self.active_calls: Dict[str, "DirectRelayCall"] = {}
        self.last_upstream_ok_at: Optional[float] = None
        self.last_upstream_error: str = ""

    async def _lifecycle(self, app: web.Application):
        timeout = aiohttp.ClientTimeout(total=max(5.0, self.cfg.connect_timeout_sec))
        self.http = aiohttp.ClientSession(timeout=timeout)
        self.prompt_resolver = PromptResolver(self.cfg, self.http)
        yield
        if self.http is not None:
            await self.http.close()
            self.http = None

    async def handle_health(self, request: web.Request) -> web.Response:
        data = {
            "status": "ok",
            "personaplex_ws": self.cfg.personaplex_ws,
            "active_calls": len(self.active_calls),
            "last_upstream_ok_at": self.last_upstream_ok_at,
            "last_upstream_error": self.last_upstream_error or None,
            "tts_enabled": self.cfg.tts_enabled and HAS_EDGE_TTS,
            "asr_enabled": self.cfg.local_asr_enabled and HAS_LOCAL_ASR,
            "opus_enabled": HAS_OPUSLIB,
            "prompt_mode": "api+static" if self.cfg.omnicortex_fetch_enabled else "static",
            "native_audio_only": self.cfg.native_audio_only,
        }
        return web.json_response(data)

    async def handle_calls(self, request: web.Request) -> web.StreamResponse:
        LOG.info(
            "incoming relay request remote=%s path=%s upgrade=%s user-agent=%s",
            request.remote or "unknown",
            request.path_qs,
            request.headers.get("Upgrade"),
            request.headers.get("User-Agent"),
        )
        ws = web.WebSocketResponse(max_msg_size=16 * 1024 * 1024)
        await ws.prepare(request)
        call = DirectRelayCall(self, request, ws)
        self.active_calls[call.call_id] = call
        try:
            await call.run()
        finally:
            self.active_calls.pop(call.call_id, None)
        return ws


class DirectRelayCall:
    def __init__(self, service: DirectRelayService, request: web.Request, fs_ws: web.WebSocketResponse) -> None:
        self.service = service
        self.cfg = service.cfg
        self.request = request
        self.fs_ws = fs_ws
        self.call_id = _normalize_text(request.query.get("call_uuid")) or str(uuid.uuid4())
        self.remote = request.remote or "unknown"
        self.prompt: Optional[PromptPackage] = None
        self.upstream_ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.encoder = None
        self.decoder = None
        self.ogg_mux = OggMuxer(self.cfg.personaplex_rate)
        self.ogg_demux = OggDemuxer()
        self.opus_frame_samples = self.cfg.personaplex_rate * self.cfg.frame_ms // 1000
        self.opus_48k_frame = 48000 * self.cfg.frame_ms // 1000
        self.pcm_up_buffer = np.zeros((0,), dtype=np.float32)
        self.handshake_event = asyncio.Event()
        self.closed = False
        self.last_real_fs_audio_at = 0.0
        self.analysis_queue: asyncio.Queue[Optional[np.ndarray]] = asyncio.Queue(maxsize=256)
        self.local_speech_queue: asyncio.Queue[Optional[SpeechRequest]] = asyncio.Queue()
        self.fs_send_lock = asyncio.Lock()
        self.current_local_cancel = asyncio.Event()
        self.local_speech_generation = 0
        self.local_speech_active = False
        self.current_response_revision: Optional[int] = None
        self.current_response_has_native_audio = False
        self.current_response_suppressed = False
        self.last_output_activity_at = 0.0
        self.current_text_revision: Optional[int] = None
        self.text_buffer = ""
        self.last_text_at = 0.0
        self.first_text_at = 0.0
        self.turn_revision = 0
        self.suppressed_response_revisions: set[int] = set()
        self.native_audio_active_until = 0.0
        self.assistant_spoke_first = False
        self.last_backchannel_at = 0.0
        self.latest_partial: Optional[Dict[str, Any]] = None
        self.audio_seq = 0
        self.input_ack_sent = False
        self.utterance_buffer = np.zeros((0,), dtype=np.float32)
        self.utterance_speech_started_at: Optional[float] = None
        self.last_vad_state = "speaking"
        self.last_partial_asr_at = 0.0
        self.partial_task: Optional[asyncio.Task] = None
        self.finalize_task: Optional[asyncio.Task] = None
        self.output_token_bytes = bytearray()

    @property
    def assistant_audio_active(self) -> bool:
        return self.local_speech_active or time.monotonic() < self.native_audio_active_until

    def log(self, message: str, *args: Any, level: int = logging.INFO) -> None:
        LOG.log(level, "[%s] " + message, self.call_id, *args)

    async def run(self) -> None:
        if not HAS_OPUSLIB:
            raise RuntimeError("opuslib is not installed. Install it before running the direct relay.")
        self.encoder = opuslib.Encoder(self.cfg.personaplex_rate, 1, opuslib.APPLICATION_VOIP)
        self.decoder = opuslib.Decoder(self.cfg.personaplex_rate, 1)
        self.log("accepted connection remote=%s path=%s", self.remote, self.request.path)
        try:
            assert self.service.prompt_resolver is not None
            self.prompt = await self.service.prompt_resolver.resolve(self.request)
            self.log("prompt source=%s voice_prompt=%s", self.prompt.source, self.prompt.voice_prompt)
            await self._connect_upstream()
            critical_tasks = [
                asyncio.create_task(self._fs_to_upstream_loop(), name="fs_to_upstream"),
                asyncio.create_task(self._upstream_to_fs_loop(), name="upstream_to_fs"),
            ]
            background_tasks = [
                asyncio.create_task(self._silence_pump_loop(), name="silence_pump"),
                asyncio.create_task(self._analysis_loop(), name="analysis_loop"),
                asyncio.create_task(self._local_speech_worker(), name="local_speech_worker"),
                asyncio.create_task(self._text_flush_loop(), name="text_flush"),
                asyncio.create_task(self._response_housekeeping_loop(), name="response_housekeeping"),
            ]
            for task in background_tasks:
                task.add_done_callback(self._log_background_task_done)
            done, pending = await asyncio.wait(critical_tasks, return_when=asyncio.FIRST_COMPLETED)
            self.log(
                "task completion first_done=%s pending=%s",
                [task.get_name() for task in done],
                [task.get_name() for task in pending] + [task.get_name() for task in background_tasks if not task.done()],
                level=logging.INFO,
            )
            for task in list(pending) + background_tasks:
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
            self.log("relay failed: %s", exc, level=logging.ERROR)
            with suppress(Exception):
                await self.fs_ws.close(code=1011, message=b"relay failed")
        finally:
            self.closed = True
            for queue in (self.analysis_queue, self.local_speech_queue):
                with suppress(asyncio.QueueFull):
                    queue.put_nowait(None)
            await self._cancel_local_speech("session_end")
            if self.partial_task:
                self.partial_task.cancel()
            if self.finalize_task:
                self.finalize_task.cancel()
            if self.upstream_ws is not None and not self.upstream_ws.closed:
                with suppress(Exception):
                    await self.upstream_ws.close()
            self.log("session closed")

    def _log_background_task_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        try:
            exc = task.exception()
        except Exception as err:
            self.log("background task exception inspection failed name=%s err=%s", task.get_name(), err, level=logging.ERROR)
            return
        if exc:
            self.log("background task failed name=%s err=%s", task.get_name(), exc, level=logging.ERROR)
        else:
            self.log("background task exited cleanly name=%s", task.get_name(), level=logging.WARNING)

    async def _connect_upstream(self) -> None:
        assert self.prompt is not None
        assert self.service.http is not None
        prompt_text = build_prompt_with_greeting_note(
            self.prompt.system_prompt,
            self.prompt.initial_greeting,
            self.cfg.proactive_greeting,
            self.cfg.upstream_initial_greeting,
        )
        params = {
            "voice_prompt": self.prompt.voice_prompt or self.cfg.voice_prompt,
            "text_prompt": prompt_text,
            "seed": str(self.cfg.seed),
        }
        url = self.cfg.personaplex_ws
        separator = "&" if "?" in url else "?"
        upstream_url = f"{url}{separator}{urlencode(params)}"
        ssl_ctx = None
        if upstream_url.startswith("wss://") and not self.cfg.personaplex_ssl_verify:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
        timeout = aiohttp.ClientTimeout(total=self.cfg.connect_timeout_sec)
        try:
            self.upstream_ws = await self.service.http.ws_connect(upstream_url, ssl=ssl_ctx, timeout=timeout)
        except Exception as exc:
            raise UpstreamUnavailable(f"Unable to connect upstream: {exc}") from exc
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

    async def _stream_local_pcm(self, pcm16_bytes: bytes, *, revision: int, source: str, cancel_event: asyncio.Event) -> None:
        chunk_bytes = self.cfg.fs_sample_rate * 2 * self.cfg.frame_ms // 1000
        next_tick = time.monotonic()
        for offset in range(0, len(pcm16_bytes), chunk_bytes):
            if cancel_event.is_set():
                return
            if revision < self.turn_revision:
                return
            if revision in self.suppressed_response_revisions and source != "backchannel":
                return
            if source != "native" and time.monotonic() < self.native_audio_active_until:
                return
            chunk = pcm16_bytes[offset : offset + chunk_bytes]
            if not chunk:
                continue
            await self._send_pcm_to_fs(chunk)
            next_tick += self.cfg.frame_ms / 1000.0
            delay = next_tick - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)

    async def _cancel_local_speech(self, reason: str) -> None:
        self.local_speech_generation += 1
        self.current_local_cancel.set()
        drained = 0
        while True:
            try:
                item = self.local_speech_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            else:
                drained += 1 if item is not None else 0
                with suppress(ValueError):
                    self.local_speech_queue.task_done()
        self.current_local_cancel = asyncio.Event()
        if drained or self.local_speech_active:
            self.log("cancel local speech reason=%s drained=%d", reason, drained)

    async def _interrupt_current_response(self, reason: str, transcript: str = "") -> None:
        if self.current_response_revision is not None:
            self.suppressed_response_revisions.add(self.current_response_revision)
        await self._cancel_local_speech(reason)
        self.current_response_suppressed = True
        self.text_buffer = ""
        self.native_audio_active_until = 0.0
        self.log("interrupt response reason=%s transcript=%s", reason, transcript)

    def _ensure_response_revision(self) -> int:
        now = time.monotonic()
        if self.current_response_revision is None or (self.last_output_activity_at and now - self.last_output_activity_at > self.cfg.response_idle_sec):
            self.current_response_revision = self.turn_revision
            self.current_response_has_native_audio = False
            self.current_response_suppressed = self.current_response_revision in self.suppressed_response_revisions
            self.current_text_revision = self.current_response_revision
            self.text_buffer = ""
            self.first_text_at = 0.0
        return self.current_response_revision

    async def _queue_local_speech(self, text: str, *, revision: int, kind: str, phrase_key: Optional[str] = None) -> None:
        cleaned = _normalize_text(text)
        if not cleaned:
            return
        if kind != "backchannel" and revision in self.suppressed_response_revisions:
            return
        await self.local_speech_queue.put(SpeechRequest(text=cleaned, revision=revision, kind=kind, phrase_key=phrase_key))

    async def _maybe_start_greeting(self) -> None:
        assert self.prompt is not None
        if not self.cfg.proactive_greeting or not self.prompt.initial_greeting:
            return
        if not self.cfg.tts_enabled or not HAS_EDGE_TTS:
            self.log("greeting skipped: TTS unavailable", level=logging.WARNING)
            return
        await self._queue_local_speech(self.prompt.initial_greeting, revision=0, kind="greeting")
        self.assistant_spoke_first = True

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
                    await self.fs_ws.send_str(json.dumps({"type": "connected", "protocol": "audio"}))
                continue
            if msg.type != web.WSMsgType.BINARY:
                continue
            data = bytes(msg.data)
            if not data:
                continue
            self.audio_seq += 1
            self.last_real_fs_audio_at = time.monotonic()
            await self._send_pcm_to_upstream(data)
            if self.cfg.local_asr_enabled and HAS_LOCAL_ASR:
                pcm = pcm16_to_f32(data)
                try:
                    self.analysis_queue.put_nowait(pcm.copy())
                except asyncio.QueueFull:
                    with suppress(asyncio.QueueEmpty):
                        self.analysis_queue.get_nowait()
                        self.analysis_queue.task_done()
                    with suppress(asyncio.QueueFull):
                        self.analysis_queue.put_nowait(pcm.copy())

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
                await self._maybe_start_greeting()
                continue
            revision = self._ensure_response_revision()
            self.last_output_activity_at = time.monotonic()
            if kind == FRAME_AUDIO and payload:
                self.current_response_has_native_audio = True
                self.current_response_suppressed = revision in self.suppressed_response_revisions
                if self.current_response_suppressed:
                    continue
                self.native_audio_active_until = time.monotonic() + 0.35
                await self._cancel_local_speech("native_audio")
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
                if self.cfg.log_text_frames:
                    self.log("text frame=%s", token.replace("\n", "\\n"), level=logging.DEBUG)
                if revision in self.suppressed_response_revisions:
                    continue
                self.current_text_revision = revision
                if not self.first_text_at:
                    self.first_text_at = time.monotonic()
                self.text_buffer += token
                self.last_text_at = time.monotonic()
                if self.current_response_has_native_audio or not self.cfg.tts_enabled or not HAS_EDGE_TTS:
                    continue
                if time.monotonic() - self.first_text_at < self.cfg.tts_fallback_delay_sec:
                    continue
                sentences, remainder = extract_complete_sentences(self.text_buffer)
                self.text_buffer = remainder
                for sentence in sentences:
                    await self._queue_local_speech(sentence, revision=revision, kind="fallback_tts")
                continue
            if kind == FRAME_CTRL:
                text = payload.decode("utf-8", errors="replace")
                self.log("control frame=%s", text, level=logging.DEBUG)
                continue

    async def _text_flush_loop(self) -> None:
        while not self.closed:
            await asyncio.sleep(0.2)
            if not self.text_buffer or self.current_text_revision is None:
                continue
            if self.current_response_has_native_audio or not self.cfg.tts_enabled or not HAS_EDGE_TTS:
                continue
            if self.first_text_at and time.monotonic() - self.first_text_at < self.cfg.tts_fallback_delay_sec:
                continue
            if time.monotonic() - self.last_text_at < self.cfg.tts_flush_after_sec:
                continue
            sentence = _normalize_text(self.text_buffer.replace("\u2581", " "))
            self.text_buffer = ""
            if sentence:
                await self._queue_local_speech(sentence, revision=self.current_text_revision, kind="fallback_tts")

    async def _response_housekeeping_loop(self) -> None:
        while not self.closed:
            await asyncio.sleep(0.5)
            if self.current_response_revision is None:
                continue
            idle_for = time.monotonic() - self.last_output_activity_at if self.last_output_activity_at else 0.0
            if idle_for < self.cfg.response_idle_sec:
                continue
            if self.assistant_audio_active:
                continue
            self.log("response idle revision=%s", self.current_response_revision, level=logging.DEBUG)
            self.current_response_revision = None
            self.current_response_has_native_audio = False
            self.current_response_suppressed = False
            self.current_text_revision = None
            self.text_buffer = ""
            self.first_text_at = 0.0

    async def _local_speech_worker(self) -> None:
        while not self.closed:
            request = await self.local_speech_queue.get()
            if request is None:
                return
            try:
                if request.revision < self.turn_revision and request.kind != "greeting":
                    continue
                if request.revision in self.suppressed_response_revisions and request.kind not in {"greeting", "backchannel"}:
                    continue
                if request.kind != "fallback_tts" and self.assistant_audio_active and request.kind != "backchannel":
                    continue
                generation = self.local_speech_generation
                cancel_event = self.current_local_cancel
                self.local_speech_active = True
                if request.kind == "backchannel":
                    pcm = await self.service.backchannel_cache.get_pcm(request.phrase_key or request.text, cancel_event)
                else:
                    pcm = await synthesize_text_to_pcm(
                        request.text,
                        voice=self.cfg.tts_voice,
                        sample_rate=self.cfg.fs_sample_rate,
                        work_dir=Path(self.cfg.tts_dir),
                        cancel_event=cancel_event,
                    )
                if generation != self.local_speech_generation or cancel_event.is_set():
                    continue
                await self._stream_local_pcm(pcm, revision=request.revision, source=request.kind, cancel_event=cancel_event)
                if request.kind == "greeting":
                    self.assistant_spoke_first = True
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.log("local speech failed kind=%s err=%s", request.kind, exc, level=logging.WARNING)
            finally:
                self.local_speech_active = False
                self.local_speech_queue.task_done()

    async def _analysis_loop(self) -> None:
        if not self.cfg.local_asr_enabled or not HAS_LOCAL_ASR:
            reason = "disabled by config" if not self.cfg.local_asr_enabled else "unavailable"
            self.log("local ASR %s; VAD/barge/backchannels disabled", reason, level=logging.WARNING)
            while not self.closed:
                chunk = await self.analysis_queue.get()
                if chunk is None:
                    return
                self.analysis_queue.task_done()
            return
        asr = await get_asr_engine()
        while not self.closed:
            chunk = await self.analysis_queue.get()
            try:
                if chunk is None:
                    return
                if chunk.size == 0:
                    continue
                self.utterance_buffer = np.concatenate([self.utterance_buffer, chunk])
                max_samples = int(self.cfg.fs_sample_rate * self.cfg.max_utterance_sec)
                if self.utterance_buffer.size > max_samples:
                    self.utterance_buffer = self.utterance_buffer[-max_samples:]
                state = detect_vad_state(
                    self.utterance_buffer,
                    rate=self.cfg.fs_sample_rate,
                    base_threshold=self.cfg.vad_energy_threshold,
                    brief_pause_ms=self.cfg.vad_brief_pause_ms,
                    utterance_end_ms=self.cfg.vad_utterance_end_ms,
                    brief_factor=self.cfg.vad_brief_factor,
                    end_factor=self.cfg.vad_end_factor,
                )
                now = time.monotonic()
                if state == "speaking" and self.utterance_speech_started_at is None:
                    self.utterance_speech_started_at = now
                if (
                    state in {"brief_pause", "utterance_end"}
                    and self.utterance_buffer.size >= int(self.cfg.fs_sample_rate * self.cfg.asr_min_audio_sec)
                    and (self.partial_task is None or self.partial_task.done())
                    and now - self.last_partial_asr_at >= self.cfg.asr_recheck_sec
                ):
                    self.last_partial_asr_at = now
                    self.partial_task = asyncio.create_task(
                        self._run_partial_asr(
                            asr,
                            self.utterance_buffer.copy(),
                            self.audio_seq,
                        )
                    )
                if (
                    state == "brief_pause"
                    and self.last_vad_state != "brief_pause"
                    and self.cfg.backchannel_enabled
                    and HAS_EDGE_TTS
                    and not self.assistant_audio_active
                    and self.utterance_speech_started_at is not None
                    and now - self.utterance_speech_started_at >= self.cfg.backchannel_min_speech_sec
                    and now - self.last_backchannel_at >= self.cfg.backchannel_cooldown_sec
                ):
                    phrase = self.cfg.backchannel_phrases[(self.turn_revision + int(now)) % len(self.cfg.backchannel_phrases)]
                    await self._queue_local_speech(phrase, revision=self.turn_revision + 1, kind="backchannel", phrase_key=phrase)
                    self.last_backchannel_at = now
                if state == "utterance_end" and self.last_vad_state != "utterance_end":
                    snapshot = self.utterance_buffer.copy()
                    snapshot_seq = self.audio_seq
                    self.utterance_buffer = np.zeros((0,), dtype=np.float32)
                    self.utterance_speech_started_at = None
                    if self.finalize_task and not self.finalize_task.done():
                        self.finalize_task.cancel()
                    self.finalize_task = asyncio.create_task(self._finalize_turn(asr, snapshot, snapshot_seq))
                self.last_vad_state = state
            finally:
                self.analysis_queue.task_done()

    async def _run_partial_asr(self, asr: Any, pcm: np.ndarray, snapshot_seq: int) -> None:
        try:
            text, confidence, language = await asr.transcribe(pcm, sample_rate=self.cfg.fs_sample_rate)
        except Exception as exc:
            self.log("partial ASR failed: %s", exc, level=logging.DEBUG)
            return
        text = _normalize_text(text)
        if not text:
            return
        self.latest_partial = {
            "text": text,
            "confidence": confidence,
            "language": language,
            "audio_seq": snapshot_seq,
            "timestamp": time.monotonic(),
        }
        phrase = match_stop_phrase(text, self.cfg.stop_phrases)
        if phrase and self.assistant_audio_active:
            await self._interrupt_current_response(f"stop_phrase:{phrase}", transcript=text)

    async def _finalize_turn(self, asr: Any, pcm: np.ndarray, snapshot_seq: int) -> None:
        await asyncio.sleep(self.cfg.partial_grace_ms / 1000.0)
        if self.audio_seq > snapshot_seq:
            return
        candidate = self.latest_partial if self.latest_partial and self.latest_partial.get("audio_seq", 0) >= snapshot_seq else None
        text = _normalize_text(str(candidate.get("text"))) if candidate else ""
        if not text or looks_incomplete_partial(text, self.cfg.partial_incomplete_endings):
            try:
                final_text, _, _ = await asr.transcribe(pcm, sample_rate=self.cfg.fs_sample_rate)
                text = _normalize_text(final_text)
            except Exception as exc:
                self.log("final ASR failed: %s", exc, level=logging.DEBUG)
                return
        if not text:
            return
        self.turn_revision += 1
        revision = self.turn_revision
        self.log("turn revision=%s text=%s source=local_asr", revision, text)
        if self.assistant_spoke_first and is_greeting_only(text, self.cfg.greeting_words):
            self.suppressed_response_revisions.add(revision)
            self.log("suppressing greeting-only reply revision=%s", revision)
        self.current_response_revision = None
        self.current_response_has_native_audio = False
        self.current_response_suppressed = False
        self.current_text_revision = None
        self.text_buffer = ""
        self.latest_partial = None
        self.first_text_at = 0.0


def build_config(args: argparse.Namespace) -> DirectRelayConfig:
    native_audio_only = args.native_audio_only
    proactive_greeting = args.proactive_greeting
    upstream_initial_greeting = args.upstream_initial_greeting
    tts_enabled = args.tts_enabled
    backchannel_enabled = args.backchannel_enabled
    local_asr_enabled = not args.disable_local_asr
    if native_audio_only:
        proactive_greeting = False
        upstream_initial_greeting = True
        tts_enabled = False
        backchannel_enabled = False
        local_asr_enabled = False
    return DirectRelayConfig(
        host=args.host,
        port=args.port,
        path=args.path,
        health_path=args.health_path,
        personaplex_ws=args.personaplex_ws,
        personaplex_ssl_verify=args.personaplex_ssl_verify,
        fs_sample_rate=args.fs_sample_rate,
        personaplex_rate=args.personaplex_rate,
        frame_ms=args.frame_ms,
        max_decode_samples=args.max_decode_samples,
        seed=args.seed,
        connect_timeout_sec=args.connect_timeout_sec,
        health_probe_timeout_sec=args.health_probe_timeout_sec,
        voice_prompt=args.voice_prompt,
        text_prompt=args.text_prompt,
        text_prompt_file=args.text_prompt_file,
        initial_greeting=args.initial_greeting,
        preset_file=args.preset_file,
        preset_name=args.preset_name,
        proactive_greeting=proactive_greeting,
        upstream_initial_greeting=upstream_initial_greeting,
        omnicortex_api_base=args.omnicortex_api_base,
        omnicortex_bearer=args.omnicortex_bearer,
        omnicortex_user_id=args.omnicortex_user_id,
        omnicortex_agent_id=args.omnicortex_agent_id,
        omnicortex_fetch_enabled=args.omnicortex_fetch_enabled,
        prompt_request_timeout_sec=args.prompt_request_timeout_sec,
        tts_enabled=tts_enabled,
        tts_voice=args.tts_voice,
        tts_dir=args.tts_dir,
        tts_fallback_delay_sec=args.tts_fallback_delay_sec,
        tts_flush_after_sec=args.tts_flush_after_sec,
        backchannel_enabled=backchannel_enabled,
        backchannel_phrases=_split_csv(args.backchannel_phrases, DEFAULT_BACKCHANNELS),
        backchannel_min_speech_sec=args.backchannel_min_speech_sec,
        backchannel_cooldown_sec=args.backchannel_cooldown_sec,
        stop_phrases=_split_csv(args.stop_phrases, DEFAULT_STOP_PHRASES),
        vad_energy_threshold=args.vad_energy_threshold,
        vad_brief_pause_ms=args.vad_brief_pause_ms,
        vad_utterance_end_ms=args.vad_utterance_end_ms,
        vad_brief_factor=args.vad_brief_factor,
        vad_end_factor=args.vad_end_factor,
        partial_grace_ms=args.partial_grace_ms,
        partial_incomplete_endings=set(_split_csv(args.partial_incomplete_endings, list(DEFAULT_INCOMPLETE_ENDINGS))),
        local_asr_enabled=local_asr_enabled,
        asr_min_audio_sec=args.asr_min_audio_sec,
        asr_recheck_sec=args.asr_recheck_sec,
        greeting_words=set(_split_csv(args.greeting_words, list(DEFAULT_GREETING_WORDS))),
        response_idle_sec=args.response_idle_sec,
        max_utterance_sec=args.max_utterance_sec,
        log_text_frames=args.log_text_frames,
        send_fs_connected_ack=args.send_fs_connected_ack,
        native_audio_only=native_audio_only,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Direct FreeSWITCH <-> PersonaPlex relay")
    parser.add_argument("--host", default=os.getenv("RELAY_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("RELAY_PORT", "8012")))
    parser.add_argument("--path", default=os.getenv("RELAY_PATH", "/calls"))
    parser.add_argument("--health-path", default=os.getenv("RELAY_HEALTH_PATH", "/health"))
    parser.add_argument("--personaplex-ws", default=os.getenv("PERSONAPLEX_WS", "ws://127.0.0.1:8998/api/chat"))
    parser.add_argument("--personaplex-ssl-verify", action="store_true", default=_to_bool(os.getenv("PERSONAPLEX_SSL_VERIFY", "0")))
    parser.add_argument("--fs-sample-rate", type=int, default=int(os.getenv("RELAY_FS_SAMPLE_RATE", "16000")))
    parser.add_argument("--personaplex-rate", type=int, default=int(os.getenv("RELAY_PERSONAPLEX_RATE", "24000")))
    parser.add_argument("--frame-ms", type=int, default=int(os.getenv("RELAY_FRAME_MS", "20")))
    parser.add_argument("--max-decode-samples", type=int, default=int(os.getenv("RELAY_MAX_DECODE_SAMPLES", "2880")))
    parser.add_argument("--seed", type=int, default=int(os.getenv("RELAY_SEED", "-1")))
    parser.add_argument("--connect-timeout-sec", type=float, default=float(os.getenv("RELAY_CONNECT_TIMEOUT_SEC", "20")))
    parser.add_argument("--health-probe-timeout-sec", type=float, default=float(os.getenv("RELAY_HEALTH_PROBE_TIMEOUT_SEC", "2")))
    parser.add_argument("--voice-prompt", default=os.getenv("VOICE_PROMPT", "NATF0.pt"))
    parser.add_argument("--text-prompt", default=os.getenv("TEXT_PROMPT", ""))
    parser.add_argument("--text-prompt-file", default=os.getenv("TEXT_PROMPT_FILE", ""))
    parser.add_argument("--initial-greeting", default=os.getenv("INITIAL_GREETING", ""))
    parser.add_argument("--preset-file", default=os.getenv("PROMPT_PRESET_FILE", ""))
    parser.add_argument("--preset-name", default=os.getenv("PROMPT_PRESET_NAME", "default"))
    parser.add_argument("--proactive-greeting", action="store_true", default=_to_bool(os.getenv("RELAY_PROACTIVE_GREETING", "1")))
    parser.add_argument("--upstream-initial-greeting", action="store_true", default=_to_bool(os.getenv("RELAY_UPSTREAM_INITIAL_GREETING", "0")))
    parser.add_argument("--omnicortex-api-base", default=os.getenv("OMNICORTEX_API_BASE", ""))
    parser.add_argument("--omnicortex-bearer", default=os.getenv("OMNICORTEX_BEARER", ""))
    parser.add_argument("--omnicortex-user-id", default=os.getenv("OMNICORTEX_USER_ID", ""))
    parser.add_argument("--omnicortex-agent-id", default=os.getenv("AGENT_ID", ""))
    parser.add_argument("--omnicortex-fetch-enabled", action="store_true", default=_to_bool(os.getenv("OMNICORTEX_FETCH_ENABLED", "0")))
    parser.add_argument("--prompt-request-timeout-sec", type=float, default=float(os.getenv("PROMPT_REQUEST_TIMEOUT_SEC", "8")))
    parser.add_argument("--tts-enabled", action="store_true", default=_to_bool(os.getenv("RELAY_TTS_ENABLED", "1")))
    parser.add_argument("--tts-voice", default=os.getenv("RELAY_TTS_VOICE", "en-US-AriaNeural"))
    parser.add_argument("--tts-dir", default=os.getenv("RELAY_TTS_DIR", os.path.join(tempfile.gettempdir(), "relay_tts")))
    parser.add_argument("--tts-fallback-delay-sec", type=float, default=float(os.getenv("RELAY_TTS_FALLBACK_DELAY_SEC", "0.65")))
    parser.add_argument("--tts-flush-after-sec", type=float, default=float(os.getenv("RELAY_TTS_FLUSH_AFTER_SEC", "1.2")))
    parser.add_argument("--backchannel-enabled", action="store_true", default=_to_bool(os.getenv("RELAY_BACKCHANNEL_ENABLED", "1")))
    parser.add_argument("--backchannel-phrases", default=os.getenv("RELAY_BACKCHANNELS", ",".join(DEFAULT_BACKCHANNELS)))
    parser.add_argument("--backchannel-min-speech-sec", type=float, default=float(os.getenv("RELAY_BACKCHANNEL_MIN_SPEECH_SEC", "1.2")))
    parser.add_argument("--backchannel-cooldown-sec", type=float, default=float(os.getenv("RELAY_BACKCHANNEL_COOLDOWN_SEC", "4.0")))
    parser.add_argument("--stop-phrases", default=os.getenv("STOP_PHRASES", ",".join(DEFAULT_STOP_PHRASES)))
    parser.add_argument("--vad-energy-threshold", type=float, default=float(os.getenv("RELAY_VAD_ENERGY_THRESHOLD", "0.01")))
    parser.add_argument("--vad-brief-pause-ms", type=int, default=int(os.getenv("RELAY_VAD_BRIEF_PAUSE_MS", "350")))
    parser.add_argument("--vad-utterance-end-ms", type=int, default=int(os.getenv("RELAY_VAD_UTTERANCE_END_MS", "700")))
    parser.add_argument("--vad-brief-factor", type=float, default=float(os.getenv("RELAY_VAD_BRIEF_FACTOR", "0.9")))
    parser.add_argument("--vad-end-factor", type=float, default=float(os.getenv("RELAY_VAD_END_FACTOR", "0.75")))
    parser.add_argument("--partial-grace-ms", type=int, default=int(os.getenv("RELAY_PARTIAL_GRACE_MS", "220")))
    parser.add_argument("--partial-incomplete-endings", default=os.getenv("RELAY_INCOMPLETE_ENDINGS", ",".join(sorted(DEFAULT_INCOMPLETE_ENDINGS))))
    parser.add_argument("--disable-local-asr", action="store_true", default=not _to_bool(os.getenv("RELAY_LOCAL_ASR_ENABLED", "1")))
    parser.add_argument("--asr-min-audio-sec", type=float, default=float(os.getenv("RELAY_ASR_MIN_AUDIO_SEC", "0.8")))
    parser.add_argument("--asr-recheck-sec", type=float, default=float(os.getenv("RELAY_ASR_RECHECK_SEC", "0.8")))
    parser.add_argument("--greeting-words", default=os.getenv("RELAY_GREETING_WORDS", ",".join(sorted(DEFAULT_GREETING_WORDS))))
    parser.add_argument("--response-idle-sec", type=float, default=float(os.getenv("RELAY_RESPONSE_IDLE_SEC", "1.25")))
    parser.add_argument("--max-utterance-sec", type=float, default=float(os.getenv("RELAY_MAX_UTTERANCE_SEC", "20.0")))
    parser.add_argument("--log-text-frames", action="store_true", default=_to_bool(os.getenv("RELAY_LOG_TEXT_FRAMES", "0")))
    parser.add_argument("--send-fs-connected-ack", action="store_true", default=_to_bool(os.getenv("RELAY_SEND_FS_CONNECTED_ACK", "0")))
    parser.add_argument("--native-audio-only", action="store_true", default=_to_bool(os.getenv("RELAY_NATIVE_AUDIO_ONLY", "0")))
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = build_config(args)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    LOG.info(
        "starting direct relay host=%s port=%s path=%s upstream=%s fs_rate=%s prompt_fetch=%s tts=%s backchannel=%s asr=%s native_audio_only=%s",
        cfg.host,
        cfg.port,
        cfg.path,
        cfg.personaplex_ws,
        cfg.fs_sample_rate,
        cfg.omnicortex_fetch_enabled,
        cfg.tts_enabled,
        cfg.backchannel_enabled,
        cfg.local_asr_enabled,
        cfg.native_audio_only,
    )
    service = DirectRelayService(cfg)
    web.run_app(service.app, host=cfg.host, port=cfg.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
