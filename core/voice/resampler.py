"""
Audio resampling and PCM conversion utilities for the voice pipeline.
Extracted from ws_bridge.py pattern — torch Resample with numpy fallback.
"""
import numpy as np

try:
    import torch
    import torchaudio.transforms as T
except ImportError:
    torch = None
    T = None


class Resampler:
    """Resample PCM float32 audio between sample rates."""

    def __init__(self, src_rate: int, dst_rate: int):
        self.src_rate = src_rate
        self.dst_rate = dst_rate
        self._resampler = None

        if src_rate == dst_rate:
            return
        if torch is not None and T is not None:
            self._resampler = T.Resample(src_rate, dst_rate)

    def run(self, pcm: np.ndarray) -> np.ndarray:
        if pcm.size == 0 or self.src_rate == self.dst_rate:
            return pcm.astype(np.float32, copy=False)

        if self._resampler is not None and torch is not None:
            tensor = torch.from_numpy(pcm.astype(np.float32, copy=False)).unsqueeze(0)
            out = self._resampler(tensor).squeeze(0).detach().cpu().numpy()
            return out.astype(np.float32, copy=False)

        # Numpy fallback: linear interpolation
        in_len = pcm.shape[0]
        out_len = int(round(in_len * self.dst_rate / self.src_rate))
        if out_len <= 1 or in_len <= 1:
            return pcm.astype(np.float32, copy=False)
        x_old = np.linspace(0.0, 1.0, num=in_len, dtype=np.float64)
        x_new = np.linspace(0.0, 1.0, num=out_len, dtype=np.float64)
        out = np.interp(x_new, x_old, pcm.astype(np.float64))
        return out.astype(np.float32)


def pcm16_bytes_to_float32(audio_bytes: bytes) -> np.ndarray:
    """Convert PCM16 little-endian bytes to float32 [-1.0, 1.0]."""
    int16_audio = np.frombuffer(audio_bytes, dtype=np.int16)
    if int16_audio.size == 0:
        return np.zeros((0,), dtype=np.float32)
    return (int16_audio.astype(np.float32) / 32768.0).astype(np.float32)


def float32_to_pcm16_bytes(audio: np.ndarray) -> bytes:
    """Convert float32 [-1.0, 1.0] to PCM16 little-endian bytes."""
    if audio.size == 0:
        return b""
    clipped = np.clip(audio, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16).tobytes()
