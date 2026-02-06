"""
OmniCortex Moshi Engine (PersonaPlex)
Interface for Nvidia PersonaPlex (Moshi) Voice Model
"""
import os
import requests
from core.config import PERSONAPLEX_URL


class MoshiEngine:
    """
    Interface for Moshi Voice Server (PersonaPlex).
    Moshi is an Audio-to-Audio model (not traditional TTS).
    """
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or PERSONAPLEX_URL
        self.is_available = self._check_server()
        
    def _check_server(self) -> bool:
        """Check if Moshi server is reachable"""
        try:
            response = requests.get(self.base_url, timeout=2)
            print(f"✅ [Moshi] Server reachable at {self.base_url}")
            return True
        except Exception as e:
            print(f"⚠️ [Moshi] Server not reachable: {e}")
            return False

    def speak(self, text: str) -> bytes:
        """
        Generate speech from text using PersonaPlex.
        
        Note: Moshi is primarily Audio-to-Audio (voice-to-voice).
        For Text-to-Speech, users should use the Web UI directly.
        
        This method guides users to the correct interface.
        """
        if not self.is_available:
            print(f"❌ [Moshi] Server unavailable at {self.base_url}")
            raise ConnectionError(
                f"Moshi server not available at {self.base_url}\n"
                f"Start with: python -m moshi.server --port 8998"
            )
        
        print(f"ℹ️ [Moshi] TTS requested for: {text[:50]}...")
        print(f"ℹ️ [Moshi] Use Moshi Web UI for full voice interaction:")
        print(f"   {self.base_url}")
        
        # Return empty bytes - UI will show message to use Web UI
        return b""

    def transcribe(self, audio_bytes: bytes) -> str:
        """
        Transcribe audio using Moshi.
        
        Note: Moshi doesn't expose a REST API for transcription.
        Users should use the WebSocket interface in the Web UI.
        """
        if not self.is_available:
            raise ConnectionError(f"Moshi server not available at {self.base_url}")
        
        print(f"ℹ️ [Moshi] Transcription requires WebSocket connection")
        print(f"   Use Moshi Web UI at: {self.base_url}")
        
        return "[Use Moshi Web UI for voice interaction]"


def get_moshi_engine():
    """Get or create Moshi engine singleton"""
    return MoshiEngine()
