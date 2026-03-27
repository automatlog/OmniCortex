"""
OmniCortex Moshi Engine (PersonaPlex)
Interface for Nvidia PersonaPlex (Moshi) voice server.
"""
import requests
from urllib.parse import urlparse, urlunparse

from core.config import PERSONAPLEX_URL


class MoshiEngine:
    """
    Interface for Moshi voice server.
    Moshi is audio-to-audio over WebSocket in this integration.
    """

    def __init__(self, base_url: str = None):
        self.base_url = base_url or PERSONAPLEX_URL
        self.is_available = self._check_server()

    def _healthcheck_urls(self) -> list[str]:
        """Generate candidate HTTP health endpoints for the configured server."""
        raw_base = (self.base_url or "").strip()
        if "://" not in raw_base:
            raw_base = f"http://{raw_base or 'localhost:8998'}"

        parsed = urlparse(raw_base)
        scheme = parsed.scheme.lower()
        if scheme == "ws":
            scheme = "http"
        elif scheme == "wss":
            scheme = "https"
        elif not scheme:
            scheme = "http"

        root = urlunparse((scheme, parsed.netloc, "", "", "", "")).rstrip("/")
        if not root:
            root = "http://localhost:8998"
        return [f"{root}/health", f"{root}/readiness", root]

    def _check_server(self) -> bool:
        """Check if Moshi server is reachable."""
        last_error = None
        try:
            for url in self._healthcheck_urls():
                try:
                    response = requests.get(url, timeout=2)
                    response.raise_for_status()
                    print(f"[Moshi] Server reachable at {url}")
                    return True
                except Exception as exc:
                    last_error = exc
        except Exception as exc:
            last_error = exc
        print(f"[Moshi] Server not reachable via {self._healthcheck_urls()}: {last_error}")
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
