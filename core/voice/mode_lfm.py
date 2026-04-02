"""
Mode 2: LFM2.5 Interleaved — utterance-based voice processing using LiquidAI LFM2.5.

Pipeline per utterance:
  1. Receive audio chunks (8kHz PCM16), accumulate with VAD
  2. Resample 8kHz -> 16kHz, transcribe via LFM2.5
  3. Check if response is a query -> call process_question_voice() for grounded answer
  4. Feed grounded answer to LFM2.5 text_to_speech()
  5. Resample output -> 8kHz, send back
"""
import asyncio
import json
import logging
import re
from typing import List

import numpy as np
from starlette.websockets import WebSocket, WebSocketDisconnect

from core.config import VOICE_VAD_SILENCE_MS, VOICE_VAD_ENERGY_THRESHOLD
from core.voice.voice_protocol import (
    VoiceSession, SessionState,
    GATEWAY_RATE, LFM_INPUT_RATE,
    MSG_TRANSCRIPT, MSG_ANSWER, MSG_STATUS, MSG_ERROR,
)
from core.voice.resampler import Resampler, pcm16_bytes_to_float32, float32_to_pcm16_bytes

logger = logging.getLogger(__name__)

_QUERY_PATTERN = re.compile(
    r"\b(what|how|when|who|where|why|explain|tell me|describe|can you|could you|is there|are there)\b",
    re.IGNORECASE,
)


def _is_query_intent(text: str) -> bool:
    """Heuristic: does the transcript look like a question that needs RAG grounding?"""
    return bool(_QUERY_PATTERN.search(text)) or text.rstrip().endswith("?")


def _simple_energy_vad(
    buffer: np.ndarray,
    threshold: float = VOICE_VAD_ENERGY_THRESHOLD,
    silence_ms: int = VOICE_VAD_SILENCE_MS,
    rate: int = GATEWAY_RATE,
) -> bool:
    if buffer.size == 0:
        return False
    silence_samples = int(rate * silence_ms / 1000)
    if buffer.size < silence_samples:
        return False
    tail = buffer[-silence_samples:]
    energy = float(np.mean(tail ** 2))
    return energy < threshold


async def _send_json(ws: WebSocket, msg: dict):
    try:
        await ws.send_text(json.dumps(msg))
    except Exception:
        pass


async def handle_lfm(websocket: WebSocket, session: VoiceSession):
    """LFM2.5 interleaved voice handler."""
    from core.voice.liquid_voice import get_voice_engine
    from core.config import VOICE_LLM_BACKEND

    # Default voice reasoning model if agent has no model_selection.
    if not session.model_selection:
        session.model_selection = VOICE_LLM_BACKEND

    resample_up = Resampler(GATEWAY_RATE, LFM_INPUT_RATE)
    resample_down = Resampler(24000, GATEWAY_RATE)  # LFM2.5 outputs 24kHz

    audio_buffer: List[np.ndarray] = []
    conversation_history: List[dict] = []

    # Get the LFM engine (lazy-loaded singleton)
    loop = asyncio.get_running_loop()
    try:
        engine = await loop.run_in_executor(None, get_voice_engine)
    except Exception as exc:
        logger.error("LFM2.5 engine unavailable: %s", exc)
        await _send_json(websocket, {"type": MSG_ERROR, "message": "LFM2.5 engine unavailable"})
        return

    await _send_json(websocket, {"type": MSG_STATUS, "status": SessionState.LISTENING.value})

    try:
        while True:
            data = await websocket.receive()

            # Text control frames
            if "text" in data:
                try:
                    msg = json.loads(data["text"])
                    if msg.get("type") == "control" and msg.get("action") == "stop":
                        break
                except (json.JSONDecodeError, TypeError):
                    pass
                continue

            # Binary audio frames
            if "bytes" in data:
                pcm_bytes = data["bytes"]
                if not pcm_bytes:
                    continue

                chunk = pcm16_bytes_to_float32(pcm_bytes)
                audio_buffer.append(chunk)

                full_buffer = np.concatenate(audio_buffer) if audio_buffer else np.array([], dtype=np.float32)
                if not _simple_energy_vad(full_buffer, rate=GATEWAY_RATE):
                    continue

                # --- Utterance boundary ---
                if full_buffer.size == 0:
                    audio_buffer.clear()
                    continue

                session.state = SessionState.THINKING
                await _send_json(websocket, {"type": MSG_STATUS, "status": SessionState.THINKING.value})

                # 1. Resample 8k -> 16k
                pcm_16k = resample_up.run(full_buffer)
                audio_buffer.clear()

                # 2. Transcribe via LFM2.5
                try:
                    transcript = await loop.run_in_executor(None, engine.speech_to_text, pcm_16k)
                    transcript = (transcript or "").strip()
                except Exception as exc:
                    logger.error("LFM2.5 STT failed: %s", exc)
                    await _send_json(websocket, {"type": MSG_ERROR, "message": "Transcription failed"})
                    session.state = SessionState.LISTENING
                    await _send_json(websocket, {"type": MSG_STATUS, "status": SessionState.LISTENING.value})
                    continue

                if not transcript:
                    session.state = SessionState.LISTENING
                    await _send_json(websocket, {"type": MSG_STATUS, "status": SessionState.LISTENING.value})
                    continue

                await _send_json(websocket, {"type": MSG_TRANSCRIPT, "text": transcript, "final": True})

                # 3. If it's a query, ground via RAG+LLM
                if _is_query_intent(transcript):
                    try:
                        from core.voice_chat_service import process_question_voice

                        answer = await loop.run_in_executor(
                            None,
                            lambda: process_question_voice(
                                question=transcript,
                                agent_id=session.agent_id,
                                conversation_history=conversation_history,
                                max_history=5,
                                model_selection=session.model_selection,
                                session_id=session.session_id,
                                user_id=session.user_id,
                            ),
                        )
                    except Exception as exc:
                        logger.error("RAG+LLM failed in LFM mode: %s", exc)
                        answer = transcript  # Fall back to echo
                else:
                    # Non-query: let LFM handle conversationally
                    try:
                        answer = await loop.run_in_executor(
                            None, engine.transcribe_and_respond, pcm_16k
                        )
                        answer = (answer or "").strip()
                    except Exception as exc:
                        logger.error("LFM2.5 respond failed: %s", exc)
                        answer = ""

                if answer:
                    await _send_json(websocket, {"type": MSG_ANSWER, "text": answer})
                    conversation_history.append({"role": "user", "content": transcript})
                    conversation_history.append({"role": "assistant", "content": answer})
                    if len(conversation_history) > 10:
                        conversation_history = conversation_history[-10:]

                # 4. TTS via LFM2.5
                session.state = SessionState.SPEAKING
                await _send_json(websocket, {"type": MSG_STATUS, "status": SessionState.SPEAKING.value})

                if answer:
                    try:
                        tts_bytes = await loop.run_in_executor(None, engine.text_to_speech, answer)
                        if tts_bytes:
                            tts_float = pcm16_bytes_to_float32(tts_bytes)
                            gateway_audio = resample_down.run(tts_float)
                            await websocket.send_bytes(float32_to_pcm16_bytes(gateway_audio))
                    except Exception as exc:
                        logger.warning("LFM2.5 TTS failed: %s", exc)

                session.state = SessionState.LISTENING
                await _send_json(websocket, {"type": MSG_STATUS, "status": SessionState.LISTENING.value})

    except WebSocketDisconnect:
        logger.info("LFM session %s disconnected", session.session_id)
    except Exception as exc:
        logger.error("LFM session %s error: %s", session.session_id, exc)
        await _send_json(websocket, {"type": MSG_ERROR, "message": "An internal error occurred"})
