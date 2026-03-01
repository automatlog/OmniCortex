"""
OmniCortex Voice Engine (Moshi-only mode)

This runtime is intentionally restricted to PersonaPlex/Moshi.
REST STT/TTS is not supported by Moshi in this integration; use /voice/ws.
"""
import logging
import threading
from typing import Optional

from core.config import MOSHI_ENABLED, PERSONAPLEX_URL

logger = logging.getLogger("voice_engine")


class MoshiEmptyResponseError(Exception):
    """Raised when Moshi is reachable but returns no audio payload."""


_engine_instance: Optional["VoiceEngine"] = None
_engine_lock = threading.Lock()


class VoiceEngine:
    """Moshi-only voice engine."""

    def __init__(self):
        self._moshi = None
        self._active_backend: str = "none"

        if not MOSHI_ENABLED:
            logger.warning("Moshi-only mode active, but MOSHI_ENABLED=false")
            return

        try:
            from core.voice.moshi_engine import MoshiEngine

            self._moshi = MoshiEngine(base_url=PERSONAPLEX_URL)
            if self._moshi.is_available:
                self._active_backend = "moshi"
                logger.info("Voice engine active: Moshi at %s", PERSONAPLEX_URL)
            else:
                logger.warning("Moshi server not reachable at %s", PERSONAPLEX_URL)
                self._moshi = None
        except Exception as exc:
            logger.error("Moshi init failed: %s", exc)
            self._moshi = None
            self._active_backend = "none"

    @property
    def backend(self) -> str:
        """Return active backend name ('moshi' or 'none')."""
        return self._active_backend

    def transcribe(self, audio_source) -> str:
        """REST transcription is not available in Moshi-only mode."""
        raise NotImplementedError(
            "Moshi-only mode does not support REST transcription. Use /voice/ws."
        )

    def speak(self, text: str, voice: str = None, allow_fallback: bool = False) -> bytes:
        """
        Try Moshi TTS bridge.

        Note: allow_fallback is ignored in Moshi-only mode and kept only for API compatibility.
        """
        if self._moshi is None or not self._moshi.is_available:
            raise ConnectionError(
                f"Moshi server not available at {PERSONAPLEX_URL}. "
                "Start Moshi and use /voice/ws."
            )

        try:
            result = self._moshi.speak(text)
        except NotImplementedError as exc:
            raise MoshiEmptyResponseError(str(exc)) from exc

        if result:
            return result

        raise MoshiEmptyResponseError(
            "Moshi returned empty audio. Use /voice/ws for real-time voice streaming."
        )

    def voice_chat(self, audio_bytes: bytes, system_prompt: str = None, history: list = None) -> dict:
        """REST voice chat is not available in Moshi-only mode."""
        raise NotImplementedError(
            "Moshi-only mode does not support REST voice chat. Use /voice/ws."
        )


def get_engine() -> VoiceEngine:
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = VoiceEngine()
    return _engine_instance


def transcribe_audio(audio_source) -> str:
    """Wrapper for STT (Moshi-only)."""
    return get_engine().transcribe(audio_source)


def speak(text: str, voice: str = None, allow_fallback: bool = False) -> bytes:
    """Wrapper for TTS (Moshi-only)."""
    return get_engine().speak(text, voice=voice, allow_fallback=allow_fallback)


def voice_conversion(audio_bytes: bytes, voice_id: str = None) -> bytes:
    """Wrapper for STS - not supported in this integration."""
    logger.warning("Voice conversion is not supported in Moshi-only mode")
    return audio_bytes