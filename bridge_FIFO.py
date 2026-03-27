"""
bridge_FIFO.py -- Self-contained FreeSWITCH <-> Moshi audio bridge.

FreeSWITCH  --L16/16kHz-->  bridge.py  --kind=1+OggOpus/24kHz-->  Moshi (8998)
FreeSWITCH  <--L16/16kHz--  bridge.py  <--kind=1+OggOpus/24kHz--  Moshi (8998)

Uses opuslib + minimal Ogg container. No sphn dependency.
Sends continuous audio (real or silence) so Moshi's pipeline stays active.

CHANGE LOG:
- REMOVED: fs_ws.send() for Moshi audio (broken in mod_audio_stream)
- ADDED:   FIFO pipe + uuid_displace for real audio injection to caller
- TTS:     Still works as fallback (kept as-is)
"""

import asyncio
import json
import os
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
    print(f"{C_YELLOW}  TXT{C_RESET}  {C_DIM}{_ts()}{C_RESET}  {C_DIM}[{uuid[:8]}]{C_RESET} {C_YELLOW}{text}{C_RESET}", end="", flush=True)

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

def log_pipe(uuid, msg):
    print(f"{C_CYAN}{C_BOLD} PIPE{C_RESET}  {C_DIM}{_ts()}{C_RESET}  {C_DIM}[{uuid[:8]}]{C_RESET} {msg}")

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
FS_PORT            = 8001
API_KEY            = "b6f3b11e-64a5-49c7-9a90-54dd5a4cd482"
_BASE_URL          = "wss://qxpksbv6g9k06w-8998.proxy.runpod.net/api/chat"
_TEXT_PROMPT       = "You are a helpful voice assistant. Be concise and friendly."
MOSHI_URL          = f"{_BASE_URL}?text_prompt={quote(_TEXT_PROMPT)}"

FS_RATE            = 16000   # FreeSWITCH captures caller audio at this rate
FS_RETURN_RATE     = 8000    # Rate for audio injected back to caller via FIFO
FS_BIG_ENDIAN      = False
TEST_TONE_MODE     = False
MOSHI_RATE         = 24000
OPUS_FRAME_MS      = 20
OPUS_FRAME_SAMPLES = MOSHI_RATE * OPUS_FRAME_MS // 1000   # 480
OPUS_48K_FRAME     = 48000 * OPUS_FRAME_MS // 1000        # 960
MAX_DECODE_SAMPLES = MOSHI_RATE * 120 // 1000             # 2880

KIND_HANDSHAKE = 0x00
KIND_AUDIO     = 0x01
KIND_TEXT      = 0x02
KIND_SPECIAL   = 0x03

SUPPRESS_TOKENS = {"PAD", "EPAD"}

# ── FIFO Pipe Config ────────────────────────────────────────────────
FIFO_DIR         = "/tmp/moshi_pipes"
USE_FIFO         = True
FIFO_SAMPLE_RATE = 8000

# ── TTS Config (fallback) ──────────────────────────────────────────
TTS_ENABLED = True
TTS_VOICE   = "en-US-AriaNeural"
TTS_DIR     = "/tmp/bridge_tts"
FS_CLI      = "/usr/local/freeswitch/bin/fs_cli"


# ── Ogg CRC-32 ──────────────────────────────────────────────────────

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
        self._buf        = bytearray()
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
            seg_table     = self._buf[27:header_end]
            page_data_len = sum(seg_table)
            page_end      = header_end + page_data_len
            if len(self._buf) < page_end:
                break
            self._pages_seen += 1
            if self._pages_seen > 2:
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
        self._serial   = 0x4272696E
        self._page_seq = 0
        self._granule  = 0
        self._sr       = sample_rate
        self._ch       = channels
        self._started  = False

    def _page(self, payload: bytes, granule: int, flags: int = 0) -> bytes:
        segs = []
        rem  = len(payload)
        while rem >= 255:
            segs.append(255)
            rem -= 255
        segs.append(rem)
        buf = bytearray(27 + len(segs) + len(payload))
        struct.pack_into("<4sBBqIIIB", buf, 0,
                         b"OggS", 0, flags, granule,
                         self._serial, self._page_seq, 0, len(segs))
        buf[27:27 + len(segs)] = bytes(segs)
        buf[27 + len(segs):]   = payload
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
            tags   = struct.pack("<8sI", b"OpusTags", len(vendor)) + vendor + struct.pack("<I", 0)
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
    idx   = np.linspace(0, len(pcm) - 1, n_out)
    left  = np.floor(idx).astype(int)
    right = np.clip(left + 1, 0, len(pcm) - 1)
    frac  = (idx - left).astype(np.float32)
    return (pcm[left] * (1.0 - frac) + pcm[right] * frac).astype(np.float32)

def pcm16_to_f32(data, big_endian=False):
    dtype = ">i2" if big_endian else "<i2"
    return np.frombuffer(data, dtype=dtype).astype(np.float32) / 32768.0

def f32_to_pcm16(pcm, big_endian=False):
    dtype = ">i2" if big_endian else "<i2"
    return (np.clip(pcm, -1.0, 1.0) * 32767.0).astype(dtype).tobytes()


# ── FIFO Pipe helpers ────────────────────────────────────────────────

def make_fifo(uuid: str) -> str:
    os.makedirs(FIFO_DIR, exist_ok=True)
    pipe_path = f"{FIFO_DIR}/moshi_{uuid}.raw"
    if os.path.exists(pipe_path):
        os.unlink(pipe_path)
    os.mkfifo(pipe_path)
    return pipe_path


async def start_displace(uuid: str, pipe_path: str) -> bool:
    cmd  = f"uuid_displace {uuid} start {pipe_path} 0 mux"
    proc = await asyncio.create_subprocess_exec(
        FS_CLI, "-x", cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    result   = out.decode().strip()
    if "+OK" in result or result == "":
        log_pipe(uuid, f"{C_GREEN}uuid_displace started{C_RESET}  pipe={C_DIM}{pipe_path}{C_RESET}")
        return True
    else:
        log_error(uuid, f"uuid_displace failed: {result} | {err.decode().strip()}")
        return False


async def stop_displace(uuid: str, pipe_path: str) -> None:
    try:
        cmd  = f"uuid_displace {uuid} stop {pipe_path}"
        proc = await asyncio.create_subprocess_exec(
            FS_CLI, "-x", cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
        log_pipe(uuid, f"{C_DIM}uuid_displace stopped{C_RESET}")
    except Exception as e:
        log_error(uuid, f"stop_displace: {e}")
    finally:
        if os.path.exists(pipe_path):
            with suppress(OSError):
                os.unlink(pipe_path)
            log_pipe(uuid, f"{C_DIM}FIFO file deleted{C_RESET}")


# ── Per-call handler ──────────────────────────────────────────────────

async def bridge_connection(fs_ws):
    path       = getattr(fs_ws.request, "path", "/")
    uuid       = path.split("/")[-1] or "unknown"
    call_start = time.monotonic()

    print()
    log_call(f"{C_BOLD}{C_GREEN}New call{C_RESET}  uuid={C_BOLD}{uuid}{C_RESET}")
    print(f"{C_DIM}  {'=' * 70}{C_RESET}")

    encoder    = opuslib.Encoder(MOSHI_RATE, 1, opuslib.APPLICATION_VOIP)
    decoder    = opuslib.Decoder(MOSHI_RATE, 1)
    ogg_mux    = OggMuxer(MOSHI_RATE)
    ogg_demux  = OggDemuxer()
    pcm_buf    = np.array([], dtype=np.float32)
    hs_event   = asyncio.Event()
    last_fs_send = [0.0]           # monotonic time of last fs_to_moshi send
    frame_cnt  = [0, 0]
    debug_pcm  = bytearray()

    tts_queue      = asyncio.Queue()
    sentence_buf   = [""]
    last_text_time = [0.0]

    # FIFO state
    pipe_path  = None
    pipe_fd    = None
    pipe_ready = asyncio.Event()

    try:
        async with websockets.connect(
            MOSHI_URL,
            extra_headers={"x-api-key": API_KEY},
            max_size=10 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=30,
        ) as moshi_ws:
            log_info(uuid, f"{C_GREEN}Connected to Moshi{C_RESET}  url={C_DIM}{_BASE_URL}{C_RESET}")

            def encode_and_wrap(pcm_f32_24k):
                pcm16    = f32_to_pcm16(pcm_f32_24k)
                opus_pkt = encoder.encode(pcm16, OPUS_FRAME_SAMPLES)
                return bytes([KIND_AUDIO]) + ogg_mux.encode(opus_pkt)

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

            # ── Silence pump — keeps Moshi pipeline alive ───────────
            async def audio_pump() -> None:
                await hs_event.wait()
                log_pump(uuid, "Started (feeding silence to Moshi)")
                silence = np.zeros(OPUS_FRAME_SAMPLES, dtype=np.float32)
                t0   = time.monotonic()
                tick = 0
                while True:
                    tick += 1
                    now = time.monotonic()
                    # Only skip if fs_to_moshi sent a frame very recently (<25ms)
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
                        log_pump(uuid, f"sent={frame_cnt[0]}  recv={frame_cnt[1]}  elapsed={elapsed:.1f}s")
                    next_t = t0 + tick * (OPUS_FRAME_MS / 1000.0)
                    delay  = next_t - time.monotonic()
                    if delay > 0:
                        await asyncio.sleep(delay)

            # ── FreeSWITCH -> Moshi ─────────────────────────────────
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
                    if fs_frames <= 3:
                        log_fs_in(uuid, f"PCM #{fs_frames}: {len(data)}B")
                    await send_pcm(data)

            # ── Create FIFO and start uuid_displace ─────────────────
            async def setup_fifo_pipe() -> None:
                nonlocal pipe_path, pipe_fd

                await hs_event.wait()
                log_pipe(uuid, "Setting up FIFO pipe...")

                pipe_path = make_fifo(uuid)
                log_pipe(uuid, f"FIFO created: {C_DIM}{pipe_path}{C_RESET}")

                ok = await start_displace(uuid, pipe_path)
                if not ok:
                    log_error(uuid, "uuid_displace failed — FIFO disabled for this call")
                    return

                # open() blocks until FS opens the other end — run in thread
                loop = asyncio.get_event_loop()
                try:
                    pipe_fd = await loop.run_in_executor(
                        None,
                        lambda: open(pipe_path, 'wb', buffering=0)
                    )
                    log_pipe(uuid, f"{C_GREEN}FIFO pipe OPEN — Moshi audio will reach the caller{C_RESET}")
                    pipe_ready.set()
                except OSError as e:
                    log_error(uuid, f"FIFO open failed: {e}")

            # ── TTS worker ──────────────────────────────────────────
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
                    try:
                        log_tts(uuid, f"Gen #{seq}: \"{text}\"")
                        ts_ms    = int(time.time() * 1000)
                        mp3_path = f"{TTS_DIR}/{uuid[:8]}_{ts_ms}.mp3"
                        wav_path = mp3_path.replace(".mp3", ".wav")

                        comm = edge_tts.Communicate(text, TTS_VOICE)
                        await comm.save(mp3_path)

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
                        if mp3_path and os.path.exists(mp3_path):
                            os.unlink(mp3_path)
                            mp3_path = None

                        if not os.path.exists(wav_path):
                            log_error(uuid, "TTS: WAV not created")
                            continue

                        wav_size = os.path.getsize(wav_path)
                        dur      = wav_size / (8000 * 2)
                        log_tts(uuid, f"Play #{seq}: {wav_size}B ({dur:.1f}s)")

                        cmd  = f"uuid_broadcast {uuid} {wav_path} aleg"
                        proc = await asyncio.create_subprocess_exec(
                            FS_CLI, "-x", cmd,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        out, _ = await proc.communicate()
                        result  = out.decode().strip()
                        if "+OK" in result:
                            log_tts(uuid, f"#{seq} broadcast started")
                        else:
                            log_error(uuid, f"broadcast: {result}")

                        await asyncio.sleep(dur + 0.5)

                    except Exception as e:
                        log_error(uuid, f"TTS: {e}")
                    finally:
                        for p in (mp3_path, wav_path):
                            if p and os.path.exists(p):
                                with suppress(OSError):
                                    os.unlink(p)
                        tts_queue.task_done()

            # ── Text flusher ────────────────────────────────────────
            async def text_flusher() -> None:
                if not TTS_ENABLED:
                    return
                while True:
                    await asyncio.sleep(1.0)
                    buf = sentence_buf[0].strip()
                    if buf and len(buf) > 2 and time.monotonic() - last_text_time[0] > 1.5:
                        sentence_buf[0] = ""
                        clean = buf.replace("\u2581", " ").strip()
                        if clean:
                            tts_queue.put_nowait(clean)
                            log_tts(uuid, f"Flushed: \"{clean}\"")

            # ── Moshi -> FIFO pipe ──────────────────────────────────
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
                                pcm_f32     = pcm16_to_f32(pcm16_bytes)
                                resampled   = resample(pcm_f32, MOSHI_RATE, FS_RETURN_RATE)
                                rms = float(np.sqrt(np.mean(resampled ** 2))) if len(resampled) > 0 else 0.0
                                out_pcm = f32_to_pcm16(resampled, big_endian=FS_BIG_ENDIAN)
                                debug_pcm.extend(f32_to_pcm16(resampled))

                                frame_cnt[1] += 1
                                if frame_cnt[1] <= 10 or frame_cnt[1] % 250 == 0:
                                    log_moshi_out(uuid,
                                        f"frame {C_BOLD}#{frame_cnt[1]:<5}{C_RESET} "
                                        f"rms={rms:.4f} {_bar(rms)} "
                                        f"{len(out_pcm)}B")

                                # Write to FIFO -> FS reads via uuid_displace -> caller hears
                                if USE_FIFO and pipe_fd is not None:
                                    try:
                                        pipe_fd.write(out_pcm)
                                    except (BrokenPipeError, OSError) as e:
                                        log_error(uuid, f"Pipe write error: {e}")
                                        return
                                else:
                                    if frame_cnt[1] % 100 == 0:
                                        log_pipe(uuid, f"{C_YELLOW}Pipe not ready, skipping frame{C_RESET}")

                            except opuslib.exceptions.OpusError as e:
                                log_error(uuid, f"Opus decode: {e}")

                    elif kind == KIND_TEXT:
                        token = payload.decode("utf-8", errors="replace")
                        log_text(uuid, token)
                        if TTS_ENABLED and HAS_EDGE_TTS:
                            sentence_buf[0] += token
                            last_text_time[0] = time.monotonic()
                            for end_ch in ".!?\n":
                                if end_ch in sentence_buf[0]:
                                    idx      = sentence_buf[0].rindex(end_ch)
                                    sentence = sentence_buf[0][:idx + 1].strip()
                                    sentence_buf[0] = sentence_buf[0][idx + 1:]
                                    clean    = sentence.replace("\u2581", " ").strip()
                                    if len(clean) > 2:
                                        tts_queue.put_nowait(clean)
                                    break

                    elif kind == KIND_SPECIAL:
                        label = payload.decode("utf-8", errors="replace").strip()
                        if label.upper() not in SUPPRESS_TOKENS:
                            print()
                            log_info(uuid, f"<{C_MAGENTA}{label}{C_RESET}>")

            # ── Launch all tasks ────────────────────────────────────
            t_fs    = asyncio.create_task(fs_to_moshi(),     name="fs_to_moshi")
            t_moshi = asyncio.create_task(moshi_to_fs(),     name="moshi_to_fs")
            t_pump  = asyncio.create_task(audio_pump(),      name="audio_pump")

            extra_tasks = []
            if USE_FIFO:
                extra_tasks.append(asyncio.create_task(setup_fifo_pipe(), name="fifo_setup"))
                log_info(uuid, f"{C_CYAN}FIFO audio injection enabled{C_RESET}")
            if TTS_ENABLED and HAS_EDGE_TTS:
                extra_tasks.append(asyncio.create_task(tts_worker(),   name="tts_worker"))
                extra_tasks.append(asyncio.create_task(text_flusher(), name="text_flusher"))
                log_info(uuid, f"{C_YELLOW}TTS playback enabled{C_RESET}  voice={TTS_VOICE}")

            core_tasks    = [t_moshi, t_pump]
            done, pending = await asyncio.wait(
                core_tasks, return_when=asyncio.FIRST_COMPLETED
            )
            for t in done:
                if t.exception():
                    log_error(uuid, f"Task '{t.get_name()}' crashed: {t.exception()}")
                else:
                    log_info(uuid, f"Task '{t.get_name()}' finished")

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

        if pipe_fd is not None:
            with suppress(OSError):
                pipe_fd.close()

        if pipe_path is not None:
            await stop_displace(uuid, pipe_path)

        if len(debug_pcm) > 0:
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
    print(f"{C_BG_BLU}{C_BOLD}  BRIDGE  {C_RESET} {C_BOLD}FreeSWITCH <-> Moshi Audio Bridge (FIFO){C_RESET}")
    print(f"{C_DIM}  {'─' * 60}{C_RESET}")
    print(f"  {C_GREEN}Listen:{C_RESET}  :{FS_PORT}")
    print(f"  {C_CYAN}Moshi:{C_RESET}   {_BASE_URL}")
    print(f"  {C_DIM}FS rate: {FS_RATE}Hz  Moshi rate: {MOSHI_RATE}Hz  Return: {FS_RETURN_RATE}Hz{C_RESET}")
    print(f"  {C_DIM}Big-endian: {FS_BIG_ENDIAN}  Test tone: {TEST_TONE_MODE}{C_RESET}")
    fifo_status = f"{C_GREEN}ON{C_RESET}  (path: {FIFO_DIR}/moshi_<uuid>.raw)" if USE_FIFO else f"{C_RED}OFF{C_RESET}"
    print(f"  {C_CYAN}FIFO:{C_RESET}    {fifo_status}")
    tts_status = f"{C_GREEN}ON{C_RESET} ({TTS_VOICE})" if TTS_ENABLED and HAS_EDGE_TTS else f"{C_RED}OFF{C_RESET}"
    print(f"  {C_YELLOW}TTS:{C_RESET}     {tts_status}")
    print(f"{C_DIM}  {'─' * 60}{C_RESET}")
    print(f"  {C_YELLOW}Waiting for calls...{C_RESET}")
    print()
    async with serve(bridge_connection, "0.0.0.0", FS_PORT):
        await asyncio.Future()


asyncio.run(main())
