"""
OmniCortex Moshi Engine (PersonaPlex)
Interface for Nvidia PersonaPlex (Moshi) voice server.
"""
import requests

from core.config import PERSONAPLEX_URL


class MoshiEngine:
    """
    Interface for Moshi voice server.
    Moshi is audio-to-audio over WebSocket in this integration.
    """

    def __init__(self, base_url: str = None):
        self.base_url = base_url or PERSONAPLEX_URL
        self.is_available = self._check_server()

    def _check_server(self) -> bool:
        """Check if Moshi server is reachable."""
        try:
            response = requests.get(self.base_url, timeout=2)
            response.raise_for_status()
            print(f"[Moshi] Server reachable at {self.base_url}")
            return True
        except Exception as exc:
            print(f"[Moshi] Server not reachable: {exc}")
            return False

    def speak(self, text: str) -> bytes:
        """
        REST TTS is not supported by Moshi in this integration.
        Use /voice/ws for real-time voice streaming.
        """
        if not self.is_available:
            raise ConnectionError(
                f"Moshi server not available at {self.base_url}. "
                "Start with: python -m moshi.server --port 8998"
            )
        raise NotImplementedError(
            "Moshi REST TTS is not supported in this integration. Use /voice/ws."
        )

    def transcribe(self, audio_bytes: bytes) -> str:
        """
        REST transcription is not supported by Moshi in this integration.
        Use /voice/ws for real-time voice streaming.
        """
        if not self.is_available:
            raise ConnectionError(f"Moshi server not available at {self.base_url}")
        raise NotImplementedError(
            "Moshi REST transcription is not supported in this integration. Use /voice/ws."
        )


_moshi_instance = None


def get_moshi_engine():
    """Get or create Moshi engine singleton."""
    global _moshi_instance
    if _moshi_instance is None:
        _moshi_instance = MoshiEngine()
    return _moshi_instance