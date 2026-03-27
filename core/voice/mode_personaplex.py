"""
Mode 1: PersonaPlex + Reasoner Sidecar

Three concurrent tasks:
  1. client_to_personaplex — relay audio upstream + tee to reasoner queue
  2. personaplex_to_client — relay audio downstream
  3. reasoner_loop — drain audio queue -> energy-based VAD -> faster-whisper ASR
     -> intent detection -> process_question_voice() -> drip-feed text to PersonaPlex

Uses aiohttp.ClientSession.ws_connect() for the PersonaPlex upstream connection.
"""
import asyncio
import json
import logging
import re
import ssl
from typing import List, Optional
from urllib.parse import urlencode

import numpy as np
from starlette.websockets import WebSocket, WebSocketDisconnect

from core.config import (
    PERSONAPLEX_URL,
    PERSONAPLEX_API_KEY,
    PERSONAPLEX_AUTH_HEADER,
    PERSONAPLEX_SSL_VERIFY,
    PERSONAPLEX_CONNECT_TIMEOUT,
    PERSONAPLEX_RECONNECT_ATTEMPTS,
    PERSONAPLEX_RECONNECT_DELAY,
    PERSONAPLEX_HEARTBEAT,
    VOICE_DRIP_FEED_CHARS,
    VOICE_DRIP_FEED_INTERVAL_MS,
    VOICE_VAD_SILENCE_MS,
    VOICE_VAD_ENERGY_THRESHOLD,
    VOICE_REASONER_QUEUE_SIZE,
)
from core.voice.voice_protocol import (
    VoiceSession, SessionState,
    GATEWAY_RATE, PERSONAPLEX_RATE, LFM_INPUT_RATE,
    MSG_TRANSCRIPT, MSG_ANSWER, MSG_STATUS, MSG_ERROR,
)
from core.voice.resampler import Resampler, pcm16_bytes_to_float32, float32_to_pcm16_bytes
from core.voice.opus_codec import OpusCodec
from core.voice.asr_engine import get_asr_engine

logger = logging.getLogger(__name__)

_QUERY_PATTERN = re.compile(
    r"\b(what|how|when|who|where|why|explain|tell me|describe|can you|could you|is there|are there)\b",
    re.IGNORECASE,
)


def _is_query_intent(text: str) -> bool:
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


async def _drip_feed_text(text: str, px_ws, chars: int = VOICE_DRIP_FEED_CHARS, interval_ms: int = VOICE_DRIP_FEED_INTERVAL_MS):
    """
    Send text to PersonaPlex in small chunks to avoid repetition degeneration.
    PersonaPlex kind=2 frame: b"\\x02" + utf8 text chunk.
    """
    for i in range(0, len(text), chars):
        chunk = text[i:i + chars]
        frame = b"\x02" + chunk.encode("utf-8")
        try:
            await px_ws.send_bytes(frame)
        except Exception:
            break
        await asyncio.sleep(interval_ms / 1000.0)


def _build_personaplex_url(session: VoiceSession) -> str:
    """Build the PersonaPlex WebSocket URL with query parameters."""
    base = PERSONAPLEX_URL.rstrip("/")
    # Protocol conversion: http(s) -> ws(s)
    if base.startswith("https"):
        base = "wss" + base[5:]
    elif base.startswith("http"):
        base = "ws" + base[4:]
    query = urlencode({
        "voice_prompt": session.voice_prompt or "NATF0.pt",
        "text_prompt": session.text_prompt or session.system_prompt or "",
    })
    # PersonaPlex server registers /api/chat (server.py:2137)
    return f"{base}/api/chat?{query}"


def _build_ssl_context() -> Optional[ssl.SSLContext]:
    """Build SSL context for wss:// connections."""
    url = PERSONAPLEX_URL.lower()
    if not url.startswith("https") and not url.startswith("wss"):
        return None
    ctx = ssl.create_default_context()
    if not PERSONAPLEX_SSL_VERIFY:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


async def handle_personaplex(websocket: WebSocket, session: VoiceSession):
    """
    PersonaPlex mode handler with Reasoner sidecar.
    Raises ConnectionError if PersonaPlex is unreachable (triggers cascade fallback).
    """
    import aiohttp

    # --- Phase 1: pgvector prefill — enrich text_prompt with knowledge chunks ---
    from core.agent_manager import get_agent
    from core.rag.retrieval import hybrid_search

    if not session.text_prompt and not session.system_prompt:
        agent = get_agent(session.agent_id)
        if agent:
            session.system_prompt = agent.get("system_prompt") or ""

    try:
        loop = asyncio.get_running_loop()
        prefill_chunks = await loop.run_in_executor(
            None,
            lambda: hybrid_search(
                "account information loan balance",
                session.agent_id,
                top_k=5,
            )
        )
        chunk_texts = []
        for c in prefill_chunks:
            text = c.get("content") or c.get("page_content") or ""
            if text:
                chunk_texts.append(text.strip())
        knowledge = "\n".join(chunk_texts)

        base_prompt = session.text_prompt or session.system_prompt or ""
        if knowledge:
            full_prompt = base_prompt + "\n\nKnowledge:\n" + knowledge
            session.text_prompt = full_prompt[:1000]
            logger.info("Prefilled %d chunks (%d chars) for agent %s",
                        len(chunk_texts), len(session.text_prompt), session.agent_id)
    except Exception as exc:
        logger.warning("pgvector prefill failed (non-fatal): %s", exc)
    # --- END Phase 1 ---

    px_url = _build_personaplex_url(session)
    resample_up = Resampler(GATEWAY_RATE, PERSONAPLEX_RATE)   # 8k -> 24k for PersonaPlex
    resample_down = Resampler(PERSONAPLEX_RATE, GATEWAY_RATE)  # 24k -> 8k for gateway
    resample_asr = Resampler(GATEWAY_RATE, LFM_INPUT_RATE)    # 8k -> 16k for ASR
    opus_codec = OpusCodec(sample_rate=PERSONAPLEX_RATE)

    reasoner_queue: asyncio.Queue = asyncio.Queue(maxsize=VOICE_REASONER_QUEUE_SIZE)
    conversation_history: List[dict] = []
    stop_event = asyncio.Event()

    # Build connection kwargs for RunPod support
    connect_headers = {}
    if PERSONAPLEX_API_KEY:
        connect_headers[PERSONAPLEX_AUTH_HEADER] = PERSONAPLEX_API_KEY
    ssl_ctx = _build_ssl_context()

    async with aiohttp.ClientSession() as http_session:
        # Retry loop for RunPod cold starts / transient failures
        px_ws = None
        last_exc = None
        for attempt in range(1, PERSONAPLEX_RECONNECT_ATTEMPTS + 1):
            try:
                px_ws = await http_session.ws_connect(
                    px_url,
                    timeout=PERSONAPLEX_CONNECT_TIMEOUT,
                    headers=connect_headers or None,
                    ssl=ssl_ctx,
                    heartbeat=PERSONAPLEX_HEARTBEAT,
                )
                logger.info("PersonaPlex connected on attempt %d: %s", attempt, px_url)
                break
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "PersonaPlex connect attempt %d/%d failed: %s",
                    attempt, PERSONAPLEX_RECONNECT_ATTEMPTS, exc,
                )
                if attempt < PERSONAPLEX_RECONNECT_ATTEMPTS:
                    await asyncio.sleep(PERSONAPLEX_RECONNECT_DELAY * attempt)
        if px_ws is None:
            logger.error("PersonaPlex unreachable after %d attempts: %s", PERSONAPLEX_RECONNECT_ATTEMPTS, last_exc)
            raise ConnectionError(f"PersonaPlex unreachable: {last_exc}") from last_exc

        await _send_json(websocket, {"type": MSG_STATUS, "status": SessionState.LISTENING.value})

        async def client_to_personaplex():
            """Relay client audio -> PersonaPlex, tee to reasoner queue."""
            try:
                while not stop_event.is_set():
                    data = await websocket.receive()

                    if "text" in data:
                        try:
                            msg = json.loads(data["text"])
                            if msg.get("type") == "control" and msg.get("action") == "stop":
                                stop_event.set()
                                break
                        except (json.JSONDecodeError, TypeError):
                            pass
                        continue

                    if "bytes" in data:
                        pcm_bytes = data["bytes"]
                        if not pcm_bytes:
                            continue

                        # Resample 8k -> 24k then Opus-encode for PersonaPlex
                        chunk_float = pcm16_bytes_to_float32(pcm_bytes)
                        px_audio = resample_up.run(chunk_float)
                        opus_data = opus_codec.encode(px_audio)

                        # PersonaPlex kind=1 audio frame: b"\x01" + opus bytes
                        if opus_data:
                            try:
                                await px_ws.send_bytes(b"\x01" + opus_data)
                            except Exception:
                                stop_event.set()
                                break

                        # Tee original 8kHz audio to reasoner (non-blocking)
                        try:
                            reasoner_queue.put_nowait(pcm_bytes)
                        except asyncio.QueueFull:
                            pass  # Drop if queue full — reasoner is behind

            except WebSocketDisconnect:
                stop_event.set()
            except Exception as exc:
                logger.error("client_to_personaplex error: %s", exc)
                stop_event.set()

        async def personaplex_to_client():
            """Relay PersonaPlex audio -> client."""
            try:
                async for msg in px_ws:
                    if stop_event.is_set():
                        break
                    if msg.type == aiohttp.WSMsgType.BINARY:
                        frame_data = msg.data
                        if not frame_data:
                            continue
                        kind = frame_data[0]
                        payload = frame_data[1:]

                        if kind == 0:  # Handshake
                            logger.info("PersonaPlex handshake received")
                            continue
                        elif kind == 1:  # Audio frame (Opus-encoded)
                            # Decode Opus -> float32 PCM at 24kHz, resample -> 8kHz
                            px_float = opus_codec.decode(payload)
                            if px_float.size == 0:
                                continue
                            gw_audio = resample_down.run(px_float)
                            try:
                                await websocket.send_bytes(float32_to_pcm16_bytes(gw_audio))
                            except Exception:
                                stop_event.set()
                                break
                        elif kind == 2:  # Text token
                            token_text = payload.decode("utf-8", errors="replace")
                            await _send_json(websocket, {"type": MSG_TRANSCRIPT, "text": token_text, "final": False})
                        elif kind == 3:  # Special
                            pass  # Reserved

                    elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                        stop_event.set()
                        break
            except Exception as exc:
                logger.error("personaplex_to_client error: %s", exc)
                stop_event.set()

        async def reasoner_loop():
            """
            Drain audio queue -> VAD -> ASR -> intent detection ->
            process_question_voice() -> drip-feed answer text to PersonaPlex.
            """
            audio_chunks: List[np.ndarray] = []

            while not stop_event.is_set():
                # Drain available audio from queue
                try:
                    pcm_bytes = await asyncio.wait_for(reasoner_queue.get(), timeout=0.5)
                    chunk = pcm16_bytes_to_float32(pcm_bytes)
                    audio_chunks.append(chunk)
                except asyncio.TimeoutError:
                    continue

                # Drain any additional queued chunks
                while not reasoner_queue.empty():
                    try:
                        extra = reasoner_queue.get_nowait()
                        audio_chunks.append(pcm16_bytes_to_float32(extra))
                    except asyncio.QueueEmpty:
                        break

                full_buffer = np.concatenate(audio_chunks) if audio_chunks else np.array([], dtype=np.float32)

                if not _simple_energy_vad(full_buffer, rate=GATEWAY_RATE):
                    continue

                # Utterance boundary detected
                if full_buffer.size == 0:
                    audio_chunks.clear()
                    continue

                pcm_16k = resample_asr.run(full_buffer)
                audio_chunks.clear()

                # ASR
                try:
                    asr = await get_asr_engine()
                    transcript, confidence = await asr.transcribe(pcm_16k, sample_rate=LFM_INPUT_RATE)
                except Exception as exc:
                    logger.warning("Reasoner ASR failed: %s", exc)
                    continue

                if not transcript.strip():
                    continue

                await _send_json(websocket, {"type": MSG_TRANSCRIPT, "text": transcript, "final": True})

                # Intent detection
                if not _is_query_intent(transcript):
                    continue

                # --- Phase 4: fast pgvector drip-feed (before LLM) ---
                loop = asyncio.get_running_loop()
                try:
                    rag_chunks = await loop.run_in_executor(
                        None,
                        lambda t=transcript: hybrid_search(t, session.agent_id, top_k=3)
                    )
                    chunk_texts = []
                    for c in rag_chunks:
                        text = c.get("content") or c.get("page_content") or ""
                        if text:
                            chunk_texts.append(text.strip())
                    context_text = " ".join(chunk_texts)[:400]
                    if context_text:
                        await _drip_feed_text(context_text, px_ws)
                        logger.info("Drip-fed %d pgvector chars for: %.40s", len(context_text), transcript)
                except Exception as exc:
                    logger.warning("pgvector drip-feed failed: %s", exc)
                # --- END Phase 4 ---

                # RAG + LLM
                session.state = SessionState.THINKING
                await _send_json(websocket, {"type": MSG_STATUS, "status": SessionState.THINKING.value})

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
                            transcript_confidence=confidence,
                        ),
                    )
                except Exception as exc:
                    logger.error("Reasoner RAG+LLM failed: %s", exc)
                    session.state = SessionState.LISTENING
                    await _send_json(websocket, {"type": MSG_STATUS, "status": SessionState.LISTENING.value})
                    continue

                if answer:
                    await _send_json(websocket, {"type": MSG_ANSWER, "text": answer})

                    conversation_history.append({"role": "user", "content": transcript})
                    conversation_history.append({"role": "assistant", "content": answer})
                    if len(conversation_history) > 10:
                        conversation_history = conversation_history[-10:]

                    # Drip-feed answer text to PersonaPlex
                    try:
                        await _drip_feed_text(answer, px_ws)
                    except Exception as exc:
                        logger.warning("Drip-feed failed: %s", exc)

                session.state = SessionState.LISTENING
                await _send_json(websocket, {"type": MSG_STATUS, "status": SessionState.LISTENING.value})

        # Run all three tasks concurrently
        tasks = [
            asyncio.create_task(client_to_personaplex(), name="c2px"),
            asyncio.create_task(personaplex_to_client(), name="px2c"),
            asyncio.create_task(reasoner_loop(), name="reasoner"),
        ]

        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            stop_event.set()
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        finally:
            try:
                await px_ws.close()
            except Exception:
                pass

        logger.info("PersonaPlex session %s ended", session.session_id)
