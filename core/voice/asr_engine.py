"""
ASR Engine — async singleton wrapper around faster-whisper.
Blocking transcription runs in a thread executor.
"""
import asyncio
import logging
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

    def _load(self):
        if self._model is not None:
            return
        from faster_whisper import WhisperModel

        compute_type = "float16" if self.device == "cuda" else "int8"
        logger.info("Loading faster-whisper model=%s device=%s compute=%s", self.model_size, self.device, compute_type)
        self._model = WhisperModel(self.model_size, device=self.device, compute_type=compute_type)
        logger.info("faster-whisper loaded")

    def _transcribe_sync(self, pcm_float32: np.ndarray, sample_rate: int) -> Tuple[str, float]:
        """Blocking transcription — must be called via run_in_executor."""
        self._load()
        # faster-whisper expects float32 numpy at any sample rate (internally resamples to 16kHz)
        segments, info = self._model.transcribe(pcm_float32, beam_size=3, language="en")
        text_parts = []
        total_prob = 0.0
        count = 0
        for seg in segments:
            text_parts.append(seg.text.strip())
            total_prob += seg.avg_log_prob
            count += 1
        text = " ".join(text_parts).strip()
        confidence = (total_prob / count) if count > 0 else 0.0
        return text, confidence

    async def transcribe(self, pcm_float32: np.ndarray, sample_rate: int = 16000) -> Tuple[str, float]:
        """Async transcription — runs blocking model in executor."""
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
