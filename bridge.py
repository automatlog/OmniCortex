"""
bridge.py -- Self-contained FreeSWITCH <-> Moshi audio bridge.

FreeSWITCH  --L16/16kHz-->  bridge.py  --kind=1+OggOpus/24kHz-->  Moshi (8998)
FreeSWITCH  <--L16/16kHz--  bridge.py  <--kind=1+OggOpus/24kHz--  Moshi (8998)

Uses opuslib + minimal Ogg container. No sphn dependency.
Sends continuous audio (real or silence) so Moshi's pipeline stays active.
"""

import asyncio
import json
import os
import re
import shlex
import struct
import time
import wave
from contextlib import suppress
from datetime import datetime
from urllib.parse import quote

import numpy as np
import opuslib
import websockets
from websockets.asyncio.server import serve

try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False
    print("\033[93mWARNING: edge-tts not installed. Run: pip install edge-tts\033[0m")

try:
    from core.voice.asr_engine import get_asr_engine
    HAS_LOCAL_ASR = True
except Exception:
    HAS_LOCAL_ASR = False
    get_asr_engine = None
    print("\033[93mWARNING: faster-whisper ASR unavailable. Phrase barge-in disabled.\033[0m")


# ── ANSI Colors ─────────────────────────────────────────────────────
C_RESET   = "\033[0m"
C_BOLD    = "\033[1m"
C_DIM     = "\033[2m"
C_RED     = "\033[91m"
C_GREEN   = "\033[92m"
C_YELLOW  = "\033[93m"
C_BLUE    = "\033[94m"
C_MAGENTA = "\033[95m"
C_CYAN    = "\033[96m"
C_WHITE   = "\033[97m"
C_BG_RED  = "\033[41m"
C_BG_GRN  = "\033[42m"
C_BG_BLU  = "\033[44m"

# ── Log helpers ─────────────────────────────────────────────────────
def _ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

def log_call(msg):
    print(f"{C_BG_GRN}{C_BOLD} CALL {C_RESET} {C_DIM}{_ts()}{C_RESET}  {msg}")

def log_fs_in(uuid, msg):
    print(f"{C_GREEN}  FS>{C_RESET}  {C_DIM}{_ts()}{C_RESET}  {C_DIM}[{uuid[:8]}]{C_RESET} {msg}")

def log_fs_out(uuid, msg):
    print(f"{C_CYAN}  <FS{C_RESET}  {C_DIM}{_ts()}{C_RESET}  {C_DIM}[{uuid[:8]}]{C_RESET} {msg}")

def log_moshi_in(uuid, msg):
    print(f"{C_MAGENTA}MOSHI>{C_RESET} {C_DIM}{_ts()}{C_RESET}  {C_DIM}[{uuid[:8]}]{C_RESET} {msg}")

def log_moshi_out(uuid, msg):
    print(f"{C_BLUE}<MOSHI{C_RESET} {C_DIM}{_ts()}{C_RESET}  {C_DIM}[{uuid[:8]}]{C_RESET} {msg}")

def log_text(uuid, text):
    clean = text.replace("\u2581", " ")
    end_char = "\n" if any(c in text for c in ".!?\n") else ""
    print(f"{C_YELLOW}  TXT{C_RESET}  {C_DIM}{_ts()}{C_RESET}  {C_DIM}[{uuid[:8]}]{C_RESET} {C_YELLOW}{clean}{C_RESET}", end=end_char, flush=True)

def log_pump(uuid, msg):
    print(f"{C_DIM} PUMP  {_ts()}  [{uuid[:8]}] {msg}{C_RESET}")

def log_tone(uuid, msg):
    print(f"{C_WHITE}{C_BOLD} TONE{C_RESET}  {C_DIM}{_ts()}{C_RESET}  {C_DIM}[{uuid[:8]}]{C_RESET} {msg}")

def log_error(uuid, msg):
    print(f"{C_BG_RED}{C_BOLD} ERR  {C_RESET} {C_DIM}{_ts()}{C_RESET}  {C_DIM}[{uuid[:8]}]{C_RESET} {C_RED}{msg}{C_RESET}")

def log_info(uuid, msg):
    print(f"{C_WHITE} INFO{C_RESET}  {C_DIM}{_ts()}{C_RESET}  {C_DIM}[{uuid[:8]}]{C_RESET} {msg}")

def log_debug(uuid, msg):
    print(f"{C_DIM} DBG   {_ts()}  [{uuid[:8]}] {msg}{C_RESET}")

def log_tts(uuid, msg):
    print(f"{C_YELLOW}{C_BOLD}  TTS{C_RESET}  {C_DIM}{_ts()}{C_RESET}  {C_DIM}[{uuid[:8]}]{C_RESET} {msg}")

def _bar(value, width=20, max_val=0.15):
    filled = int(min(value / max_val, 1.0) * width)
    if value < 0.005:
        color = C_DIM
    elif value < 0.03:
        color = C_GREEN
    elif value < 0.08:
        color = C_YELLOW
    else:
        color = C_RED
    return f"{color}{'|' * filled}{C_DIM}{'.' * (width - filled)}{C_RESET}"


# ── Config ──────────────────────────────────────────────────────────
def parse_float_env(name: str, default: float) -> float:
    """Safely parse a float environment variable with fallback."""
    try:
        value = os.getenv(name, "").strip()
        if not value:
            return default
        return float(value)
    except (ValueError, TypeError):
        logger.error("Invalid value for env var %s; using default %.2f", name, default)
        return default


FS_PORT           = 8001
API_KEY           = os.getenv("BRIDGE_API_KEY", "")
_BASE_URL         = os.getenv("BRIDGE_BASE_URL", "wss://localhost:8998/api/chat")
_TEXT_PROMPT      = "You work for ICICI Bank and your name is Priya Sharma. You are a helpful and professional customer service representative specializing in personal accounts and loan products. You are currently assisting a customer who holds a personal savings account with a current balance of ₹50,000. Your role is to help the customer with any queries related to their account balance, recent transactions, and available loan products including personal loans, home loans, car loans, and education loans. When discussing loans, always mention that ICICI Bank offers competitive interest rates starting from 10.5% per annum for personal loans, with flexible EMI options and instant approval for eligible customers. Always verify the customer's identity before sharing any account details by asking for their registered mobile number and date of birth. Speak in a warm, helpful, and professional tone. If the customer asks about loan eligibility, guide them based on their current balance and account history."
MOSHI_URL         = f"{_BASE_URL}?text_prompt={quote(_TEXT_PROMPT)}"

FS_RATE           = 8000   # FreeSWITCH L16 mono (must match uuid_audio_stream rate)
FS_RETURN_RATE    = 8000    # Match caller's PCMU/8000 codec
FS_BIG_ENDIAN     = False   # Set True if mod_audio_stream expects big-endian L16
TEST_TONE_MODE    = False   # Disabled — mod_audio_stream receive doesn't work
MOSHI_RATE        = 24000   # Moshi native rate
OPUS_FRAME_MS     = 20
OPUS_FRAME_SAMPLES = MOSHI_RATE * OPUS_FRAME_MS // 1000  # 480 @ 24kHz (for encode)
OPUS_48K_FRAME    = 48000 * OPUS_FRAME_MS // 1000         # 960 (granule is 48k)
MAX_DECODE_SAMPLES = MOSHI_RATE * 120 // 1000             # 2880 — safe upper bound for decode

# Moshi kind bytes
KIND_HANDSHAKE = 0x00
KIND_AUDIO     = 0x01
KIND_TEXT      = 0x02
KIND_SPECIAL   = 0x03

SUPPRESS_TOKENS   = {"PAD", "EPAD"}

# TTS playback via FreeSWITCH (bypasses broken mod_audio_stream receive)
TTS_ENABLED       = True
TTS_VOICE         = "en-US-AriaNeural"   # Microsoft Edge TTS voice (default)
TTS_DIR           = "/tmp/bridge_tts"
PHRASE_BARGE_IN_ENABLED = os.getenv("PHRASE_BARGE_IN_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
PHRASE_BARGE_IN_MIN_AUDIO_SEC = parse_float_env("PHRASE_BARGE_IN_MIN_AUDIO_SEC", 0.8)
PHRASE_BARGE_IN_MAX_AUDIO_SEC = parse_float_env("PHRASE_BARGE_IN_MAX_AUDIO_SEC", 2.5)
PHRASE_BARGE_IN_CHECK_INTERVAL_SEC = parse_float_env("PHRASE_BARGE_IN_CHECK_INTERVAL_SEC", 0.8)
PHRASE_BARGE_IN_RMS_GATE = parse_float_env("PHRASE_BARGE_IN_RMS_GATE", 0.012)
TTS_SUPPRESS_AFTER_BARGE_SEC = parse_float_env("TTS_SUPPRESS_AFTER_BARGE_SEC", 1.75)
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

# Language-aware TTS voice map for dynamic switching
TTS_VOICE_MAP = {
    "en": "en-US-AriaNeural",
    "hi": "hi-IN-SwaraNeural",
    "gu": "gu-IN-DhwaniNeural",
    "ta": "ta-IN-PallaviNeural",
    "te": "te-IN-ShrutiNeural",
    "mr": "mr-IN-AarohiNeural",
    "bn": "bn-IN-TanishaaNeural",
    "kn": "kn-IN-SapnaNeural",
    "ml": "ml-IN-SobhanaNeural",
    "ur": "ur-PK-UzmaNeural",
    "es": "es-ES-ElviraNeural",
    "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural",
    "ja": "ja-JP-NanamiNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
    "ar": "ar-SA-ZariyahNeural",
}
FS_CLI            = "/usr/local/freeswitch/bin/fs_cli"  # FreeSWITCH CLI
DEBUG_DUMP_PCM    = os.getenv("DEBUG_DUMP_PCM", "false").strip().lower() == "true" or os.getenv("DEBUG_WAV", "false").strip().lower() == "true"
MAX_DEBUG_PCM_BYTES = max(0, int(os.getenv("MAX_DEBUG_PCM_BYTES", str(16 * 1024 * 1024))))
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

if not API_KEY:
    raise RuntimeError("MOSHI_API_KEY is required. Set it via environment variables.")


def _detect_text_language(text: str) -> str:
    """Simple script-based language detection from text.
    Returns ISO 639-1 code. Falls back to 'en'."""
    if not text or len(text.strip()) < 3:
        return "en"
    # Count characters by Unicode script
    devanagari = sum(1 for c in text if '\u0900' <= c <= '\u097F')  # Hindi, Marathi, Sanskrit
    gujarati = sum(1 for c in text if '\u0A80' <= c <= '\u0AFF')
    tamil = sum(1 for c in text if '\u0B80' <= c <= '\u0BFF')
    telugu = sum(1 for c in text if '\u0C00' <= c <= '\u0C7F')
    bengali = sum(1 for c in text if '\u0980' <= c <= '\u09FF')
    kannada = sum(1 for c in text if '\u0C80' <= c <= '\u0CFF')
    arabic = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    cjk = sum(1 for c in text if '\u4E00' <= c <= '\u9FFF')
    hiragana = sum(1 for c in text if '\u3040' <= c <= '\u309F')
    total = len(text.replace(" ", ""))
    if total == 0:
        return "en"
    # Require at least 20% non-Latin characters to switch
    threshold = total * 0.2
    if devanagari > threshold:
        return "hi"
    if gujarati > threshold:
        return "gu"
    if tamil > threshold:
        return "ta"
    if telugu > threshold:
        return "te"
    if bengali > threshold:
        return "bn"
    if kannada > threshold:
        return "kn"
    if arabic > threshold:
        return "ar"
    if cjk > threshold:
        return "zh"
    if hiragana > threshold:
        return "ja"
    return "en"


def _normalize_phrase_text(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]+", " ", str(text or "").lower()).strip()


def _match_stop_phrase(text: str) -> str:
    normalized = f" {_normalize_phrase_text(text)} "
    for phrase in STOP_PHRASES:
        needle = _normalize_phrase_text(phrase)
        if needle and f" {needle} " in normalized:
            return phrase
    return ""


def sanitize_uuid(raw: str) -> str:
    candidate = (raw or "").strip()
    if not _UUID_RE.fullmatch(candidate):
        raise ValueError(f"Invalid UUID for bridge session: {raw!r}")
    return candidate


def append_debug_pcm(debug_buffer: bytearray | None, chunk: bytes) -> None:
    if debug_buffer is None or not chunk or MAX_DEBUG_PCM_BYTES <= 0:
        return
    if len(chunk) >= MAX_DEBUG_PCM_BYTES:
        debug_buffer.clear()
        debug_buffer.extend(chunk[-MAX_DEBUG_PCM_BYTES:])
        return
    overflow = len(debug_buffer) + len(chunk) - MAX_DEBUG_PCM_BYTES
    if overflow > 0:
        del debug_buffer[:overflow]
    debug_buffer.extend(chunk)


# ── Ogg CRC-32 (polynomial 0x04C11DB7) ──────────────────────────────

_OGG_CRC_TABLE = []
for i in range(256):
    r = i << 24
    for _ in range(8):
        r = ((r << 1) ^ 0x04C11DB7) if r & 0x80000000 else (r << 1)
    _OGG_CRC_TABLE.append(r & 0xFFFFFFFF)


def _ogg_crc(data: bytes) -> int:
    crc = 0
    for b in data:
        crc = ((crc << 8) ^ _OGG_CRC_TABLE[((crc >> 24) ^ b) & 0xFF]) & 0xFFFFFFFF
    return crc


# ── Ogg Demuxer ──────────────────────────────────────────────────────

class OggDemuxer:
    def __init__(self):
        self._buf = bytearray()
        self._pages_seen = 0

    def feed(self, data: bytes) -> list:
        self._buf.extend(data)
        packets = []
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
            if self._pages_seen > 2:  # skip OpusHead + OpusTags
                offset = header_end
                packet = bytearray()
                for seg_len in seg_table:
                    packet.extend(self._buf[offset:offset + seg_len])
                    offset += seg_len
                    if seg_len < 255:
                        if packet:
                            packets.append(bytes(packet))
                        packet = bytearray()
            self._buf = self._buf[page_end:]
        return packets


# ── Ogg Muxer ────────────────────────────────────────────────────────

class OggMuxer:
    def __init__(self, sample_rate=24000, channels=1):
        self._serial = 0x4272696E
        self._page_seq = 0
        self._granule = 0
        self._sr = sample_rate
        self._ch = channels
        self._started = False

    def _page(self, payload: bytes, granule: int, flags: int = 0) -> bytes:
        segs = []
        rem = len(payload)
        while rem >= 255:
            segs.append(255)
            rem -= 255
        segs.append(rem)
        buf = bytearray(27 + len(segs) + len(payload))
        struct.pack_into("<4sBBqIIIB", buf, 0,
                         b"OggS", 0, flags, granule,
                         self._serial, self._page_seq, 0, len(segs))
        buf[27:27 + len(segs)] = bytes(segs)
        buf[27 + len(segs):] = payload
        struct.pack_into("<I", buf, 22, _ogg_crc(bytes(buf)))
        self._page_seq += 1
        return bytes(buf)

    def encode(self, opus_pkt: bytes) -> bytes:
        out = bytearray()
        if not self._started:
            head = struct.pack("<8sBBHIhB", b"OpusHead", 1, self._ch,
                               312, self._sr, 0, 0)
            out.extend(self._page(head, 0, flags=0x02))
            vendor = b"bridge"
            tags = struct.pack("<8sI", b"OpusTags", len(vendor)) + vendor + struct.pack("<I", 0)
            out.extend(self._page(tags, 0))
            self._started = True
        self._granule += OPUS_48K_FRAME
        out.extend(self._page(opus_pkt, self._granule))
        return bytes(out)


# ── PCM helpers ──────────────────────────────────────────────────────

def resample(pcm, from_rate, to_rate):
    if from_rate == to_rate or len(pcm) == 0:
        return pcm
    n_out = int(len(pcm) * to_rate / from_rate)
    if n_out == 0:
        return np.array([], dtype=np.float32)
    idx = np.linspace(0, len(pcm) - 1, n_out)
    left = np.floor(idx).astype(int)
    right = np.clip(left + 1, 0, len(pcm) - 1)
    frac = (idx - left).astype(np.float32)
    return (pcm[left] * (1.0 - frac) + pcm[right] * frac).astype(np.float32)

def pcm16_to_f32(data, big_endian=False):
    dtype = ">i2" if big_endian else "<i2"
    return np.frombuffer(data, dtype=dtype).astype(np.float32) / 32768.0

def f32_to_pcm16(pcm, big_endian=False):
    dtype = ">i2" if big_endian else "<i2"
    return (np.clip(pcm, -1.0, 1.0) * 32767.0).astype(dtype).tobytes()


# ── Per-call handler ──────────────────────────────────────────────────

async def bridge_connection(fs_ws):
    path = getattr(fs_ws.request, "path", "/")
    raw_uuid = path.split("/")[-1] or "unknown"
    try:
        uuid = sanitize_uuid(raw_uuid)
    except ValueError as exc:
        log_error(raw_uuid, str(exc))
        with suppress(Exception):
            await fs_ws.close()
        return
    call_start = time.monotonic()

    print()
    log_call(f"{C_BOLD}{C_GREEN}New call{C_RESET}  uuid={C_BOLD}{uuid}{C_RESET}")
    print(f"{C_DIM}  {'=' * 70}{C_RESET}")

    encoder   = opuslib.Encoder(MOSHI_RATE, 1, opuslib.APPLICATION_VOIP)
    decoder   = opuslib.Decoder(MOSHI_RATE, 1)
    ogg_mux   = OggMuxer(MOSHI_RATE)
    ogg_demux = OggDemuxer()
    pcm_buf   = np.array([], dtype=np.float32)
    hs_event  = asyncio.Event()
    last_fs_send = [0.0]           # monotonic time of last fs_to_moshi send
    frame_cnt = [0, 0]            # [sent, received] for debug
    debug_pcm = bytearray() if DEBUG_DUMP_PCM else None
    tts_queue      = asyncio.Queue()   # sentences waiting for TTS
    phrase_audio_queue = asyncio.Queue(maxsize=48)
    sentence_buf   = [""]              # mutable accumulator for text tokens
    last_text_time = [0.0]             # monotonic time of last text token
    tts_playing    = [False]           # True while uuid_broadcast is active
    tts_active     = [False]           # True while generating or playing TTS
    tts_generation = [0]               # Increment to invalidate current queued/active TTS jobs
    suppress_tts_until = [0.0]         # Temporarily suppress AI TTS after user interrupt

    # Language detection from text tokens
    detected_tts_voice = [TTS_VOICE]   # current TTS voice, can change dynamically
    text_token_buf     = [""]          # accumulate text tokens for language detection
    text_byte_buf      = bytearray()   # accumulate raw bytes for multi-byte UTF-8 reassembly

    async def cancel_tts(reason: str, transcript: str = "") -> None:
        had_activity = tts_active[0] or tts_playing[0] or (not tts_queue.empty())
        tts_generation[0] += 1
        tts_active[0] = False
        tts_playing[0] = False
        suppress_tts_until[0] = time.monotonic() + TTS_SUPPRESS_AFTER_BARGE_SEC
        sentence_buf[0] = ""
        text_token_buf[0] = ""
        text_byte_buf.clear()

        drained = 0
        while True:
            try:
                item = tts_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            else:
                if item is not None:
                    drained += 1
                with suppress(ValueError):
                    tts_queue.task_done()

        if not had_activity and drained == 0:
            return

        transcript_suffix = f' transcript="{transcript}"' if transcript else ""
        log_tts(uuid, f"{C_RED}{C_BOLD}CANCEL{C_RESET} reason={reason} drained={drained}{transcript_suffix}")
        try:
            proc = await asyncio.create_subprocess_exec(
                FS_CLI, "-x", f"uuid_break {uuid} all",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
                log_tts(uuid, f"uuid_break result: {out.decode().strip()}")
            except asyncio.TimeoutError:
                log_error(uuid, f"uuid_break timed out after 5s (uuid={uuid})")
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                    await proc.wait()
        except Exception as e:
            log_error(uuid, f"uuid_break failed: {e}")

    try:
        async with websockets.connect(
            MOSHI_URL,
            extra_headers={"x-api-key": API_KEY},
            max_size=10 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=30,
        ) as moshi_ws:
            log_info(uuid, f"{C_GREEN}Connected to Moshi{C_RESET}  url={C_DIM}{_BASE_URL}{C_RESET}")

            # ── Encode one Opus frame and send to Moshi ───────────────
            def encode_and_wrap(pcm_f32_24k):
                pcm16 = f32_to_pcm16(pcm_f32_24k)
                opus_pkt = encoder.encode(pcm16, OPUS_FRAME_SAMPLES)
                return bytes([KIND_AUDIO]) + ogg_mux.encode(opus_pkt)

            # ── Encode + send PCM to Moshi ────────────────────────────
            async def send_pcm(raw: bytes) -> None:
                nonlocal pcm_buf
                pcm_f32 = pcm16_to_f32(raw, big_endian=FS_BIG_ENDIAN)
                pcm_24k = resample(pcm_f32, FS_RATE, MOSHI_RATE)
                pcm_buf = np.concatenate([pcm_buf, pcm_24k])
                while len(pcm_buf) >= OPUS_FRAME_SAMPLES:
                    frame   = pcm_buf[:OPUS_FRAME_SAMPLES]
                    pcm_buf = pcm_buf[OPUS_FRAME_SAMPLES:]
                    await moshi_ws.send(encode_and_wrap(frame))
                    frame_cnt[0] += 1

            # ── Steady clock: feed Moshi at 20ms intervals ────────────
            async def audio_pump() -> None:
                await hs_event.wait()
                log_pump(uuid, "Started (feeding silence to Moshi)")
                silence = np.zeros(OPUS_FRAME_SAMPLES, dtype=np.float32)
                t0 = time.monotonic()
                tick = 0
                while True:
                    tick += 1
                    # Only skip if fs_to_moshi sent a frame very recently (<25ms)
                    now = time.monotonic()
                    if now - last_fs_send[0] < 0.025:
                        next_t = t0 + tick * (OPUS_FRAME_MS / 1000.0)
                        delay = next_t - now
                        if delay > 0:
                            await asyncio.sleep(delay)
                        continue
                    await moshi_ws.send(encode_and_wrap(silence))
                    frame_cnt[0] += 1
                    if tick <= 3 or tick % 500 == 0:
                        elapsed = now - call_start
                        silence_gap = now - last_fs_send[0]
                        log_pump(uuid, f"sent={frame_cnt[0]}  recv={frame_cnt[1]}  elapsed={elapsed:.1f}s  last_fs={silence_gap:.1f}s ago")
                    next_t = t0 + tick * (OPUS_FRAME_MS / 1000.0)
                    delay = next_t - time.monotonic()
                    if delay > 0:
                        await asyncio.sleep(delay)

            # ── FreeSWITCH -> Moshi ───────────────────────────────────
            async def fs_to_moshi() -> None:
                await hs_event.wait()
                fs_frames = 0
                async for data in fs_ws:
                    if not isinstance(data, bytes):
                        log_fs_in(uuid, f"metadata: {C_BOLD}{data}{C_RESET}")
                        ack = json.dumps({"type": "connected", "protocol": "audio"})
                        await fs_ws.send(ack)
                        log_fs_out(uuid, f"Sent ack: {C_DIM}{ack}{C_RESET}")
                        continue
                    last_fs_send[0] = time.monotonic()
                    fs_frames += 1

                    # Compute RMS for logging and barge-in detection
                    pcm_f32_tmp = pcm16_to_f32(data, big_endian=FS_BIG_ENDIAN)
                    rms_in = float(np.sqrt(np.mean(pcm_f32_tmp ** 2))) if len(pcm_f32_tmp) > 0 else 0.0

                    # Log first 5, then every 250th frame
                    if fs_frames <= 5 or fs_frames % 250 == 0:
                        log_fs_in(uuid, f"PCM #{fs_frames}: {len(data)}B  rms={rms_in:.4f} {_bar(rms_in)}")

                    if (
                        PHRASE_BARGE_IN_ENABLED
                        and HAS_LOCAL_ASR
                        and (tts_active[0] or tts_playing[0])
                    ):
                        try:
                            phrase_audio_queue.put_nowait(pcm_f32_tmp.copy())
                        except asyncio.QueueFull:
                            with suppress(asyncio.QueueEmpty):
                                phrase_audio_queue.get_nowait()
                                phrase_audio_queue.task_done()
                            with suppress(asyncio.QueueFull):
                                phrase_audio_queue.put_nowait(pcm_f32_tmp.copy())

                    # NOTE: Backchannel via kind=2 text frames is NOT supported by
                    # vanilla Moshi server — it logs "[Warn] unknown message kind 2"
                    # and disconnects. Backchanneling only works in mode_personaplex.py
                    # where PersonaPlex accepts kind=2 input. For bridge.py, a future
                    # approach would use short edge-tts clips via uuid_broadcast.

                    await send_pcm(data)

            # ── Test tone generator ──────────────────────────────────
            async def test_tone_to_fs() -> None:
                await hs_event.wait()
                await asyncio.sleep(0.5)
                log_tone(uuid, f"{C_BOLD}Sending 440Hz sine wave to FS for 5s{C_RESET}")
                duration_s = 5
                freq = 440
                rate = FS_RETURN_RATE
                t = np.arange(int(rate * duration_s)) / rate
                sine = (np.sin(2 * np.pi * freq * t) * 0.3).astype(np.float32)
                pcm_data = f32_to_pcm16(sine, big_endian=FS_BIG_ENDIAN)
                CHUNK = rate * 2 * OPUS_FRAME_MS // 1000
                chunk_count = 0
                t0 = time.monotonic()
                for i in range(0, len(pcm_data), CHUNK):
                    chunk = pcm_data[i:i + CHUNK]
                    if len(chunk) > 0:
                        await fs_ws.send(chunk)
                        chunk_count += 1
                        next_t = t0 + chunk_count * (OPUS_FRAME_MS / 1000.0)
                        delay = next_t - time.monotonic()
                        if delay > 0:
                            await asyncio.sleep(delay)
                log_tone(uuid, f"{C_GREEN}Done.{C_RESET} {chunk_count} chunks, {len(pcm_data)} bytes")

            # ── Phrase-based barge-in: only stop TTS on explicit stop phrases ──
            async def phrase_barge_worker() -> None:
                if not PHRASE_BARGE_IN_ENABLED:
                    return
                if not HAS_LOCAL_ASR:
                    log_info(uuid, f"{C_YELLOW}Phrase barge-in disabled{C_RESET}  local ASR unavailable")
                    return

                min_samples = max(1, int(FS_RATE * PHRASE_BARGE_IN_MIN_AUDIO_SEC))
                max_samples = max(min_samples, int(FS_RATE * PHRASE_BARGE_IN_MAX_AUDIO_SEC))
                last_check = 0.0
                pcm_window = np.array([], dtype=np.float32)
                asr = await get_asr_engine()
                if asr is None:
                    log_error(uuid, "ASR engine unavailable; phrase barge-in disabled")
                    return
                log_info(uuid, f"{C_YELLOW}Phrase barge-in enabled{C_RESET}  stop_phrases={len(STOP_PHRASES)}")

                while True:
                    chunk = await phrase_audio_queue.get()
                    try:
                        if chunk is None:
                            return
                        if not (tts_active[0] or tts_playing[0]):
                            pcm_window = np.array([], dtype=np.float32)
                            continue
                        if chunk.size == 0:
                            continue

                        rms_in = float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) > 0 else 0.0
                        if rms_in < PHRASE_BARGE_IN_RMS_GATE:
                            if pcm_window.size > max_samples:
                                pcm_window = pcm_window[-max_samples:]
                            continue

                        pcm_window = np.concatenate([pcm_window, chunk])
                        if pcm_window.size > max_samples:
                            pcm_window = pcm_window[-max_samples:]
                        now = time.monotonic()
                        if pcm_window.size < min_samples:
                            continue
                        if now - last_check < PHRASE_BARGE_IN_CHECK_INTERVAL_SEC:
                            continue

                        last_check = now
                        try:
                            transcript, confidence, detected_lang = await asr.transcribe(
                                pcm_window.copy(), sample_rate=FS_RATE
                            )
                        except Exception as e:
                            log_tts(uuid, f"Barge-in ASR failed: {e}")
                            continue
                        transcript = (transcript or "").strip()
                        if transcript:
                            log_tts(
                                uuid,
                                f'Barge-in ASR lang={detected_lang} conf={confidence:.2f} text="{transcript}"'
                            )
                        phrase = _match_stop_phrase(transcript)
                        if phrase:
                            await cancel_tts(
                                reason=f"stop_phrase:{phrase}",
                                transcript=transcript,
                            )
                            pcm_window = np.array([], dtype=np.float32)
                        elif pcm_window.size >= max_samples:
                            pcm_window = pcm_window[-min_samples:]
                    finally:
                        phrase_audio_queue.task_done()

            # ── TTS worker: text tokens → audio file → FS playback ───
            async def tts_worker() -> None:
                if not TTS_ENABLED or not HAS_EDGE_TTS:
                    return
                os.makedirs(TTS_DIR, exist_ok=True)
                seq = 0
                while True:
                    text = await tts_queue.get()
                    if text is None:
                        break
                    seq += 1
                    mp3_path = wav_path = None
                    job_generation = tts_generation[0]
                    try:
                        if time.monotonic() < suppress_tts_until[0]:
                            log_tts(uuid, f"Skip #{seq}: suppressed after barge-in")
                            continue
                        tts_active[0] = True
                        log_tts(uuid, f"Gen #{seq}: \"{text}\"")
                        ts_ms = int(time.time() * 1000)
                        mp3_path = f"{TTS_DIR}/{uuid[:8]}_{ts_ms}.mp3"
                        wav_path = mp3_path.replace(".mp3", ".wav")

                        voice = detected_tts_voice[0]
                        comm = edge_tts.Communicate(text, voice)
                        await comm.save(mp3_path)
                        if job_generation != tts_generation[0]:
                            log_tts(uuid, f"Drop #{seq}: cancelled during TTS generation")
                            continue

                        proc = await asyncio.create_subprocess_exec(
                            "ffmpeg", "-y", "-loglevel", "error",
                            "-i", mp3_path,
                            "-ar", "8000", "-ac", "1", "-sample_fmt", "s16",
                            wav_path,
                            stdout=asyncio.subprocess.DEVNULL,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        _, stderr = await proc.communicate()
                        if proc.returncode != 0:
                            log_error(uuid, f"ffmpeg: {stderr.decode().strip()}")
                            continue
                        if job_generation != tts_generation[0]:
                            log_tts(uuid, f"Drop #{seq}: cancelled during ffmpeg conversion")
                            continue
                        if mp3_path and os.path.exists(mp3_path):
                            os.unlink(mp3_path)
                            mp3_path = None

                        if not os.path.exists(wav_path):
                            log_error(uuid, "TTS: WAV not created")
                            continue

                        wav_size = os.path.getsize(wav_path)
                        dur = wav_size / (8000 * 2)
                        log_tts(uuid, f"Play #{seq}: {wav_size}B ({dur:.1f}s)")

                        cmd = f"uuid_broadcast {uuid} {shlex.quote(wav_path)} aleg"
                        proc = await asyncio.create_subprocess_exec(
                            FS_CLI, "-x", cmd,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        out, _ = await proc.communicate()
                        if job_generation != tts_generation[0]:
                            log_tts(uuid, f"Drop #{seq}: cancelled before playback")
                            continue
                        result = out.decode().strip()
                        if "+OK" in result:
                            log_tts(uuid, f"#{seq} broadcast started")
                            tts_playing[0] = True
                        else:
                            log_error(uuid, f"broadcast: {result}")

                        # Wait for playback to finish (or barge-in clears the flag)
                        sleep_step = 0.1
                        remaining = dur + 0.5
                        while remaining > 0 and tts_playing[0] and job_generation == tts_generation[0]:
                            await asyncio.sleep(min(sleep_step, remaining))
                            remaining -= sleep_step
                        tts_playing[0] = False

                    except Exception as e:
                        log_error(uuid, f"TTS: {e}")
                    finally:
                        tts_active[0] = False
                        tts_playing[0] = False
                        for p in (mp3_path, wav_path):
                            if p and os.path.exists(p):
                                with suppress(OSError):
                                    os.unlink(p)
                        tts_queue.task_done()

            # ── Flush incomplete sentences after a pause ────────────
            async def text_flusher() -> None:
                if not TTS_ENABLED:
                    return
                while True:
                    await asyncio.sleep(1.0)
                    buf = sentence_buf[0].strip()
                    if buf and len(buf) > 2 and time.monotonic() - last_text_time[0] > 1.5:
                        sentence_buf[0] = ""
                        clean = buf.replace("\u2581", " ").strip()
                        if clean and time.monotonic() >= suppress_tts_until[0]:
                            tts_queue.put_nowait(clean)
                            log_tts(uuid, f"Flushed: \"{clean}\"")

            # ── Moshi -> FreeSWITCH ───────────────────────────────────
            audio_chunks_in = [0]

            async def moshi_to_fs() -> None:
                try:
                    msg_iter = moshi_ws.__aiter__()
                except AttributeError:
                    msg_iter = moshi_ws
                while True:
                    try:
                        data = await msg_iter.__anext__()
                    except StopAsyncIteration:
                        log_info(uuid, "Moshi stream ended")
                        return
                    except websockets.exceptions.ConnectionClosedOK:
                        log_info(uuid, "Moshi closed normally")
                        return
                    except websockets.exceptions.ConnectionClosed as e:
                        log_error(uuid, f"Moshi connection closed: {e}")
                        return
                    if not isinstance(data, bytes) or not data:
                        continue
                    kind    = data[0]
                    payload = data[1:]

                    if kind == KIND_HANDSHAKE:
                        log_moshi_in(uuid, f"{C_GREEN}{C_BOLD}Handshake received{C_RESET}")
                        hs_event.set()

                    elif kind == KIND_AUDIO and payload:
                        audio_chunks_in[0] += 1
                        if audio_chunks_in[0] <= 3:
                            log_moshi_in(uuid, f"Ogg chunk #{audio_chunks_in[0]}: {len(payload)}B")
                        opus_packets = ogg_demux.feed(payload)
                        for pkt in opus_packets:
                            try:
                                pcm16_bytes = decoder.decode(pkt, MAX_DECODE_SAMPLES)
                                pcm_f32 = pcm16_to_f32(pcm16_bytes)
                                resampled = resample(pcm_f32, MOSHI_RATE, FS_RETURN_RATE)
                                rms = float(np.sqrt(np.mean(resampled ** 2))) if len(resampled) > 0 else 0.0
                                out_full = f32_to_pcm16(resampled, big_endian=FS_BIG_ENDIAN)
                                append_debug_pcm(debug_pcm, f32_to_pcm16(resampled))
                                CHUNK = FS_RETURN_RATE * 2 * OPUS_FRAME_MS // 1000
                                chunks_sent = 0
                                for i in range(0, len(out_full), CHUNK):
                                    chunk = out_full[i:i + CHUNK]
                                    if len(chunk) > 0:
                                        await fs_ws.send(chunk)
                                        chunks_sent += 1
                                frame_cnt[1] += 1
                                if frame_cnt[1] <= 10 or frame_cnt[1] % 250 == 0:
                                    log_moshi_out(uuid,
                                        f"frame {C_BOLD}#{frame_cnt[1]:<5}{C_RESET} "
                                        f"rms={rms:.4f} {_bar(rms)} "
                                        f"{len(out_full)}B -> {chunks_sent}x{CHUNK}B")
                            except opuslib.exceptions.OpusError as e:
                                log_error(uuid, f"Opus decode: {e}")
                            except websockets.exceptions.ConnectionClosed:
                                log_info(uuid, "FS WebSocket closed during send")
                                return

                    elif kind == KIND_TEXT:
                        # Accumulate raw bytes for multi-byte UTF-8 reassembly
                        # Moshi can split chars like ₹ (E2 82 B9) across tokens
                        text_byte_buf.extend(payload)
                        try:
                            token = text_byte_buf.decode("utf-8")
                            text_byte_buf.clear()
                        except UnicodeDecodeError:
                            # Incomplete multi-byte sequence — wait for more
                            if len(text_byte_buf) > 6:
                                # Too many bad bytes, flush with replacement
                                token = text_byte_buf.decode("utf-8", errors="replace")
                                text_byte_buf.clear()
                            else:
                                continue
                        log_text(uuid, token)
                        if TTS_ENABLED and HAS_EDGE_TTS:
                            sentence_buf[0] += token
                            text_token_buf[0] += token
                            last_text_time[0] = time.monotonic()

                            # Language detection from accumulated text tokens
                            if len(text_token_buf[0]) > 30:
                                new_lang = _detect_text_language(text_token_buf[0])
                                new_voice = TTS_VOICE_MAP.get(new_lang, TTS_VOICE)
                                if new_voice != detected_tts_voice[0]:
                                    log_info(uuid, f"Language switch: {detected_tts_voice[0]} -> {new_voice} (lang={new_lang})")
                                    detected_tts_voice[0] = new_voice
                                text_token_buf[0] = ""  # reset for next detection window

                            # Sentence boundary detection — skip decimal points in numbers
                            buf = sentence_buf[0]
                            for end_ch in ".!?\n":
                                if end_ch in buf:
                                    idx = buf.rindex(end_ch)
                                    # Skip decimal points: digit before AND digit after
                                    if end_ch == "." and idx > 0 and idx < len(buf) - 1:
                                        if buf[idx - 1].isdigit() and buf[idx + 1].isdigit():
                                            continue
                                    sentence = buf[:idx + 1].strip()
                                    sentence_buf[0] = buf[idx + 1:]
                                    # Clean SentencePiece ▁ markers to spaces
                                    clean = sentence.replace("\u2581", " ").strip()
                                    if len(clean) > 2 and time.monotonic() >= suppress_tts_until[0]:
                                        tts_queue.put_nowait(clean)
                                    break

                    elif kind == KIND_SPECIAL:
                        label = payload.decode("utf-8", errors="replace").strip()
                        if label.upper() not in SUPPRESS_TOKENS:
                            print()
                            log_info(uuid, f"<{C_MAGENTA}{label}{C_RESET}>")

            # ── Run all tasks concurrently ─────────────────────────────
            t_fs    = asyncio.create_task(fs_to_moshi(), name="fs_to_moshi")
            t_moshi = asyncio.create_task(moshi_to_fs(), name="moshi_to_fs")
            t_pump  = asyncio.create_task(audio_pump(), name="audio_pump")

            extra_tasks = []
            if TEST_TONE_MODE:
                extra_tasks.append(asyncio.create_task(test_tone_to_fs(), name="test_tone"))
            if PHRASE_BARGE_IN_ENABLED:
                extra_tasks.append(asyncio.create_task(phrase_barge_worker(), name="phrase_barge_worker"))
            if TTS_ENABLED and HAS_EDGE_TTS:
                extra_tasks.append(asyncio.create_task(tts_worker(), name="tts_worker"))
                extra_tasks.append(asyncio.create_task(text_flusher(), name="text_flusher"))
                log_info(uuid, f"{C_YELLOW}TTS playback enabled{C_RESET}  voice={TTS_VOICE}")

            core_tasks = [t_fs, t_moshi, t_pump]
            done, pending = await asyncio.wait(
                core_tasks, return_when=asyncio.FIRST_COMPLETED
            )
            for t in done:
                if t.exception():
                    log_error(uuid, f"Task '{t.get_name()}' crashed: {t.exception()}")
                else:
                    log_info(uuid, f"Task '{t.get_name()}' finished")
            # Signal TTS worker to stop
            if PHRASE_BARGE_IN_ENABLED:
                with suppress(asyncio.QueueFull):
                    phrase_audio_queue.put_nowait(None)
            if TTS_ENABLED and HAS_EDGE_TTS:
                tts_queue.put_nowait(None)
            for t in [t_fs, *extra_tasks, *pending]:
                t.cancel()
                with suppress(asyncio.CancelledError):
                    await t

    except websockets.exceptions.InvalidStatus as e:
        log_error(uuid, f"Moshi rejected: HTTP {e.response.status_code}")
    except Exception as e:
        log_error(uuid, f"{type(e).__name__}: {e}")
    finally:
        elapsed = time.monotonic() - call_start
        if debug_pcm is not None and len(debug_pcm) > 0:
            wav_path = f"/tmp/moshi_debug_{uuid}.wav"
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(FS_RETURN_RATE)
                wf.writeframes(bytes(debug_pcm))
            log_debug(uuid, f"Saved {len(debug_pcm):,} bytes to {wav_path}")
        print(f"{C_DIM}  {'=' * 70}{C_RESET}")
        log_call(
            f"{C_BOLD}{C_RED}Call ended{C_RESET}  "
            f"uuid={C_DIM}{uuid[:8]}{C_RESET}  "
            f"duration={C_BOLD}{elapsed:.1f}s{C_RESET}  "
            f"sent={C_GREEN}{frame_cnt[0]}{C_RESET}  "
            f"recv={C_CYAN}{frame_cnt[1]}{C_RESET}")
        print()


# ── Server ────────────────────────────────────────────────────────────

async def main():
    print()
    print(f"{C_BG_BLU}{C_BOLD}  BRIDGE  {C_RESET} {C_BOLD}FreeSWITCH <-> Moshi Audio Bridge{C_RESET}")
    print(f"{C_DIM}  {'─' * 60}{C_RESET}")
    print(f"  {C_GREEN}Listen:{C_RESET}  :{FS_PORT}")
    print(f"  {C_CYAN}Moshi:{C_RESET}   {_BASE_URL}")
    print(f"  {C_DIM}FS rate: {FS_RATE}Hz  Moshi rate: {MOSHI_RATE}Hz  Return: {FS_RETURN_RATE}Hz{C_RESET}")
    print(f"  {C_DIM}Big-endian: {FS_BIG_ENDIAN}  Test tone: {TEST_TONE_MODE}{C_RESET}")
    tts_status = f"{C_GREEN}ON{C_RESET} ({TTS_VOICE})" if TTS_ENABLED and HAS_EDGE_TTS else f"{C_RED}OFF{C_RESET}"
    print(f"  {C_YELLOW}TTS:{C_RESET}     {tts_status}")
    print(f"{C_DIM}  {'─' * 60}{C_RESET}")
    print(f"  {C_YELLOW}Waiting for calls...{C_RESET}")
    print()
    async with serve(bridge_connection, "0.0.0.0", FS_PORT):
        await asyncio.Future()


asyncio.run(main())
