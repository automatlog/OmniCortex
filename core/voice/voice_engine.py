"""
OmniCortex Voice Engine
Unified interface for Speech-to-Text (STT) and Text-to-Speech (TTS).

Primary:  PersonaPlex (Moshi) — real-time audio-to-audio via WebSocket.
Fallback: LiquidVoice (LFM2.5-Audio) — in-process speech-to-speech.

If Moshi is unreachable the engine auto-falls-back to LiquidVoice and
logs a warning so operators are notified.
"""
import logging
import threading
from typing import Optional

from core.config import MOSHI_ENABLED, PERSONAPLEX_URL

logger = logging.getLogger("voice_engine")


class MoshiEmptyResponseError(Exception):
    """Raised when Moshi is reachable but returns an empty/stub response."""
    pass

# ---------------------------------------------------------------------------
# Engine registry
# ---------------------------------------------------------------------------
_engine_instance: Optional["VoiceEngine"] = None
_engine_lock = threading.Lock()


class VoiceEngine:
    """
    Unified voice engine with automatic Moshi → LiquidVoice fallback.

    Every public method tries Moshi first.  If Moshi is disabled or
    unavailable the request is routed to LiquidVoice and a warning is
    emitted so operators/monitoring can react.
    """

    def __init__(self):
        self._moshi = None
        self._liquid = None
        self._active_backend: str = "none"
        self._fallback_notified = False

        # --- Try Moshi (primary) ---
        if MOSHI_ENABLED:
            try:
                from core.voice.moshi_engine import MoshiEngine
                self._moshi = MoshiEngine(base_url=PERSONAPLEX_URL)
                if self._moshi.is_available:
                    self._active_backend = "moshi"
                    logger.info("✅ Voice engine: Moshi (PersonaPlex) active at %s", PERSONAPLEX_URL)
                else:
                    logger.warning("⚠️ Moshi server not reachable at %s — will try fallback", PERSONAPLEX_URL)
                    self._moshi = None
            except Exception as e:
                logger.warning("⚠️ Moshi init failed (%s) — will try fallback", e)
                self._moshi = None

        # --- Fallback: LiquidVoice ---
        if self._moshi is None:
            try:
                from core.voice.liquid_voice import get_voice_engine
                self._liquid = get_voice_engine()
                self._active_backend = "liquid"
                self._notify_fallback("Moshi unavailable — fell back to LiquidVoice (LFM2.5-Audio)")
            except Exception as e:
                logger.error("❌ Both Moshi and LiquidVoice failed to initialise: %s", e)
                self._active_backend = "none"

    # ---- Notification helper ----

    def _notify_fallback(self, reason: str):
        """Log a fallback event.  Only emits the first time to avoid spam."""
        if not self._fallback_notified:
            self._fallback_notified = True
            logger.warning("🔄 VOICE FALLBACK: %s", reason)
            # Also emit to Prometheus if available
            try:
                from core.monitoring import REQUEST_COUNT
                REQUEST_COUNT.labels(
                    method="VOICE", endpoint="/voice", status_code="fallback"
                ).inc()
            except Exception:
                pass  # Monitoring not critical

    # ---- Public API ----

    @property
    def backend(self) -> str:
        """Return the name of the active backend ('moshi', 'liquid', or 'none')."""
        return self._active_backend

    def transcribe(self, audio_source) -> str:
        """
        Transcribe audio to text.

        Moshi does not expose an REST-based ASR endpoint, so transcription
        always uses LiquidVoice's speech_to_text when available.
        """
        # Moshi does not have REST transcription — always delegate
        if self._liquid is not None:
            if self._active_backend == "moshi":
                logger.info("ℹ️ Transcription routed to LiquidVoice (Moshi lacks REST ASR)")
            return self._liquid.speech_to_text(
                audio_source if isinstance(audio_source, bytes) else open(audio_source, "rb").read()
            )

        if self._moshi is not None:
            return self._moshi.transcribe(
                audio_source if isinstance(audio_source, bytes) else open(audio_source, "rb").read()
            )

        raise ConnectionError(
            "No voice engine available for transcription. "
            "Start Moshi or install liquid-audio."
        )

    def speak(self, text: str, voice: str = None, allow_fallback: bool = False) -> bytes:
        """
        Convert text to speech audio bytes (WAV).

        Args:
            text: Text to synthesize.
            voice: Optional voice ID.
            allow_fallback: If True, auto-fallback to LiquidVoice when Moshi
                            returns empty. If False (default), raises
                            MoshiEmptyResponseError so the caller/client can
                            decide whether to retry or fallback.
        """
        if self._moshi is not None and self._moshi.is_available:
            result = self._moshi.speak(text)
            if result:
                return result
            # Moshi returned empty — let caller decide
            logger.warning("⚠️ Moshi speak() returned empty response for: %s", text[:80])
            if not allow_fallback:
                raise MoshiEmptyResponseError(
                    "Moshi returned an empty response. You can retry or "
                    "request fallback to LiquidVoice by setting allow_fallback=true."
                )
            # Explicit fallback consented
            logger.warning("🔄 User consented to fallback — routing TTS to LiquidVoice")

        if self._liquid is not None:
            self._notify_fallback("TTS request routed to LiquidVoice")
            return self._liquid.text_to_speech(text)

        raise ConnectionError(
            "No voice engine available for TTS. "
            "Start Moshi or install liquid-audio."
        )

    def voice_chat(self, audio_bytes: bytes, system_prompt: str = None, history: list = None) -> dict:
        """
        End-to-end voice-to-voice using LiquidVoice (speech→speech+text).

        For RAG-aware voice chat, use the /voice/chat API endpoint instead
        which pipes transcription through the /query RAG pipeline.
        """
        if self._liquid is not None:
            resp = self._liquid.transcribe_and_respond(
                audio_bytes=audio_bytes,
                system_prompt=system_prompt or "You are a helpful assistant.",
                conversation_history=history,
            )
            return {
                "text": resp.text,
                "audio_bytes": resp.audio_bytes,
                "sample_rate": resp.sample_rate,
                "backend": "liquid",
            }

        raise ConnectionError("LiquidVoice not available for voice chat.")


# ---------------------------------------------------------------------------
# Singleton accessor (thread-safe)
# ---------------------------------------------------------------------------

def get_engine() -> VoiceEngine:
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = VoiceEngine()
    return _engine_instance


# ---------------------------------------------------------------------------
# Backward-compatible wrapper functions (used by api.py imports)
# ---------------------------------------------------------------------------

def transcribe_audio(audio_source) -> str:
    """Wrapper for STT — used by api.py /voice/transcribe and /voice/chat."""
    return get_engine().transcribe(audio_source)


def speak(text: str, voice: str = None, allow_fallback: bool = False) -> bytes:
    """Wrapper for TTS — used by api.py /voice/speak and /voice/chat."""
    return get_engine().speak(text, voice=voice, allow_fallback=allow_fallback)


def voice_conversion(audio_bytes: bytes, voice_id: str = None) -> bytes:
    """Wrapper for STS — currently no-op on both engines."""
    logger.warning("⚠️ Voice conversion not supported by current engines")
    return audio_bytes
