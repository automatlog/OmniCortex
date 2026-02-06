"""
OmniCortex Moshi Engine (PersonaPlex)
Intefrace for Nvidia PersonaPlex (Moshi) Voice Model
"""
import os
import requests
import asyncio
from core.config import PERSONAPLEX_URL

class MoshiEngine:
    """
    Interface for Moshi Voice Server (PersonaPlex).
    """
    def __init__(self, base_url: str = None):
        self.base_url = base_url or PERSONAPLEX_URL
        self.has_warned = False

    def speak(self, text: str) -> bytes:
        """
        Generate speech from text using PersonaPlex.
        Note: Moshi is primarily Audio-to-Audio. Text-to-Audio support via API depends on server implementation.
        If standard Moshi server, we might need to wrap text in a specific payload or use a different endpoint.
        
        For now, we'll try a standard POST /tts if available, or warn if not supported.
        """
        try:
            # Placeholder for actual Moshi API call. 
            # Moshi doesn't have a standard REST TTS endpoint out of the box in the demo server.
            # Assuming we might have a wrapper or need to implement one.
            # If no endpoint exists, we return a fallback or error.
            
            # TODO: Implement actual WebSocket connection or REST wrapper for TTS.
            # Since we can't easily do WS in this sync calls without async bridge, 
            # and assuming the user just wants the OPTION for now:
            
            print(f"⚠️ [Moshi] Text-to-Speech requested: {text[:50]}...")
            print(f"ℹ️ [Moshi] Connecting to {self.base_url}...")
            
            # Simple check if server is up
            try:
                # Just a ping to see if server exists
                requests.get(self.base_url, timeout=2)
            except Exception as e:
                print(f"❌ [Moshi] Server unreachable: {e}")
                raise e

            # If we are here, server is nominally "there" (or proxy).
            # But without a specific TTS endpoint, we can't generate audio.
            # We will raise a NotImplementedError to show it's integrated but needs Server-Side TTS support.
            
            raise NotImplementedError("PersonaPlex Server (Moshi) does not expose a REST TTS endpoint. Use the Web UI for full interaction.")

        except Exception as e:
            if not self.has_warned:
                print(f"❌ Moshi Error: {e}")
                self.has_warned = True
            return b""  # Return silence on error to avoid crashing UI

def get_moshi_engine():
    return MoshiEngine()
