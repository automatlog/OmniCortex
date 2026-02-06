"""
LiquidAI Voice Engine
End-to-end speech-to-speech using LFM2.5-Audio-1.5B
"""
import os
import io
import torch
import torchaudio
from typing import Optional, Generator, Tuple
from dataclasses import dataclass
from threading import Lock

# LiquidAI imports (install: pip install liquid-audio)
try:
    from liquid_audio import LFM2AudioModel, LFM2AudioProcessor, ChatState, LFMModality
    LIQUID_AVAILABLE = True
except ImportError:
    LIQUID_AVAILABLE = False
    print("[WARN] liquid-audio not installed. Run: pip install liquid-audio")


@dataclass
class VoiceResponse:
    """Response from voice processing"""
    text: str
    audio_bytes: bytes
    sample_rate: int = 24000
    duration_ms: float = 0.0


class LiquidVoiceEngine:
    """
    End-to-end voice chat using LiquidAI LFM2.5-Audio-1.5B
    
    Features:
    - Speech-to-speech in single model (no separate ASR/TTS)
    - Multi-turn conversation support
    - Low latency (~200-300ms)
    - ~4-6GB VRAM per instance
    """
    
    _instances: dict = {}
    _lock = Lock()
    
    def __init__(
        self, 
        model_id: str = "LiquidAI/LFM2.5-Audio-1.5B",
        device: str = "cuda",
        max_instances: int = 8
    ):
        self.model_id = model_id
        self.device = device
        self.max_instances = max_instances
        self.processor = None
        self.model = None
        self._loaded = False
        
    def load(self):
        """Load model (lazy loading)"""
        if self._loaded:
            return
            
        if not LIQUID_AVAILABLE:
            raise RuntimeError("liquid-audio package not installed")
        
        print(f"[LiquidVoice] Loading {self.model_id}...")
        self.processor = LFM2AudioProcessor.from_pretrained(self.model_id).eval()
        self.model = LFM2AudioModel.from_pretrained(self.model_id).eval()
        
        if self.device == "cuda" and torch.cuda.is_available():
            self.model = self.model.to(self.device)
        
        self._loaded = True
        print(f"[LiquidVoice] Model loaded on {self.device}")
    
    def unload(self):
        """Unload model to free VRAM"""
        if self._loaded:
            del self.model
            del self.processor
            torch.cuda.empty_cache()
            self._loaded = False
            print("[LiquidVoice] Model unloaded")
    
    def transcribe_and_respond(
        self,
        audio_bytes: bytes,
        system_prompt: str = "You are a helpful assistant. Respond with interleaved text and audio.",
        conversation_history: list = None,
        max_new_tokens: int = 512,
        audio_temperature: float = 1.0,
        audio_top_k: int = 4
    ) -> VoiceResponse:
        """
        Process audio input and generate audio + text response.
        
        Args:
            audio_bytes: Input audio as bytes (WAV format)
            system_prompt: System prompt for the agent
            conversation_history: Previous turns [(role, content), ...]
            max_new_tokens: Maximum tokens to generate
            audio_temperature: Temperature for audio generation
            audio_top_k: Top-k for audio generation
            
        Returns:
            VoiceResponse with text and audio bytes
        """
        if not self._loaded:
            self.load()
        
        # Load audio
        audio_buffer = io.BytesIO(audio_bytes)
        waveform, sample_rate = torchaudio.load(audio_buffer)
        
        # Resample if needed (model expects 16kHz input)
        if sample_rate != 16000:
            resampler = torchaudio.transforms.Resample(sample_rate, 16000)
            waveform = resampler(waveform)
        
        # Build chat state
        chat = ChatState(self.processor)
        
        # System prompt
        chat.new_turn("system")
        chat.add_text(system_prompt)
        chat.end_turn()
        
        # Add conversation history
        if conversation_history:
            for role, content in conversation_history:
                chat.new_turn(role)
                if isinstance(content, str):
                    chat.add_text(content)
                else:
                    # Audio content (tensor)
                    chat.add_audio(content, 16000)
                chat.end_turn()
        
        # Add current user audio
        chat.new_turn("user")
        chat.add_audio(waveform, 16000)
        chat.end_turn()
        
        # Generate response
        chat.new_turn("assistant")
        
        text_tokens = []
        audio_tokens = []
        
        for token in self.model.generate_interleaved(
            **chat,
            max_new_tokens=max_new_tokens,
            audio_temperature=audio_temperature,
            audio_top_k=audio_top_k
        ):
            if token.numel() == 1:
                # Text token
                text_tokens.append(token)
            else:
                # Audio token
                audio_tokens.append(token)
        
        # Decode text
        text_output = ""
        if text_tokens:
            text_tensor = torch.stack(text_tokens, dim=0)
            text_output = self.processor.text.decode(text_tensor.flatten())
        
        # Decode audio (remove end token)
        audio_bytes_out = b""
        if len(audio_tokens) > 1:
            audio_codes = torch.stack(audio_tokens[:-1], 1).unsqueeze(0)
            waveform_out = self.processor.decode(audio_codes)
            
            # Convert to bytes
            buffer = io.BytesIO()
            torchaudio.save(buffer, waveform_out.cpu(), 24000, format="wav")
            audio_bytes_out = buffer.getvalue()
        
        return VoiceResponse(
            text=text_output,
            audio_bytes=audio_bytes_out,
            sample_rate=24000,
            duration_ms=len(audio_tokens) * 10  # Approximate
        )
    
    def text_to_speech(
        self,
        text: str,
        max_new_tokens: int = 256
    ) -> bytes:
        """
        Convert text to speech.
        
        Args:
            text: Text to synthesize
            max_new_tokens: Maximum audio tokens
            
        Returns:
            Audio as WAV bytes
        """
        if not self._loaded:
            self.load()
        
        chat = ChatState(self.processor)
        
        chat.new_turn("system")
        chat.add_text("Respond with audio.")
        chat.end_turn()
        
        chat.new_turn("user")
        chat.add_text(text)
        chat.end_turn()
        
        chat.new_turn("assistant")
        
        audio_tokens = []
        for token in self.model.generate_interleaved(
            **chat,
            max_new_tokens=max_new_tokens,
            audio_temperature=1.0,
            audio_top_k=4
        ):
            if token.numel() > 1:
                audio_tokens.append(token)
        
        if len(audio_tokens) > 1:
            audio_codes = torch.stack(audio_tokens[:-1], 1).unsqueeze(0)
            waveform = self.processor.decode(audio_codes)
            
            buffer = io.BytesIO()
            torchaudio.save(buffer, waveform.cpu(), 24000, format="wav")
            return buffer.getvalue()
        
        return b""
    
    def speech_to_text(
        self,
        audio_bytes: bytes
    ) -> str:
        """
        Transcribe audio to text (ASR mode).
        
        Args:
            audio_bytes: Input audio as WAV bytes
            
        Returns:
            Transcribed text
        """
        if not self._loaded:
            self.load()
        
        audio_buffer = io.BytesIO(audio_bytes)
        waveform, sample_rate = torchaudio.load(audio_buffer)
        
        if sample_rate != 16000:
            resampler = torchaudio.transforms.Resample(sample_rate, 16000)
            waveform = resampler(waveform)
        
        chat = ChatState(self.processor)
        
        chat.new_turn("system")
        chat.add_text("Transcribe the following audio.")
        chat.end_turn()
        
        chat.new_turn("user")
        chat.add_audio(waveform, 16000)
        chat.end_turn()
        
        chat.new_turn("assistant")
        
        text_tokens = []
        for token in self.model.generate_interleaved(
            **chat,
            max_new_tokens=256,
            audio_temperature=1.0,
            audio_top_k=4
        ):
            if token.numel() == 1:
                text_tokens.append(token)
        
        if text_tokens:
            text_tensor = torch.stack(text_tokens, dim=0)
            return self.processor.text.decode(text_tensor.flatten())
        
        return ""


# Singleton instance
_voice_engine: Optional[LiquidVoiceEngine] = None


def get_voice_engine() -> LiquidVoiceEngine:
    """Get or create the voice engine singleton"""
    global _voice_engine
    if _voice_engine is None:
        _voice_engine = LiquidVoiceEngine(
            model_id=os.getenv("VOICE_MODEL", "LiquidAI/LFM2.5-Audio-1.5B"),
            device="cuda" if torch.cuda.is_available() else "cpu",
            max_instances=int(os.getenv("VOICE_MAX_INSTANCES", "8"))
        )
    return _voice_engine
