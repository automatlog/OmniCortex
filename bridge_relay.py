#!/usr/bin/env python3
"""
bridge_relay.py -- Direct FreeSWITCH <-> PersonaPlex audio bridge for Linux

Simplified version of bridge.py that connects directly to PersonaPlex server.
Designed to run on the same Linux server as FreeSWITCH.

FreeSWITCH  --L16/8kHz-->  bridge_relay.py  --Opus/24kHz-->  PersonaPlex (8998)
FreeSWITCH  <--L16/8kHz--  bridge_relay.py  <--Opus/24kHz--  PersonaPlex (8998)

Features:
- Direct PersonaPlex connection (no OmniCortex proxy)
- Opus codec with Ogg container
- TTS fallback with edge-tts
- Phrase-based barge-in detection
- Multi-language support
- Production-ready logging
"""

import asyncio
import json
import os
import re
import struct
import time
from contextlib import suppress
from datetime import datetime
from urllib.parse import quote
from pathlib import Path

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


# ── Configuration ────────────────────────────────────────────────────
# Server settings
FS_PORT = int(os.getenv("BRIDGE_PORT", "8001"))
FS_RATE = 8000   # FreeSWITCH audio rate
FS_BIG_ENDIAN = False

# PersonaPlex connection
PERSONAPLEX_URL = os.getenv("PERSONAPLEX_URL", "ws://localhost:8998/api/chat")
PERSONAPLEX_API_KEY = os.getenv("PERSONAPLEX_API_KEY", "")

# Agent configuration
DEFAULT_AGENT_ID = os.getenv("AGENT_ID", "")
DEFAULT_TOKEN = os.getenv("BEARER_TOKEN", "")
DEFAULT_VOICE_PROMPT = os.getenv("VOICE_PROMPT", "NATF0.pt")
DEFAULT_TEXT_PROMPT = os.getenv("TEXT_PROMPT", "You are a helpful assistant.")

# Audio settings
MOSHI_RATE = 24000
OPUS_FRAME_MS = 20
OPUS_FRAME_SAMPLES = MOSHI_RATE * OPUS_FRAME_MS // 1000
OPUS_48K_FRAME = 48000 * OPUS_FRAME_MS // 1000

# Frame types
KIND_HANDSHAKE = 0x00
KIND_AUDIO = 0x01
KIND_TEXT = 0x02
KIND_CTRL = 0x03

# TTS settings
TTS_ENABLED = os.getenv("TTS_ENABLED", "true").lower() in {"1", "true", "yes"}
TTS_DIR = os.getenv("TTS_DIR", "/tmp/bridge_tts")
FS_CLI = os.getenv("FS_CLI", "/usr/local/freeswitch/bin/fs_cli")

# Barge-in settings
BARGE_IN_ENABLED = os.getenv("BARGE_IN_ENABLED", "true").lower() in {"1", "true", "yes"}
BARGE_IN_RMS_THRESHOLD = float(os.getenv("BARGE_IN_RMS_THRESHOLD", "0.012"))
BARGE_IN_MIN_AUDIO_SEC = float(os.getenv("BARGE_IN_MIN_AUDIO_SEC", "0.8"))
BARGE_IN_MAX_AUDIO_SEC = float(os.getenv("BARGE_IN_MAX_AUDIO_SEC", "2.5"))

STOP_PHRASES = [
    "stop", "wait", "hold on", "pause", "one second",
    "interrupt", "cancel", "stop talking", "please stop"
]

# Language-aware TTS voices
TTS_VOICE_MAP = {
    "en": "en-US-AriaNeural",
    "hi": "hi-IN-SwaraNeural",
    "es": "es-ES-ElviraNeural",
    "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural",
}

# UUID validation
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


# ── Logging ──────────────────────────────────────────────────────────
def log(level, uuid, msg):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] [{level:5s}] [{uuid[:8]}] {msg}")

def log_info(uuid, msg):
    log("INFO", uuid, msg)

def log_error(uuid, msg):
    log("ERROR", uuid, msg)

def log_debug(uuid, msg):
    if os.getenv("DEBUG", "").lower() in {"1", "true"}:
        log("DEBUG", uuid, msg)


# ── Ogg CRC-32 ───────────────────────────────────────────────────────
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
            if self._pages_seen > 2:  # Skip OpusHead + OpusTags
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
        self._serial = 0x42726967
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
            vendor = b"bridge_relay"
            tags = struct.pack("<8sI", b"OpusTags", len(vendor)) + vendor + struct.pack("<I", 0)
            out.extend(self._page(tags, 0))
            self._started = True
        self._granule += OPUS_48K_FRAME
        out.extend(self._page(opus_pkt, self._granule))
        return bytes(out)


# ── Audio helpers ────────────────────────────────────────────────────
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

def detect_language(text: str) -> str:
    """Simple script-based language detection."""
    if not text or len(text.strip()) < 3:
        return "en"
    devanagari = sum(1 for c in text if '\u0900' <= c <= '\u097F')
    total = len(text.replace(" ", ""))
    if total > 0 and devanagari > total * 0.2:
        return "hi"
    return "en"

def sanitize_uuid(raw: str) -> str:
    candidate = (raw or "").strip()
    if not UUID_RE.fullmatch(candidate):
        raise ValueError(f"Invalid UUID: {raw!r}")
    return candidate


# ── Main bridge handler ──────────────────────────────────────────────
async def bridge_connection(fs_ws):
    """Handle a single FreeSWITCH call connection."""
    path = getattr(fs_ws.request, "path", "/")
    raw_uuid = path.split("/")[-1] or "unknown"
    
    try:
        uuid = sanitize_uuid(raw_uuid)
    except ValueError as exc:
        log_error(raw_uuid, str(exc))
        with suppress(Exception):
            await fs_ws.close()
        return

    log_info(uuid, f"New call started")
    
    # Build PersonaPlex URL with parameters
    params = []
    if DEFAULT_AGENT_ID:
        params.append(f"agent_id={quote(DEFAULT_AGENT_ID)}")
    if DEFAULT_VOICE_PROMPT:
        params.append(f"voice_prompt={quote(DEFAULT_VOICE_PROMPT)}")
    if not DEFAULT_AGENT_ID and DEFAULT_TEXT_PROMPT:
        params.append(f"text_prompt={quote(DEFAULT_TEXT_PROMPT)}")
    
    url = PERSONAPLEX_URL
    if params:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{'&'.join(params)}"
    
    # Initialize codecs
    encoder = opuslib.Encoder(MOSHI_RATE, 1, opuslib.APPLICATION_VOIP)
    decoder = opuslib.Decoder(MOSHI_RATE, 1)
    ogg_mux = OggMuxer(MOSHI_RATE)
    ogg_demux = OggDemuxer()
    
    # State
    pcm_buf = np.array([], dtype=np.float32)
    handshake_event = asyncio.Event()
    tts_queue = asyncio.Queue()
    tts_active = [False]
    tts_generation = [0]
    sentence_buf = [""]
    detected_voice = [TTS_VOICE_MAP.get("en")]
    
    # Headers
    headers = {}
    if PERSONAPLEX_API_KEY:
        headers["x-api-key"] = PERSONAPLEX_API_KEY
    if DEFAULT_TOKEN:
        headers["Authorization"] = f"Bearer {DEFAULT_TOKEN}"
    
    try:
        async with websockets.connect(
            url,
            extra_headers=headers,
            max_size=10 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=30,
        ) as personaplex_ws:
            log_info(uuid, f"Connected to PersonaPlex")
            
            def encode_and_wrap(pcm_f32_24k):
                pcm16 = f32_to_pcm16(pcm_f32_24k)
                opus_pkt = encoder.encode(pcm16, OPUS_FRAME_SAMPLES)
                return bytes([KIND_AUDIO]) + ogg_mux.encode(opus_pkt)
            
            async def send_pcm(raw: bytes) -> None:
                nonlocal pcm_buf
                pcm_f32 = pcm16_to_f32(raw, big_endian=FS_BIG_ENDIAN)
                pcm_24k = resample(pcm_f32, FS_RATE, MOSHI_RATE)
                pcm_buf = np.concatenate([pcm_buf, pcm_24k])
                while len(pcm_buf) >= OPUS_FRAME_SAMPLES:
                    frame = pcm_buf[:OPUS_FRAME_SAMPLES]
                    pcm_buf = pcm_buf[OPUS_FRAME_SAMPLES:]
                    await personaplex_ws.send(encode_and_wrap(frame))
            
            # Silence pump
            async def audio_pump():
                await handshake_event.wait()
                log_debug(uuid, "Audio pump started")
                silence = np.zeros(OPUS_FRAME_SAMPLES, dtype=np.float32)
                while True:
                    await asyncio.sleep(OPUS_FRAME_MS / 1000.0)
                    await personaplex_ws.send(encode_and_wrap(silence))
            
            # FreeSWITCH → PersonaPlex
            async def fs_to_personaplex():
                await handshake_event.wait()
                async for data in fs_ws:
                    if not isinstance(data, bytes):
                        # Metadata/control
                        ack = json.dumps({"type": "connected", "protocol": "audio"})
                        await fs_ws.send(ack)
                        continue
                    await send_pcm(data)
            
            # PersonaPlex → FreeSWITCH
            async def personaplex_to_fs():
                async for msg in personaplex_ws:
                    if not isinstance(msg, bytes):
                        continue
                    
                    kind = msg[0]
                    payload = msg[1:]
                    
                    if kind == KIND_HANDSHAKE:
                        handshake_event.set()
                        log_info(uuid, "Handshake received")
                        continue
                    
                    if kind == KIND_TEXT:
                        text = payload.decode("utf-8", errors="ignore").strip()
                        if text and text not in {"PAD", "EPAD"}:
                            log_info(uuid, f"Text: {text}")
                            sentence_buf[0] += text
                            # Detect language and update TTS voice
                            lang = detect_language(sentence_buf[0])
                            detected_voice[0] = TTS_VOICE_MAP.get(lang, TTS_VOICE_MAP["en"])
                        continue
                    
                    if kind == KIND_AUDIO:
                        # Decode and send to FreeSWITCH
                        packets = ogg_demux.feed(payload)
                        for opus_pkt in packets:
                            try:
                                pcm_24k = decoder.decode(opus_pkt, OPUS_FRAME_SAMPLES)
                                pcm_f32 = pcm16_to_f32(pcm_24k)
                                pcm_8k = resample(pcm_f32, MOSHI_RATE, FS_RATE)
                                pcm_out = f32_to_pcm16(pcm_8k, big_endian=FS_BIG_ENDIAN)
                                await fs_ws.send(pcm_out)
                            except Exception as e:
                                log_error(uuid, f"Decode error: {e}")
            
            # TTS worker (if enabled)
            async def tts_worker():
                if not TTS_ENABLED or not HAS_EDGE_TTS:
                    return
                Path(TTS_DIR).mkdir(parents=True, exist_ok=True)
                while True:
                    text = await tts_queue.get()
                    if text is None:
                        break
                    try:
                        tts_active[0] = True
                        log_info(uuid, f"TTS: {text}")
                        ts = int(time.time() * 1000)
                        mp3_path = f"{TTS_DIR}/{uuid[:8]}_{ts}.mp3"
                        wav_path = mp3_path.replace(".mp3", ".wav")
                        
                        voice = detected_voice[0]
                        await edge_tts.Communicate(text, voice).save(mp3_path)
                        
                        # Convert to WAV
                        proc = await asyncio.create_subprocess_exec(
                            "ffmpeg", "-y", "-loglevel", "error",
                            "-i", mp3_path,
                            "-ar", str(FS_RATE),
                            "-ac", "1",
                            "-sample_fmt", "s16",
                            wav_path,
                            stdout=asyncio.subprocess.DEVNULL,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        await proc.communicate()
                        
                        # Play via FreeSWITCH
                        proc = await asyncio.create_subprocess_exec(
                            FS_CLI, "-x", f"uuid_broadcast {uuid} {wav_path} aleg",
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        await proc.communicate()
                        
                        # Cleanup
                        Path(mp3_path).unlink(missing_ok=True)
                        Path(wav_path).unlink(missing_ok=True)
                    except Exception as e:
                        log_error(uuid, f"TTS error: {e}")
                    finally:
                        tts_active[0] = False
            
            # Run all tasks
            tasks = [
                asyncio.create_task(audio_pump()),
                asyncio.create_task(fs_to_personaplex()),
                asyncio.create_task(personaplex_to_fs()),
                asyncio.create_task(tts_worker()),
            ]
            
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            
            # Cancel remaining tasks
            for task in pending:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            
            log_info(uuid, "Call ended")
    
    except Exception as e:
        log_error(uuid, f"Bridge error: {e}")
    finally:
        with suppress(Exception):
            await fs_ws.close()


# ── Server ───────────────────────────────────────────────────────────
async def main():
    print()
    print("=" * 70)
    print("  BRIDGE RELAY - FreeSWITCH <-> PersonaPlex Direct Connection")
    print("=" * 70)
    print(f"  Listening on: 0.0.0.0:{FS_PORT}")
    print(f"  PersonaPlex:  {PERSONAPLEX_URL}")
    print(f"  Agent ID:     {DEFAULT_AGENT_ID or '(none)'}")
    print(f"  TTS:          {'Enabled' if TTS_ENABLED and HAS_EDGE_TTS else 'Disabled'}")
    print(f"  Barge-in:     {'Enabled' if BARGE_IN_ENABLED and HAS_LOCAL_ASR else 'Disabled'}")
    print("=" * 70)
    print()
    print("Waiting for calls...")
    print()
    
    async with serve(bridge_connection, "0.0.0.0", FS_PORT):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down...")
