"""
ASR Engine — async singleton wrapper around faster-whisper.
Blocking transcription runs in a thread executor.
"""
import asyncio
import logging
import math
import threading
from typing import Optional, Tuple

import numpy as np

from core.config import VOICE_ASR_MODEL, VOICE_ASR_DEVICE

logger = logging.getLogger(__name__)

_asr_engine: Optional["ASREngine"] = None
_asr_lock = asyncio.Lock()


class ASREngine:
    """Thread-safe faster-whisper transcription engine."""

    def __init__(self, model_size: str = VOICE_ASR_MODEL, device: str = VOICE_ASR_DEVICE):
        self.model_size = model_size
        self.device = device
        self._model = None
        self._load_lock = threading.Lock()

    def _load(self):
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            from faster_whisper import WhisperModel

            compute_type = "float16" if self.device == "cuda" else "int8"
            logger.info("Loading faster-whisper model=%s device=%s compute=%s", self.model_size, self.device, compute_type)
            self._model = WhisperModel(self.model_size, device=self.device, compute_type=compute_type)
            logger.info("faster-whisper loaded")

    @staticmethod
    def _resample_to_16k(pcm_float32: np.ndarray, sample_rate: int) -> np.ndarray:
        if sample_rate == 16000 or pcm_float32.size == 0:
            return pcm_float32.astype(np.float32, copy=False)
        if sample_rate <= 0:
            return pcm_float32.astype(np.float32, copy=False)

        try:
            from scipy.signal import resample_poly  # type: ignore

            ratio = math.gcd(sample_rate, 16000)
            up = 16000 // ratio
            down = sample_rate // ratio
            return resample_poly(pcm_float32, up, down).astype(np.float32, copy=False)
        except Exception:
            n_out = int(len(pcm_float32) * 16000 / sample_rate)
            if n_out <= 0:
                return np.array([], dtype=np.float32)
            idx = np.linspace(0, len(pcm_float32) - 1, n_out)
            left = np.floor(idx).astype(int)
            right = np.clip(left + 1, 0, len(pcm_float32) - 1)
            frac = (idx - left).astype(np.float32)
            return (pcm_float32[left] * (1.0 - frac) + pcm_float32[right] * frac).astype(np.float32)

    def _transcribe_sync(self, pcm_float32: np.ndarray, sample_rate: int) -> Tuple[str, float, str]:
        """Blocking transcription — must be called via run_in_executor.

        Returns (text, confidence, detected_language).
        Confidence is average log probability; NaN if no segments produced.
        detected_language is ISO 639-1 code (e.g. "en", "hi", "gu").
        """
        self._load()
        audio_input = self._resample_to_16k(pcm_float32, sample_rate)
        # Use language=None for auto-detection when multilingual model is loaded
        # For English-only models (e.g. "base.en"), language is always "en"
        is_multilingual = not self.model_size.endswith(".en")
        lang_param = None if is_multilingual else "en"
        segments, info = self._model.transcribe(audio_input, beam_size=3, language=lang_param)
        text_parts = []
        total_prob = 0.0
        count = 0
        for seg in segments:
            text_parts.append(seg.text.strip())
            total_prob += seg.avg_log_prob
            count += 1
        text = " ".join(text_parts).strip()
        confidence = (total_prob / count) if count > 0 else math.nan
        detected_lang = getattr(info, "language", "en") or "en"
        return text, confidence, detected_lang

    async def transcribe(self, pcm_float32: np.ndarray, sample_rate: int = 16000) -> Tuple[str, float, str]:
        """Async transcription — runs blocking model in executor.

        Returns (text, confidence, detected_language).
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._transcribe_sync, pcm_float32, sample_rate)


async def get_asr_engine() -> ASREngine:
    """Double-checked locking singleton for the ASR engine."""
    global _asr_engine
    if _asr_engine is not None:
        return _asr_engine
    async with _asr_lock:
        if _asr_engine is not None:
            return _asr_engine
        _asr_engine = ASREngine()
        return _asr_engine
