"""
LiquidAI LFM2.5 Voice Server — Standalone launcher

Starts a WebSocket server that handles voice sessions using the LFM2.5-Audio-1.5B model.
Connects to the OmniCortex RAG pipeline for grounded answers when queries are detected.

Usage:
    python start_lfm.py

Env vars:
    VOICE_MODEL             Model ID (default: LiquidAI/LFM2.5-Audio-1.5B)
    LFM_HOST                Bind address (default: 0.0.0.0)
    LFM_PORT                Bind port (default: 9100)
    LFM_DEVICE              cuda / cpu (default: cuda)
    LFM_PRELOAD             Load model on startup instead of first request (default: true)
    OMNI_API_URL            OmniCortex API for RAG grounding (default: http://127.0.0.1:8000)
    API_BEARER_TOKEN        Auth token for OmniCortex API
    API_AGENT_ID            Default agent ID for RAG queries
"""
import asyncio
import io
import json
import logging
import os
import signal
import sys
import time

import numpy as np

# ---------------------------------------------------------------------------
#  Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s  %(levelname)-8s  [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("start_lfm")

# ---------------------------------------------------------------------------
#  Configuration
# ---------------------------------------------------------------------------
HOST        = os.getenv("LFM_HOST", "0.0.0.0").strip()
PORT        = int(os.getenv("LFM_PORT", "9100"))
DEVICE      = os.getenv("LFM_DEVICE", "cuda").strip()
PRELOAD     = os.getenv("LFM_PRELOAD", "true").strip().lower() == "true"
MODEL_ID    = os.getenv("VOICE_MODEL", "LiquidAI/LFM2.5-Audio-1.5B")

# OmniCortex RAG integration (optional — queries still work without it, just no grounding)
OMNI_API_URL    = os.getenv("OMNI_API_URL", "http://127.0.0.1:8000").strip().rstrip("/")
BEARER_TOKEN    = os.getenv("API_BEARER_TOKEN", "").strip()
AGENT_ID        = os.getenv("API_AGENT_ID", "").strip()
RAG_TIMEOUT     = float(os.getenv("LFM_RAG_TIMEOUT", "15"))

# Audio
GATEWAY_RATE    = int(os.getenv("GATEWAY_RATE", "16000"))
LFM_INPUT_RATE  = 16000
LFM_OUTPUT_RATE = 24000
VAD_SILENCE_MS  = int(os.getenv("LFM_VAD_SILENCE_MS", "600"))
VAD_THRESHOLD   = float(os.getenv("LFM_VAD_ENERGY_THRESHOLD", "0.01"))


# ---------------------------------------------------------------------------
#  Audio helpers (inline — no core dependency needed)
# ---------------------------------------------------------------------------
def pcm16_bytes_to_float32(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0

def float32_to_pcm16_bytes(arr: np.ndarray) -> bytes:
    return (np.clip(arr, -1.0, 1.0) * 32767).astype(np.int16).tobytes()

def resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate:
        return audio
    try:
        import torch
        import torchaudio.transforms as T
        resampler = T.Resample(src_rate, dst_rate)
        tensor = torch.from_numpy(audio).unsqueeze(0)
        return resampler(tensor).squeeze(0).numpy()
    except Exception:
        ratio = dst_rate / src_rate
        new_len = int(len(audio) * ratio)
        indices = np.linspace(0, len(audio) - 1, new_len)
        return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)

def simple_energy_vad(buffer: np.ndarray) -> bool:
    """Returns True if the tail of buffer has gone silent (utterance boundary)."""
    silence_samples = int(GATEWAY_RATE * VAD_SILENCE_MS / 1000)
    if buffer.size < silence_samples:
        return False
    tail = buffer[-silence_samples:]
    return float(np.mean(tail ** 2)) < VAD_THRESHOLD


# ---------------------------------------------------------------------------
#  LFM Engine wrapper
# ---------------------------------------------------------------------------
class LFMServer:
    def __init__(self):
        self.engine = None

    def load(self):
        from core.voice.liquid_voice import LiquidVoiceEngine
        logger.info("Loading LFM2.5 model: %s on %s ...", MODEL_ID, DEVICE)
        t0 = time.time()
        self.engine = LiquidVoiceEngine(model_id=MODEL_ID, device=DEVICE)
        self.engine.load()
        logger.info("LFM2.5 ready in %.1fs", time.time() - t0)

    def ensure_loaded(self):
        if self.engine is None or not self.engine._loaded:
            self.load()


# ---------------------------------------------------------------------------
#  Optional RAG grounding via OmniCortex /query
# ---------------------------------------------------------------------------
_rag_session = None

async def _get_rag_session():
    global _rag_session
    if _rag_session is None:
        import aiohttp
        _rag_session = aiohttp.ClientSession()
    return _rag_session

async def rag_query(question: str, agent_id: str = "") -> str | None:
    """Call OmniCortex /query for a grounded answer. Returns None on failure."""
    if not BEARER_TOKEN:
        return None
    try:
        session = await _get_rag_session()
        headers = {"Authorization": f"Bearer {BEARER_TOKEN}", "Content-Type": "application/json"}
        payload = {"question": question}
        if agent_id or AGENT_ID:
            payload["agent_id"] = agent_id or AGENT_ID
        async with session.post(
            f"{OMNI_API_URL}/query",
            json=payload,
            headers=headers,
            timeout=__import__("aiohttp").ClientTimeout(total=RAG_TIMEOUT),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("answer") or data.get("response") or data.get("text")
            logger.warning("RAG query returned %d", resp.status)
    except Exception as exc:
        logger.warning("RAG query failed: %s", exc)
    return None


# ---------------------------------------------------------------------------
#  Query intent detection
# ---------------------------------------------------------------------------
import re
_QUERY_RE = re.compile(
    r"\b(what|how|when|who|where|why|explain|tell me|describe|can you|could you|is there|are there)\b",
    re.IGNORECASE,
)

def is_query(text: str) -> bool:
    return bool(_QUERY_RE.search(text)) or text.rstrip().endswith("?")


# ---------------------------------------------------------------------------
#  WebSocket handler
# ---------------------------------------------------------------------------
async def handle_session(ws, path=None):
    """Handle one voice session over WebSocket."""
    import io as _io

    peer = ws.remote_address
    logger.info("New session from %s", peer)

    loop = asyncio.get_running_loop()
    lfm.ensure_loaded()
    engine = lfm.engine

    audio_buffer: list[np.ndarray] = []
    conversation_history: list[tuple] = []

    try:
        await ws.send(json.dumps({"type": "session", "status": "ready", "model": MODEL_ID, "device": DEVICE}))

        async for message in ws:
            # --- Text control frames ---
            if isinstance(message, str):
                try:
                    msg = json.loads(message)
                    if msg.get("type") == "control" and msg.get("action") == "stop":
                        break
                except (json.JSONDecodeError, TypeError):
                    pass
                continue

            # --- Binary audio (PCM16 mono 8kHz) ---
            if not isinstance(message, (bytes, bytearray)):
                continue
            if not message:
                continue

            chunk = pcm16_bytes_to_float32(message)
            audio_buffer.append(chunk)

            full = np.concatenate(audio_buffer)
            if not simple_energy_vad(full):
                continue

            # Utterance boundary detected
            if full.size == 0:
                audio_buffer.clear()
                continue

            await ws.send(json.dumps({"type": "status", "status": "thinking"}))
            audio_buffer.clear()

            # 1. Resample 8k -> 16k and wrap as WAV bytes for LFM
            pcm_16k = resample(full, GATEWAY_RATE, LFM_INPUT_RATE)
            wav_buf = _io.BytesIO()
            import wave
            with wave.open(wav_buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(LFM_INPUT_RATE)
                wf.writeframes(float32_to_pcm16_bytes(pcm_16k))
            wav_bytes = wav_buf.getvalue()

            # 2. STT via LFM2.5
            try:
                transcript = await loop.run_in_executor(None, engine.speech_to_text, wav_bytes)
                transcript = (transcript or "").strip()
            except Exception as exc:
                logger.error("STT failed: %s", exc)
                await ws.send(json.dumps({"type": "error", "message": "Transcription failed"}))
                await ws.send(json.dumps({"type": "status", "status": "listening"}))
                continue

            if not transcript:
                await ws.send(json.dumps({"type": "status", "status": "listening"}))
                continue

            await ws.send(json.dumps({"type": "transcript", "text": transcript, "final": True}))
            logger.info("Transcript: %s", transcript[:120])

            # 3. Generate answer
            answer = ""
            if is_query(transcript):
                # Try RAG grounding
                grounded = await rag_query(transcript)
                if grounded:
                    answer = grounded
                    logger.info("RAG answer: %s", answer[:120])

            if not answer:
                # Conversational response via LFM2.5 speech-to-speech
                try:
                    response = await loop.run_in_executor(
                        None,
                        lambda: engine.transcribe_and_respond(
                            wav_bytes,
                            system_prompt="You are a helpful assistant. Respond with interleaved text and audio.",
                            conversation_history=conversation_history[-10:],
                        ),
                    )
                    answer = response.text if hasattr(response, "text") else str(response or "")
                except Exception as exc:
                    logger.error("LFM respond failed: %s", exc)
                    answer = ""

            if answer:
                await ws.send(json.dumps({"type": "answer", "text": answer}))
                conversation_history.append(("user", transcript))
                conversation_history.append(("assistant", answer))

            # 4. TTS via LFM2.5
            await ws.send(json.dumps({"type": "status", "status": "speaking"}))
            if answer:
                try:
                    tts_wav = await loop.run_in_executor(None, engine.text_to_speech, answer)
                    if tts_wav:
                        # tts_wav is WAV bytes at 24kHz — extract PCM, resample, send
                        tts_buf = _io.BytesIO(tts_wav)
                        import torchaudio
                        waveform, sr = torchaudio.load(tts_buf)
                        tts_float = waveform.squeeze(0).numpy()
                        gateway_audio = resample(tts_float, sr, GATEWAY_RATE)
                        await ws.send(float32_to_pcm16_bytes(gateway_audio))
                except Exception as exc:
                    logger.warning("TTS failed: %s", exc)

            await ws.send(json.dumps({"type": "status", "status": "listening"}))

    except Exception as exc:
        if "closed" not in str(exc).lower():
            logger.error("Session error: %s", exc)
    finally:
        logger.info("Session ended for %s", peer)


# ---------------------------------------------------------------------------
#  Main
# ---------------------------------------------------------------------------
lfm = LFMServer()

API_KEY = os.getenv("RUNPOD_API_KEY", "").strip()

async def _process_request(path, headers):
    """HTTP health endpoint + API key auth."""
    if path == "/health":
        body = json.dumps({
            "status": "ok",
            "model": MODEL_ID,
            "device": DEVICE,
            "loaded": lfm.engine is not None and lfm.engine._loaded,
        }).encode()
        return (200, [("Content-Type", "application/json")], body)

    # API key auth (skip if no key configured)
    if API_KEY:
        from urllib.parse import urlparse, parse_qs
        key = headers.get("x-api-key", "") or headers.get("authorization", "").removeprefix("Bearer ").strip()
        token = parse_qs(urlparse(path).query).get("token", [""])[0]
        if key != API_KEY and token != API_KEY:
            return (401, [], b"Unauthorized\n")
    return None


async def main():
    import websockets

    if PRELOAD:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lfm.load)

    server = await websockets.serve(
        handle_session,
        HOST,
        PORT,
        ping_interval=None,
        max_size=8 * 1024 * 1024,
        process_request=_process_request,
    )

    logger.info("=" * 55)
    logger.info("  LFM2.5 Voice Server  STARTED")
    logger.info("  Listening  : ws://%s:%s", HOST, PORT)
    logger.info("  Model      : %s", MODEL_ID)
    logger.info("  Device     : %s", DEVICE)
    logger.info("  Preloaded  : %s", "yes" if PRELOAD else "no (lazy)")
    logger.info("  RAG API    : %s", OMNI_API_URL if BEARER_TOKEN else "(disabled — no API_BEARER_TOKEN)")
    logger.info("  Agent ID   : %s", AGENT_ID or "(none)")
    logger.info("=" * 55)

    # Graceful shutdown
    stop = asyncio.Event()

    def _signal_handler():
        logger.info("Shutting down...")
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows — signal handlers not supported in asyncio on Windows
            pass

    try:
        await stop.wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        await server.wait_closed()
        # Cleanup RAG session
        global _rag_session
        if _rag_session:
            await _rag_session.close()
        logger.info("Server stopped.")


if __name__ == "__main__":
    asyncio.run(main())
