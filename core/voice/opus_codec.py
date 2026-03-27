"""
Opus encode/decode wrapper using sphn — the same library PersonaPlex server uses.

PersonaPlex server.py uses sphn.OpusStreamWriter/Reader for all audio I/O on
the WebSocket. Kind=1 frames contain Opus-encoded audio, NOT raw PCM.
This codec ensures mode_personaplex.py speaks the correct wire format.

If sphn is not installed, falls back to raw PCM passthrough with a warning.
This fallback only works with local non-Opus test servers.
"""
import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import sphn
    SPHN_AVAILABLE = True
except ImportError:
    SPHN_AVAILABLE = False
    logger.warning(
        "sphn not installed — Opus codec unavailable. "
        "PersonaPlex mode will send raw PCM (only works with non-Opus servers). "
        "Install: pip install sphn"
    )


class OpusCodec:
    """
    Opus stream encoder/decoder using sphn.

    Usage:
        codec = OpusCodec(sample_rate=24000)
        # Encode: float32 PCM -> Opus bytes
        opus_bytes = codec.encode(pcm_float32)
        # Decode: Opus bytes -> float32 PCM
        pcm_float32 = codec.decode(opus_bytes)
    """

    def __init__(self, sample_rate: int = 24000):
        self.sample_rate = sample_rate
        self._writer: Optional[object] = None
        self._reader: Optional[object] = None

        if SPHN_AVAILABLE:
            self._writer = sphn.OpusStreamWriter(sample_rate)
            self._reader = sphn.OpusStreamReader(sample_rate)
        else:
            logger.warning("OpusCodec created without sphn — using raw PCM passthrough")

    def encode(self, pcm_float32: np.ndarray) -> bytes:
        """Encode float32 PCM audio to Opus bytes."""
        if self._writer is None:
            # Fallback: convert float32 to PCM16 bytes (raw, not Opus)
            return (np.clip(pcm_float32, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        self._writer.append_pcm(pcm_float32)
        return self._writer.read_bytes()

    def decode(self, opus_bytes: bytes) -> np.ndarray:
        """Decode Opus bytes to float32 PCM audio."""
        if self._reader is None:
            # Fallback: treat as raw PCM16 bytes
            return np.frombuffer(opus_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        self._reader.append_bytes(opus_bytes)
        return self._reader.read_pcm()

    @property
    def is_opus(self) -> bool:
        """True if real Opus encoding is available."""
        return SPHN_AVAILABLE and self._writer is not None
