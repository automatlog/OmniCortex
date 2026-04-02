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
import random
import re
import ssl
import time
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
    VOICE_POST_SILENCE_DELAY_MS,
    VOICE_BACKCHANNEL_PAUSE_MS,
    VOICE_BACKCHANNEL_COOLDOWN_S,
    VOICE_BACKCHANNEL_MIN_SPEECH_S,
)
from core.voice.voice_protocol import (
    VoiceSession, SessionState,
    GATEWAY_RATE, PERSONAPLEX_RATE, LFM_INPUT_RATE,
    MSG_TRANSCRIPT, MSG_ANSWER, MSG_STATUS, MSG_ERROR, MSG_TRANSFER,
)
from core.voice.resampler import Resampler, pcm16_bytes_to_float32, float32_to_pcm16_bytes
from core.voice.opus_codec import OpusCodec
from core.voice.asr_engine import get_asr_engine
from core.voice.intent_tracker import IntentTracker
from core.voice.agent_workflow import AgentWorkflow
from core.voice.agent_router import AgentRouter, analyze_sentiment, extract_entities
from core.voice.conversation_gate import ConversationGate

logger = logging.getLogger(__name__)

_QUERY_PATTERN = re.compile(
    r"\b(what|how|when|who|where|why|explain|tell me|describe|can you|could you|is there|are there)\b",
    re.IGNORECASE,
)


def _is_query_intent(text: str) -> bool:
    return bool(_QUERY_PATTERN.search(text)) or text.rstrip().endswith("?")


# ── Backchannel / mimicking ─────────────────────────────────────────
BACKCHANNEL_PHRASES = ["hmm", "okay", "I see", "got it", "right", "yes", "alright", "I understand"]

def _detect_brief_pause(
    buffer: np.ndarray,
    threshold: float = VOICE_VAD_ENERGY_THRESHOLD,
    brief_ms: int = VOICE_BACKCHANNEL_PAUSE_MS,
    silence_ms: int = VOICE_VAD_SILENCE_MS,
    rate: int = GATEWAY_RATE,
) -> str:
    """Detect pause type in audio buffer tail.

    Returns:
      "speaking"       — energy above threshold at tail
      "brief_pause"    — silence >= brief_ms but < silence_ms (backchannel window)
      "utterance_end"  — silence >= silence_ms (full utterance boundary)
    """
    if buffer.size == 0:
        return "speaking"
    brief_samples = int(rate * brief_ms / 1000)
    silence_samples = int(rate * silence_ms / 1000)

    # Check for full utterance end first
    if buffer.size >= silence_samples:
        tail_long = buffer[-silence_samples:]
        if float(np.mean(tail_long ** 2)) < threshold:
            return "utterance_end"

    # Check for brief pause
    if buffer.size >= brief_samples:
        tail_short = buffer[-brief_samples:]
        if float(np.mean(tail_short ** 2)) < threshold:
            return "brief_pause"

    return "speaking"


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
    except Exception as exc:
        logger.warning(
            "WebSocket send_json failed (type=%s, ws=%s): %s",
            msg.get("type") if isinstance(msg, dict) else None,
            id(ws),
            exc,
        )


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


async def _fast_inject_text(text: str, px_ws, chars: int = 80):
    """Send text to PersonaPlex in large chunks with minimal delay.
    Used for RAG context injection where speed matters more than pacing."""
    for i in range(0, len(text), chars):
        chunk = text[i:i + chars]
        frame = b"\x02" + chunk.encode("utf-8")
        try:
            await px_ws.send_bytes(frame)
        except Exception:
            break
        await asyncio.sleep(0.01)  # 10ms — just enough to not flood


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
    from core.agent_manager import get_agent, resolve_retrieval_config, resolve_voice_config
    from core.rag.retrieval import hybrid_search
    from core.config import VOICE_LLM_BACKEND

    _agent_data = get_agent(session.agent_id)
    _ret_cfg = resolve_retrieval_config(session.agent_id, agent=_agent_data)
    _voice_cfg = resolve_voice_config(session.agent_id, agent=_agent_data)

    # Default voice reasoning model if agent has no model_selection.
    if not session.model_selection:
        session.model_selection = VOICE_LLM_BACKEND

    if not session.text_prompt and not session.system_prompt:
        if _agent_data:
            session.system_prompt = _agent_data.get("system_prompt") or ""

    # Apply agent-level voice defaults if no query-param override was given
    if session.voice_prompt == "NATF0.pt" and _voice_cfg.get("voice_prompt"):
        session.voice_prompt = _voice_cfg["voice_prompt"]

    _prefill_top_k = _ret_cfg.get("voice_top_k", 8)
    _prefill_use_hybrid = _ret_cfg.get("use_hybrid_search")
    _prefill_rerank = _ret_cfg.get("use_reranker")
    _prefill_reranker_model = _ret_cfg.get("reranker_model")

    try:
        loop = asyncio.get_running_loop()

        # Build a broad prefill query from the system prompt keywords
        # so we pull diverse knowledge (not just "account loan balance")
        _base = session.system_prompt or session.text_prompt or ""
        _prefill_query = _base[:200] if len(_base) > 30 else "general information services products"

        prefill_chunks = await loop.run_in_executor(
            None,
            lambda q=_prefill_query: hybrid_search(
                q,
                session.agent_id,
                top_k=_prefill_top_k,
                use_hybrid=_prefill_use_hybrid,
                rerank=_prefill_rerank,
                reranker_model=_prefill_reranker_model,
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
            session.text_prompt = full_prompt[:2000]
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

    # Intent tracker — load agent-specific intent map if available
    agent_intent_kw = None
    agent_follow_map = None
    try:
        if _agent_data:
            _extra = _agent_data.get("extra_data") or _agent_data.get("metadata") or {}
            agent_intent_kw = _extra.get("intent_keywords")
            agent_follow_map = _extra.get("follow_up_map")
    except Exception:
        pass
    intent_tracker = IntentTracker(
        agent_intent_keywords=agent_intent_kw,
        agent_follow_up_map=agent_follow_map,
    )

    # Agent workflow state machine (loaded from agent.logic or extra_data)
    workflow: Optional[AgentWorkflow] = None
    try:
        workflow = AgentWorkflow.from_agent(_agent)
        if workflow and workflow.is_active():
            session.workflow_state = workflow.current_state
            logger.info("Workflow initialized: state=%s", workflow.current_state)
    except Exception:
        pass

    # Multi-agent router (loaded from agent.logic or extra_data routing config)
    agent_router = AgentRouter.from_agent(_agent)
    if agent_router.has_rules():
        logger.info("AgentRouter loaded with %d transfer rules", len(agent_router._rules))

    # Conversation gate — validates caller input before agent continues
    conv_gate = ConversationGate()
    agent_sentence_buf = [""]  # accumulate PersonaPlex text tokens into sentences

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
                            # Track agent output sentences for conversation gate
                            agent_sentence_buf[0] += token_text
                            for end_ch in ".!?\n":
                                if end_ch in agent_sentence_buf[0]:
                                    idx = agent_sentence_buf[0].rindex(end_ch)
                                    sentence = agent_sentence_buf[0][:idx + 1].strip()
                                    agent_sentence_buf[0] = agent_sentence_buf[0][idx + 1:]
                                    if sentence:
                                        clean = sentence.replace("\u2581", " ").strip()
                                        conv_gate.on_agent_sentence(clean)
                                    break
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
            Includes backchannel injection during brief pauses.
            """
            audio_chunks: List[np.ndarray] = []
            last_backchannel_t = 0.0       # monotonic time of last backchannel
            speech_start_t = 0.0           # when caller started speaking
            last_bc_phrase_idx = -1        # avoid repeating same phrase consecutively
            detected_lang = "en"           # track detected language across turns

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

                # Detect pause type: speaking / brief_pause / utterance_end
                pause_type = _detect_brief_pause(full_buffer, rate=GATEWAY_RATE)

                if pause_type == "speaking":
                    # Track when caller started speaking
                    if speech_start_t == 0.0:
                        speech_start_t = time.monotonic()
                    continue

                if pause_type == "brief_pause":
                    # Backchannel injection during brief pauses
                    now = time.monotonic()
                    speech_dur = now - speech_start_t if speech_start_t > 0 else 0
                    cooldown_ok = (now - last_backchannel_t) >= VOICE_BACKCHANNEL_COOLDOWN_S
                    speech_long_enough = speech_dur >= VOICE_BACKCHANNEL_MIN_SPEECH_S

                    if cooldown_ok and speech_long_enough:
                        # Pick a phrase, avoiding consecutive repeats
                        idx = random.randint(0, len(BACKCHANNEL_PHRASES) - 1)
                        while idx == last_bc_phrase_idx and len(BACKCHANNEL_PHRASES) > 1:
                            idx = random.randint(0, len(BACKCHANNEL_PHRASES) - 1)
                        phrase = BACKCHANNEL_PHRASES[idx]
                        last_bc_phrase_idx = idx
                        last_backchannel_t = now

                        # Send as kind=2 text frame to PersonaPlex
                        try:
                            await px_ws.send_bytes(b"\x02" + phrase.encode("utf-8"))
                            logger.info("Backchannel injected: '%s' (speech=%.1fs)", phrase, speech_dur)
                        except Exception:
                            pass
                    continue

                # pause_type == "utterance_end"
                speech_start_t = 0.0  # reset for next utterance

                # Wait 0.5s to confirm caller is done
                await asyncio.sleep(VOICE_POST_SILENCE_DELAY_MS / 1000.0)

                # Re-check: if new audio arrived during delay, caller was just pausing
                resumed = False
                while not reasoner_queue.empty():
                    try:
                        extra = reasoner_queue.get_nowait()
                        audio_chunks.append(pcm16_bytes_to_float32(extra))
                        resumed = True
                    except asyncio.QueueEmpty:
                        break
                if resumed:
                    continue  # go back to VAD, caller is still speaking

                if full_buffer.size == 0:
                    audio_chunks.clear()
                    continue

                pcm_16k = resample_asr.run(full_buffer)
                audio_chunks.clear()

                # ASR
                try:
                    asr = await get_asr_engine()
                    transcript, confidence, detected_lang = await asr.transcribe(pcm_16k, sample_rate=LFM_INPUT_RATE)
                except Exception as exc:
                    logger.warning("Reasoner ASR failed: %s", exc)
                    continue

                if not transcript.strip():
                    continue

                # Language change detection
                prev_lang = session.detected_language
                if detected_lang and detected_lang != prev_lang:
                    session.detected_language = detected_lang
                    logger.info("Language changed: %s -> %s", prev_lang, detected_lang)
                    await _send_json(websocket, {
                        "type": MSG_STATUS, "status": "language_changed",
                        "from_language": prev_lang, "to_language": detected_lang,
                    })

                logger.info("ASR: lang=%s conf=%.2f text=%.60s", detected_lang, confidence, transcript)
                await _send_json(websocket, {
                    "type": MSG_TRANSCRIPT, "text": transcript,
                    "final": True, "language": detected_lang,
                })

                # --- Conversation gate: validate caller input ---
                if conv_gate.is_blocking():
                    gate_result = conv_gate.validate_caller_input(transcript)
                    if not gate_result.valid:
                        # Input didn't match — ask caller to repeat
                        if gate_result.retry_prompt:
                            logger.info("Gate: retry — %s", gate_result.retry_prompt)
                            await _drip_feed_text(gate_result.retry_prompt, px_ws)
                            await _send_json(websocket, {
                                "type": MSG_ANSWER, "text": gate_result.retry_prompt,
                            })
                        continue  # skip LLM, wait for caller to repeat
                    # Input is valid — inject confirmation
                    if gate_result.confirmation_text:
                        logger.info("Gate: confirmed — %s", gate_result.confirmation_text)
                        await _drip_feed_text(gate_result.confirmation_text, px_ws)
                        await _send_json(websocket, {
                            "type": MSG_ANSWER, "text": gate_result.confirmation_text,
                        })
                    # Feed extracted value to workflow entities
                    if gate_result.extracted_value and workflow and workflow.is_active():
                        for ent_key in ["phone", "dob", "account_number"]:
                            if ent_key in conv_gate.expecting:
                                workflow.collect_entity(ent_key, gate_result.extracted_value)
                    await _send_json(websocket, {
                        "type": MSG_STATUS, "status": "input_validated",
                        "collected": dict(conv_gate.collected),
                    })
                else:
                    # Gate is open — also validate opportunistically
                    gate_result = conv_gate.validate_caller_input(transcript)
                    if gate_result.confirmation_text:
                        await _drip_feed_text(gate_result.confirmation_text, px_ws)

                # Intent detection via tracker (replaces old regex _is_query_intent)
                if not intent_tracker.is_query_intent(transcript):
                    continue

                current_intent = intent_tracker.get_current_intent()
                logger.info("Intent: %s | History: %s", current_intent,
                            ", ".join(intent_tracker.intent_history[-3:]))

                # --- Sentiment analysis + entity extraction ---
                sentiment_label, sentiment_score = analyze_sentiment(transcript)
                entities = extract_entities(transcript)
                if entities:
                    logger.info("Entities extracted: %s", entities)
                    # Feed entities to workflow if active
                    if workflow and workflow.is_active():
                        for ent_name, ent_val in entities.items():
                            workflow.collect_entity(ent_name, ent_val)

                # --- Multi-agent transfer evaluation ---
                if agent_router.has_rules():
                    transfer = agent_router.evaluate(
                        transcript=transcript,
                        intent=current_intent or "",
                        sentiment=sentiment_label,
                        sentiment_score=sentiment_score,
                        detected_language=detected_lang,
                        workflow_state=session.workflow_state,
                        current_agent_id=session.agent_id,
                    )
                    if transfer.should_transfer:
                        logger.info("Transfer triggered: %s -> agent %s (%s)",
                                    session.agent_id, transfer.target_agent_id[:8], transfer.reason)
                        # Speak transfer message to caller via PersonaPlex
                        if transfer.message:
                            await _drip_feed_text(transfer.message, px_ws)
                        # Record transfer in history and session
                        agent_router.transfer_history.add(
                            session.agent_id, transfer.target_agent_id, transfer.reason)
                        session.previous_agent_ids.append(session.agent_id)
                        session.transfer_count += 1
                        session.pending_transfer_agent_id = transfer.target_agent_id
                        session.handoff_reason = transfer.reason
                        # Notify client about transfer
                        await _send_json(websocket, {
                            "type": MSG_TRANSFER,
                            "target_agent_id": transfer.target_agent_id,
                            "reason": transfer.reason,
                            "message": transfer.message,
                            "rule_matched": transfer.rule_matched,
                            "transfer_count": session.transfer_count,
                        })
                        # Signal stop — the API layer will reconnect to new agent
                        stop_event.set()
                        break

                # Check workflow transfer_to_agent (state-driven transfers)
                if workflow and workflow.is_active():
                    wf_transfer_target = workflow.get_transfer_target()
                    if wf_transfer_target and wf_transfer_target != session.agent_id:
                        logger.info("Workflow transfer: state=%s -> agent %s",
                                    workflow.current_state, wf_transfer_target[:8])
                        session.previous_agent_ids.append(session.agent_id)
                        session.transfer_count += 1
                        session.pending_transfer_agent_id = wf_transfer_target
                        session.handoff_reason = f"workflow_state={workflow.current_state}"
                        await _send_json(websocket, {
                            "type": MSG_TRANSFER,
                            "target_agent_id": wf_transfer_target,
                            "reason": f"workflow_state={workflow.current_state}",
                            "transfer_count": session.transfer_count,
                        })
                        stop_event.set()
                        break

                # Workflow: check if current state blocks this intent
                if workflow and workflow.is_active() and current_intent:
                    if workflow.is_blocked(current_intent):
                        logger.info("Workflow blocks intent '%s' in state '%s'",
                                    current_intent, workflow.current_state)
                        # Respond with the current state's prompt override instead
                        override = workflow.get_current_prompt_override()
                        if override:
                            await _drip_feed_text(override, px_ws)
                        continue

                # --- Phase 4: fast pgvector drip-feed (before LLM) ---
                loop = asyncio.get_running_loop()

                # Check prefetch cache first (from previous turn's prediction)
                cached = intent_tracker.get_cached(current_intent) if current_intent else None
                rag_context_text = ""
                if cached:
                    chunk_texts = []
                    for c in cached:
                        text = c.get("content") or c.get("page_content") or ""
                        if text:
                            chunk_texts.append(text.strip())
                    rag_context_text = " ".join(chunk_texts)[:600]
                    if rag_context_text:
                        await _fast_inject_text(rag_context_text, px_ws)
                        logger.info("Fast-injected %d CACHED chars for intent=%s", len(rag_context_text), current_intent)
                else:
                    try:
                        rag_chunks = await loop.run_in_executor(
                            None,
                            lambda t=transcript: hybrid_search(
                                t,
                                session.agent_id,
                                top_k=_ret_cfg.get("voice_top_k", 3),
                                use_hybrid=_ret_cfg.get("use_hybrid_search"),
                                rerank=_ret_cfg.get("use_reranker"),
                                reranker_model=_ret_cfg.get("reranker_model"),
                            )
                        )
                        chunk_texts = []
                        for c in rag_chunks:
                            text = c.get("content") or c.get("page_content") or ""
                            if text:
                                chunk_texts.append(text.strip())
                        rag_context_text = " ".join(chunk_texts)[:600]
                        if rag_context_text:
                            await _fast_inject_text(rag_context_text, px_ws)
                            logger.info("Fast-injected %d pgvector chars for: %.40s", len(rag_context_text), transcript)
                    except Exception as exc:
                        logger.warning("pgvector drip-feed failed: %s", exc)

                # Background prefetch for predicted follow-up intents
                prefetch_queries = intent_tracker.get_prefetch_queries()
                for pq in prefetch_queries[:2]:
                    async def _do_prefetch(query=pq):
                        try:
                            results = await loop.run_in_executor(
                                None,
                                lambda q=query: hybrid_search(
                                    q,
                                    session.agent_id,
                                    top_k=_ret_cfg.get("voice_top_k", 3),
                                    use_hybrid=_ret_cfg.get("use_hybrid_search"),
                                    rerank=_ret_cfg.get("use_reranker"),
                                    reranker_model=_ret_cfg.get("reranker_model"),
                                )
                            )
                            for intent_name, intent_query in [
                                (k, v) for k, v in {
                                    "loan_balance": "loan balance outstanding amount principal",
                                    "payment": "payment options installment EMI schedule",
                                    "interest_rate": "interest rate APR percentage annual",
                                    "due_date": "payment due date deadline schedule",
                                    "account_info": "account details profile information",
                                    "transaction_history": "transaction history statement recent activity",
                                }.items() if v == query
                            ]:
                                intent_tracker.cache_prefetch(intent_name, results)
                                break
                        except Exception:
                            pass
                    asyncio.create_task(_do_prefetch())
                # --- END Phase 4 ---

                # RAG chunks already injected into Helium — run LLM in background
                # so Helium can start speaking immediately from RAG context
                async def _background_llm(
                    _transcript=transcript, _confidence=confidence,
                    _sentiment_label=sentiment_label, _sentiment_score=sentiment_score,
                    _current_intent=current_intent,
                ):
                    try:
                        from core.voice_chat_service import process_question_voice

                        intent_context = intent_tracker.get_intent_context()
                        enriched_question = _transcript
                        if intent_context:
                            enriched_question = f"{_transcript}\n[{intent_context}]"
                        if _sentiment_label != "neutral":
                            enriched_question = f"{enriched_question}\n[Caller sentiment: {_sentiment_label} ({_sentiment_score:.2f})]"
                        if workflow and workflow.is_active():
                            wf_override = workflow.get_current_prompt_override()
                            if wf_override:
                                enriched_question = f"{enriched_question}\n[Workflow instruction: {wf_override}]"

                        answer = await loop.run_in_executor(
                            None,
                            lambda: process_question_voice(
                                question=enriched_question,
                                agent_id=session.agent_id,
                                conversation_history=conversation_history,
                                max_history=5,
                                model_selection=session.model_selection,
                                session_id=session.session_id,
                                user_id=session.user_id,
                                transcript_confidence=_confidence,
                            ),
                        )

                        if answer:
                            await _send_json(websocket, {"type": MSG_ANSWER, "text": answer})
                            conversation_history.append({"role": "user", "content": _transcript})
                            conversation_history.append({"role": "assistant", "content": answer})
                            if len(conversation_history) > 10:
                                conversation_history[:] = conversation_history[-10:]
                            # Drip-feed LLM answer as refinement
                            await _drip_feed_text(answer, px_ws)
                            # Advance workflow
                            if workflow and workflow.is_active():
                                new_override = workflow.advance(_transcript, answer)
                                session.workflow_state = workflow.current_state
                                if new_override:
                                    logger.info("Workflow advanced to '%s'", workflow.current_state)
                                    await _send_json(websocket, {
                                        "type": MSG_STATUS,
                                        "status": "workflow_state_changed",
                                        "workflow": workflow.get_state_info(),
                                    })
                    except Exception as exc:
                        logger.error("Background LLM failed: %s", exc)

                asyncio.create_task(_background_llm())

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
