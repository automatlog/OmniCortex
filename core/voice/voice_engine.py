"""
OmniCortex Voice Engine
Unified interface for Speech-to-Text (STT), Text-to-Speech (TTS), and Voice Conversion (STS).
Powered exclusively by ElevenLabs.
"""
import io
import os
import streamlit as st
from pathlib import Path
from core.config import ELEVENLABS_API_KEY
from core.voice.moshi_engine import get_moshi_engine

class ElevenLabsEngine:
    """
    Unified ElevenLabs Engine:
    - STT: Scribe v2
    - TTS: ElevenLabs Multilingual v2
    - STS: Voice Conversion v2
    """
    
    def __init__(self):
        if not ELEVENLABS_API_KEY:
            raise ValueError("ELEVENLABS_API_KEY not found. Please set it in .env")
        try:
            from elevenlabs.client import ElevenLabs
            self.client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
        except ImportError:
            raise ImportError("elevenlabs package not installed. Run: uv add elevenlabs")

    # --- Speech-to-Text (Transcribe) ---
    def transcribe(self, audio_file, model_id: str = "scribe_v2") -> str:
        """
        Transcribe audio using ElevenLabs Scribe.
        accepts: file-like object or path string.
        """
        try:
            # If string path, open it
            if isinstance(audio_file, (str, Path)):
                if not os.path.exists(audio_file):
                    raise FileNotFoundError(f"Audio file not found: {audio_file}")
                with open(audio_file, "rb") as f:
                    transcript = self.client.speech_to_text.convert(
                        file=f,
                        model_id=model_id
                    )
            else:
                # Assume file-like (bytesIO)
                transcript = self.client.speech_to_text.convert(
                    file=audio_file,
                    model_id=model_id
                )
            
            return transcript.text
            
        except Exception as e:
            print(f"❌ ElevenLabs STT Error: {e}")
            raise e

    # --- Text-to-Speech (Speak) ---
    def speak(self, text: str, voice_id: str = "JBFqnCBsd6RMkjVDRZzb", model_id: str = "eleven_multilingual_v2") -> bytes:
        """
        Convert text to speech.
        Default Voice: George (JBFqnCBsd6RMkjVDRZzb)
        """
        try:
            audio_generator = self.client.text_to_speech.convert(
                text=text,
                voice_id=voice_id,
                model_id=model_id,
                output_format="mp3_44100_128",
            )
            return b"".join(audio_generator)
        except Exception as e:
            print(f"❌ ElevenLabs TTS Error: {e}")
            return b""

    # --- Speech-to-Speech (Voice Conversion) ---
    def voice_conversion(self, audio: bytes, voice_id: str = "JBFqnCBsd6RMkjVDRZzb") -> bytes:
        """
        Convert input audio voice to target voice.
        """
        try:
            audio_generator = self.client.speech_to_speech.convert(
                voice_id=voice_id,
                audio=audio,
                model_id="eleven_multilingual_sts_v2",
                output_format="mp3_44100_128"
            )
            return b"".join(audio_generator)
        except Exception as e:
            print(f"❌ ElevenLabs STS Error: {e}")
            return b""


# Singleton Accessor
@st.cache_resource
def get_engine():
    return ElevenLabsEngine()

# --- Wrapper Functions (for backward compatibility imports) ---

def transcribe_audio(audio_source) -> str:
    """Wrapper for STT"""
    engine = get_engine()
    return engine.transcribe(audio_source)

def speak(text: str, voice: str = None) -> bytes:
    """Wrapper for TTS"""
    engine = get_engine()
    # If voice is None, engine uses default
    if voice:
        if voice.upper() in ["PERSONAPLEX", "MOSHI", "NVIDIA/PERSONAPLEX"]:
            return get_moshi_engine().speak(text)
        return engine.speak(text, voice_id=voice)
    return engine.speak(text)

def voice_conversion(audio_bytes: bytes, voice_id: str = None) -> bytes:
    """Wrapper for STS"""
    engine = get_engine()
    target = voice_id or "JBFqnCBsd6RMkjVDRZzb"
    return engine.voice_conversion(audio_bytes, voice_id=target)
