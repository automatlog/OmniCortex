"""
OmniCortex Voice Engine
Unified interface for Speech-to-Text (STT) and Text-to-Speech (TTS).
Powered exclusively by PersonaPlex (Moshi).
"""
import streamlit as st
from core.config import MOSHI_ENABLED, PERSONAPLEX_URL
from core.voice.moshi_engine import get_moshi_engine


class MoshiVoiceEngine:
    """
    Moshi-only voice engine
    """
    
    def __init__(self):
        if not MOSHI_ENABLED:
            raise ValueError("❌ Moshi is disabled. Set MOSHI_ENABLED=true in .env")
        
        self.engine = get_moshi_engine()
        print(f"✅ Moshi Voice Engine initialized at {PERSONAPLEX_URL}")

    def transcribe(self, audio_file) -> str:
        """
        Transcribe audio using Moshi
        Note: Moshi is primarily audio-to-audio, so transcription is limited
        """
        print("⚠️ [Moshi] Transcription requested")
        print("ℹ️ [Moshi] For best results, use the Moshi Web UI for voice interaction")
        return "[Moshi: Use Web UI for full voice interaction]"

    def speak(self, text: str, voice: str = None) -> bytes:
        """
        Convert text to speech using Moshi
        """
        return self.engine.speak(text)

    def voice_conversion(self, audio_bytes: bytes, voice_id: str = None) -> bytes:
        """
        Moshi doesn't support voice conversion
        """
        print("⚠️ [Moshi] Voice conversion not supported")
        return audio_bytes  # Return original


# Singleton Accessor
@st.cache_resource
def get_engine():
    return MoshiVoiceEngine()


# --- Wrapper Functions (for backward compatibility) ---

def transcribe_audio(audio_source) -> str:
    """Wrapper for STT"""
    engine = get_engine()
    return engine.transcribe(audio_source)

def speak(text: str, voice: str = None) -> bytes:
    """Wrapper for TTS"""
    engine = get_engine()
    return engine.speak(text, voice=voice)

def voice_conversion(audio_bytes: bytes, voice_id: str = None) -> bytes:
    """Wrapper for STS"""
    engine = get_engine()
    return engine.voice_conversion(audio_bytes, voice_id=voice_id)
