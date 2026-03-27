"""
Voice Pipeline Protocol — shared types and constants for all voice modes.
"""
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# =============================================================================
# ENUMS
# =============================================================================

class VoiceMode(str, Enum):
    PERSONAPLEX = "personaplex"
    LFM = "lfm"
    CASCADE = "cascade"


class SessionState(str, Enum):
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    IDLE = "idle"


# =============================================================================
# SESSION
# =============================================================================

@dataclass
class VoiceSession:
    agent_id: str
    mode: VoiceMode
    user_id: Optional[str] = None
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    sample_rate: int = 8000
    voice_prompt: str = "NATF0.pt"
    text_prompt: str = ""
    state: SessionState = SessionState.IDLE
    system_prompt: str = ""
    agent_name: str = ""
    model_selection: Optional[str] = None


# =============================================================================
# SAMPLE RATE CONSTANTS
# =============================================================================

GATEWAY_RATE = 8000          # Gateway / telephony PCM rate
PERSONAPLEX_RATE = 24000     # PersonaPlex native rate
LFM_INPUT_RATE = 16000       # LFM2.5 expects 16 kHz input
BIGVGAN_OUTPUT_RATE = 22050  # BigVGAN v2 output rate


# =============================================================================
# WEBSOCKET MESSAGE TYPES
# =============================================================================

MSG_TRANSCRIPT = "transcript"
MSG_ANSWER = "answer"
MSG_STATUS = "status"
MSG_ERROR = "error"
MSG_SESSION = "session"
MSG_CONTROL = "control"
