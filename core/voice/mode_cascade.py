"""
Mode 3: Cascade — STT -> RAG+LLM -> TTS pipeline.

Classic sequential pipeline per utterance:
  1. Receive audio + VAD -> 8kHz -> 16kHz -> faster-whisper ASR
  2. process_question_voice(transcript) -> grounded answer text
  3. LFM2.5 text_to_speech(answer) -> audio bytes
  4. Resample to 8kHz, send back
"""
import asyncio
import json
import logging
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
from core.voice.asr_engine import get_asr_engine
from core.voice_chat_service import process_question_voice

logger = logging.getLogger(__name__)


def _simple_energy_vad(
    buffer: np.ndarray,
    threshold: float = VOICE_VAD_ENERGY_THRESHOLD,
    silence_ms: int = VOICE_VAD_SILENCE_MS,
    rate: int = GATEWAY_RATE,
) -> bool:
    """Return True when trailing silence exceeds the threshold duration."""
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


async def handle_cascade(websocket: WebSocket, session: VoiceSession):
    """
    Cascade mode handler — utterance-at-a-time voice pipeline.
    """
    resample_up = Resampler(GATEWAY_RATE, LFM_INPUT_RATE)     # 8k -> 16k for ASR
    resample_down = Resampler(LFM_INPUT_RATE, GATEWAY_RATE)     # 16k/24k -> 8k for gateway

    audio_buffer: List[np.ndarray] = []
    conversation_history: List[dict] = []

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

                # Check VAD for utterance boundary
                full_buffer = np.concatenate(audio_buffer) if audio_buffer else np.array([], dtype=np.float32)
                if not _simple_energy_vad(full_buffer, rate=GATEWAY_RATE):
                    continue

                # --- Utterance complete ---
                if full_buffer.size == 0:
                    audio_buffer.clear()
                    continue

                session.state = SessionState.THINKING
                await _send_json(websocket, {"type": MSG_STATUS, "status": SessionState.THINKING.value})

                # 1. Resample 8k -> 16k and transcribe
                pcm_16k = resample_up.run(full_buffer)
                audio_buffer.clear()

                try:
                    asr = await get_asr_engine()
                    transcript, confidence, detected_lang = await asr.transcribe(pcm_16k, sample_rate=LFM_INPUT_RATE)
                except Exception as exc:
                    logger.error("ASR failed: %s", exc)
                    await _send_json(websocket, {"type": MSG_ERROR, "message": "Transcription failed"})
                    session.state = SessionState.LISTENING
                    await _send_json(websocket, {"type": MSG_STATUS, "status": SessionState.LISTENING.value})
                    continue

                if not transcript.strip():
                    session.state = SessionState.LISTENING
                    await _send_json(websocket, {"type": MSG_STATUS, "status": SessionState.LISTENING.value})
                    continue

                await _send_json(websocket, {"type": MSG_TRANSCRIPT, "text": transcript, "final": True})

                # 2. RAG + LLM
                loop = asyncio.get_running_loop()
                try:
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
                            transcript_confidence=confidence,
                        ),
                    )
                except Exception as exc:
                    logger.error("RAG+LLM failed: %s", exc)
                    answer = "I'm sorry, I couldn't process that right now."

                await _send_json(websocket, {"type": MSG_ANSWER, "text": answer})

                # Update conversation context
                conversation_history.append({"role": "user", "content": transcript})
                conversation_history.append({"role": "assistant", "content": answer})
                if len(conversation_history) > 10:
                    conversation_history = conversation_history[-10:]

                # 3. TTS via LFM2.5
                session.state = SessionState.SPEAKING
                await _send_json(websocket, {"type": MSG_STATUS, "status": SessionState.SPEAKING.value})

                try:
                    from core.voice.vocoder_engine import get_vocoder_engine

                    vocoder = await get_vocoder_engine()
                    tts_bytes = await vocoder.tts_to_audio(answer)
                    if tts_bytes:
                        # LFM2.5 outputs at its native rate; resample to gateway
                        tts_float = pcm16_bytes_to_float32(tts_bytes)
                        # LFM2.5 outputs 24kHz — use a one-off resampler
                        out_resampler = Resampler(24000, GATEWAY_RATE)
                        gateway_audio = out_resampler.run(tts_float)
                        await websocket.send_bytes(float32_to_pcm16_bytes(gateway_audio))
                except Exception as exc:
                    logger.warning("TTS failed: %s — sending text-only response", exc)

                session.state = SessionState.LISTENING
                await _send_json(websocket, {"type": MSG_STATUS, "status": SessionState.LISTENING.value})

    except WebSocketDisconnect:
        logger.info("Cascade session %s disconnected", session.session_id)
    except Exception as exc:
        logger.error("Cascade session %s error: %s", session.session_id, exc)
        await _send_json(websocket, {"type": MSG_ERROR, "message": "An internal error occurred"})
