"""
Vocoder Engine — async singleton for BigVGAN v2 mel-to-audio synthesis.
Falls back to LFM2.5 text_to_speech() when mel spectrogram TTS is not available.
"""
import asyncio
import logging
import threading
from typing import Optional

import numpy as np

from core.config import VOICE_VOCODER_DEVICE

logger = logging.getLogger(__name__)

_vocoder_engine: Optional["VocoderEngine"] = None
_vocoder_lock = asyncio.Lock()


class VocoderEngine:
    """BigVGAN v2 vocoder — converts mel spectrograms to audio waveforms."""

    OUTPUT_RATE = 22050  # BigVGAN v2 output sample rate

    def __init__(self, device: str = VOICE_VOCODER_DEVICE):
        self.device = device
        self._model = None
        self._load_lock = threading.Lock()
        self._load_failed = False

    def _load(self):
        if self._model is not None:
            return
        if self._load_failed:
            raise RuntimeError("BigVGAN model unavailable from previous load failure")
        with self._load_lock:
            if self._model is not None:
                return
            if self._load_failed:
                raise RuntimeError("BigVGAN model unavailable from previous load failure")
            try:
                import torch
                from bigvgan import BigVGAN as BigVGANModel

                logger.info("Loading BigVGAN v2 on %s", self.device)
                self._model = BigVGANModel.from_pretrained(
                    "nvidia/bigvgan_v2_22khz_80band_256x",
                    use_cuda_kernel=False,
                )
                self._model = self._model.to(self.device).eval()
                self._load_failed = False
                logger.info("BigVGAN v2 loaded")
            except Exception as exc:
                self._model = None
                self._load_failed = True
                logger.warning("BigVGAN v2 unavailable (%s) — will use LFM2.5 TTS fallback", exc)
                raise RuntimeError("BigVGAN model unavailable") from exc

    def _synthesize_sync(self, mel: "torch.Tensor") -> np.ndarray:
        """Blocking mel-to-waveform — call via run_in_executor."""
        import torch

        self._load()
        if self._model is None:
            raise RuntimeError("BigVGAN model not loaded")
        with torch.no_grad():
            if mel.dim() == 2:
                mel = mel.unsqueeze(0)
            mel = mel.to(self.device)
            wav = self._model(mel).squeeze(0).squeeze(0).cpu().numpy()
        return wav.astype(np.float32)

    async def synthesize(self, mel) -> np.ndarray:
        """Async mel-to-waveform."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._synthesize_sync, mel)

    async def tts_to_audio(self, text: str) -> Optional[bytes]:
        """
        Text-to-speech via LFM2.5 fallback.
        Returns PCM16 bytes at the LFM output rate, or None on failure.
        """
        try:
            from core.voice.liquid_voice import get_voice_engine

            engine = get_voice_engine()
            loop = asyncio.get_running_loop()
            audio_bytes = await loop.run_in_executor(None, engine.text_to_speech, text)
            return audio_bytes
        except Exception as exc:
            logger.error("TTS fallback failed: %s", exc)
            return None


async def get_vocoder_engine() -> VocoderEngine:
    """Double-checked locking singleton."""
    global _vocoder_engine
    if _vocoder_engine is not None:
        return _vocoder_engine
    async with _vocoder_lock:
        if _vocoder_engine is not None:
            return _vocoder_engine
        _vocoder_engine = VocoderEngine()
        return _vocoder_engine
