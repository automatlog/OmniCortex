"""
Standalone LFM2.5-Audio Server

Runs LiquidAI LFM2.5-Audio-1.5B as a separate microservice.
OmniCortex connects to this via HTTP instead of loading the model in-process.

Usage:
    python lfm/serve_lfm.py                           # defaults: port 8099, cuda
    python lfm/serve_lfm.py --port 8099 --device cuda
    python lfm/serve_lfm.py --model LiquidAI/LFM2.5-Audio-1.5B --preload

Env vars (override CLI args):
    LFM_PORT=8099
    VOICE_MODEL=LiquidAI/LFM2.5-Audio-1.5B
    LFM_DEVICE=cuda
    LFM_PRELOAD=true
"""
import argparse
import logging
import os
import asyncio
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Disable hf_transfer if the package is missing — avoids hard crash during
# model download even when HF_HUB_ENABLE_HF_TRANSFER=1 is set in the env.
try:
    import hf_transfer  # noqa: F401
except ModuleNotFoundError:
    os.environ.pop("HF_HUB_ENABLE_HF_TRANSFER", None)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [LFM] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("serve_lfm")

# --- Global engine reference (loaded at startup or on first request) ---
_engine = None
_engine_config = None
_engine_error = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize LFM engine on application startup."""
    global _engine, _engine_config, _engine_error

    from core.voice.liquid_voice import LiquidVoiceEngine

    model = os.getenv("VOICE_MODEL", "LiquidAI/LFM2.5-Audio-1.5B")
    device = os.getenv("LFM_DEVICE", "cuda")
    max_instances = int(os.getenv("VOICE_MAX_INSTANCES", "8"))
    preload = os.getenv("LFM_PRELOAD", "false").lower() == "true"

    logger.info("Initializing LFM engine: model=%s device=%s preload=%s", model, device, preload)
    _engine_error = None

    _engine = LiquidVoiceEngine(
        model_id=model,
        device=device,
        max_instances=max_instances,
    )

    if preload:
        logger.info("Pre-loading LFM model on startup...")
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _engine.load)
            logger.info("LFM model ready")
        except Exception as exc:
            _engine_error = str(exc)
            logger.error("LFM preload failed: %s", exc)
    else:
        logger.info("LFM model will load on first request")

    _engine_config = {
        "model": model,
        "device": device,
        "max_instances": max_instances,
        "preload": preload,
    }

    yield  # application runs here


app = FastAPI(title="LFM2.5-Audio Server", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-LFM-Text", "X-LFM-Latency-Ms"],
)


def _get_engine():
    global _engine, _engine_error
    if _engine is None:
        raise HTTPException(status_code=503, detail="LFM engine not loaded yet")
    if _engine_error:
        raise HTTPException(status_code=503, detail=f"LFM engine unavailable: {_engine_error}")
    return _engine


async def _get_engine_async():
    """Get engine, loading it asynchronously if needed."""
    global _engine, _engine_error
    engine = _get_engine()
    if not engine._loaded:
        logger.info("Lazy-loading LFM model on first request...")
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, engine.load)
            _engine_error = None
        except Exception as exc:
            _engine_error = str(exc)
            logger.error("Lazy LFM load failed: %s", exc)
            raise HTTPException(status_code=503, detail=f"LFM engine unavailable: {_engine_error}") from exc
    return engine


# =========================================================================
# ENDPOINTS
# =========================================================================

@app.get("/health")
async def health():
    global _engine_error
    loaded = _engine is not None and _engine._loaded
    return {
        "status": "ok" if loaded else "warming",
        "model": _engine.model_id if _engine else None,
        "device": _engine.device if _engine else None,
        "loaded": loaded,
        "error": _engine_error,
    }


@app.post("/stt")
async def speech_to_text(audio: UploadFile = File(...)):
    """Transcribe audio (WAV/PCM16) to text."""
    engine = await _get_engine_async()
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio")

    t0 = time.perf_counter()
    try:
        # Run blocking STT in thread pool
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, engine.speech_to_text, audio_bytes)
    except Exception as e:
        logger.error("STT failed: %s", e)
        raise HTTPException(status_code=500, detail=f"STT failed: {e}")

    latency = (time.perf_counter() - t0) * 1000
    logger.info("STT %.0fms: %s", latency, text[:80] if text else "(empty)")
    return {"text": text or "", "latency_ms": round(latency, 1)}


@app.post("/tts")
async def text_to_speech(text: str = Form(...), max_new_tokens: int = Form(256)):
    """Convert text to speech. Returns WAV audio bytes."""
    engine = await _get_engine_async()
    if not text.strip():
        raise HTTPException(status_code=400, detail="Empty text")
    
    # Validate max_new_tokens to prevent resource exhaustion
    MAX_TOKENS_ALLOWED = 1024
    if max_new_tokens > MAX_TOKENS_ALLOWED:
        raise HTTPException(
            status_code=400,
            detail=f"max_new_tokens exceeds maximum allowed ({MAX_TOKENS_ALLOWED})"
        )

    t0 = time.perf_counter()
    try:
        # Run blocking TTS in thread pool
        loop = asyncio.get_event_loop()
        audio_bytes = await loop.run_in_executor(
            None,
            engine.text_to_speech,
            text,
            max_new_tokens
        )
    except Exception as e:
        logger.error("TTS failed: %s", e)
        raise HTTPException(status_code=500, detail=f"TTS failed: {e}")

    latency = (time.perf_counter() - t0) * 1000
    logger.info("TTS %.0fms: %d bytes for '%.40s'", latency, len(audio_bytes), text)
    return Response(content=audio_bytes, media_type="audio/wav")


@app.post("/respond")
async def transcribe_and_respond(
    audio: UploadFile = File(...),
    system_prompt: str = Form("You are a helpful assistant. Respond with interleaved text and audio."),
    max_new_tokens: int = Form(512),
    conversation_history: str = Form(None),
    audio_temperature: float = Form(1.0),
    audio_top_k: int = Form(4),
):
    """Full speech-to-speech: audio in, text + audio out."""
    if max_new_tokens > MAX_TOKENS_ALLOWED:
        return JSONResponse(
            status_code=400,
            content={"error": f"max_new_tokens ({max_new_tokens}) exceeds limit ({MAX_TOKENS_ALLOWED})"},
        )
    engine = await _get_engine_async()
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio")

    t0 = time.perf_counter()
    try:
        # Parse conversation history if provided
        conv_history = None
        if conversation_history:
            import json
            try:
                conv_history = json.loads(conversation_history)
            except (json.JSONDecodeError, ValueError) as e:
                import logging
                logging.warning("Failed to parse conversation_history: %s", e)
                return JSONResponse(
                    status_code=400,
                    content={"error": "Invalid conversation_history JSON format"},
                )
        
        # Run blocking transcribe_and_respond in thread pool
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: engine.transcribe_and_respond(
                audio_bytes,
                system_prompt=system_prompt,
                conversation_history=conv_history,
                max_new_tokens=max_new_tokens,
                audio_temperature=audio_temperature,
                audio_top_k=audio_top_k,
            )
        )
    except Exception as e:
        logger.error("Respond failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Respond failed: {e}")

    latency = (time.perf_counter() - t0) * 1000
    logger.info("Respond %.0fms: text='%.40s' audio=%dB", latency, response.text, len(response.audio_bytes))

    # Make X-LFM-Text header ASCII-safe and bounded
    text = (response.text or "")
    normalized = text.replace("\n", " ")[:500]
    ascii_safe = normalized.encode("ascii", "replace").decode("ascii")
    
    # Return text in header, audio in body
    return Response(
        content=response.audio_bytes,
        media_type="audio/wav",
        headers={
            "X-LFM-Text": ascii_safe,
            "X-LFM-Latency-Ms": str(round(latency, 1)),
        },
    )


# =========================================================================
# STARTUP
# =========================================================================

def main():
    parser = argparse.ArgumentParser(description="LFM2.5-Audio Standalone Server")
    parser.add_argument("--port", type=int, default=int(os.getenv("LFM_PORT", "8099")))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--model", default=os.getenv("VOICE_MODEL", "LiquidAI/LFM2.5-Audio-1.5B"))
    parser.add_argument("--device", default=os.getenv("LFM_DEVICE", "cuda"))
    parser.add_argument("--max-instances", type=int, default=int(os.getenv("VOICE_MAX_INSTANCES", "8")))
    parser.add_argument("--preload", action="store_true",
                        default=os.getenv("LFM_PRELOAD", "false").lower() == "true",
                        help="Load model immediately at startup instead of on first request")
    args = parser.parse_args()

    # Set environment variables from args so startup event can use them
    os.environ["VOICE_MODEL"] = args.model
    os.environ["LFM_DEVICE"] = args.device
    os.environ["VOICE_MAX_INSTANCES"] = str(args.max_instances)
    os.environ["LFM_PRELOAD"] = "true" if args.preload else "false"

    logger.info(
        "Starting LFM server on %s:%d  model=%s  device=%s  preload=%s",
        args.host, args.port, args.model, args.device, args.preload,
    )

    # uvicorn.run() will trigger startup events
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
