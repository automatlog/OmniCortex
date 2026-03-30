"""
Conversation Gate — validates caller input against what the agent asked for.

Tracks what the agent (Moshi/PersonaPlex) is expecting from the caller
(phone number, DOB, yes/no confirmation, etc.) and validates the caller's
ASR transcript before allowing the conversation to continue.

Integrated into mode_personaplex.py's reasoner_loop.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Input validators ─────────────────────────────────────────────────

_PHONE_RE = re.compile(r"\b(\d[\d\s\-]{8,}\d)\b")
_DOB_RE = re.compile(
    r"\b(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}|"
    r"\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{2,4})\b",
    re.IGNORECASE,
)
_YES_RE = re.compile(
    r"\b(yes|yeah|yep|correct|right|sure|confirm|okay|ok|haan|ji)\b",
    re.IGNORECASE,
)
_NO_RE = re.compile(
    r"\b(no|nope|nah|wrong|incorrect|not right|nahin|nahi)\b",
    re.IGNORECASE,
)
_MONTH_WORDS = {
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
}


# ── What the agent is currently expecting ────────────────────────────

class ExpectedInput:
    """What kind of input the agent is waiting for."""
    NONE = "none"
    PHONE = "phone"
    DOB = "dob"
    CONFIRMATION = "confirmation"     # yes/no
    ACCOUNT_NUMBER = "account_number"
    FREE_TEXT = "free_text"           # any response moves forward


# ── Agent output → expected input detection ──────────────────────────

_EXPECT_PATTERNS = [
    (ExpectedInput.PHONE, re.compile(
        r"(mobile|phone|number|registered.*number|contact)", re.IGNORECASE)),
    (ExpectedInput.DOB, re.compile(
        r"(date of birth|dob|birthday|birth date)", re.IGNORECASE)),
    (ExpectedInput.ACCOUNT_NUMBER, re.compile(
        r"(account\s*number|account\s*id|customer\s*id)", re.IGNORECASE)),
    (ExpectedInput.CONFIRMATION, re.compile(
        r"(is that correct|right\??|confirm|correct\??|shall I|would you like|do you want)",
        re.IGNORECASE)),
]


@dataclass
class ValidationResult:
    """Result of validating caller input."""
    valid: bool = False
    extracted_value: str = ""
    confirmation_text: str = ""     # spoken back to caller before agent continues
    retry_prompt: str = ""          # spoken if input is invalid


@dataclass
class ConversationGate:
    """Per-session gate that validates caller input before allowing agent to continue.

    Flow:
    1. Agent speaks a sentence → gate detects what input is expected
    2. Caller speaks → ASR transcribes → gate validates
    3. If valid: confirmation injected, conversation continues
    4. If invalid: retry prompt injected, agent waits again
    """
    expecting: str = ExpectedInput.NONE
    collected: Dict[str, str] = field(default_factory=dict)
    caller_turns: int = 0
    agent_last_sentence: str = ""
    waiting_for_input: bool = False
    retry_count: int = 0
    max_retries: int = 2

    def on_agent_sentence(self, sentence: str):
        """Called when the agent (Moshi/PersonaPlex) produces a complete sentence.

        Detects what input the agent is asking for and sets the gate.
        """
        self.agent_last_sentence = sentence
        lower = sentence.lower()

        # Check if this sentence is asking for specific input
        for expected_type, pattern in _EXPECT_PATTERNS:
            if pattern.search(lower):
                self.expecting = expected_type
                self.waiting_for_input = True
                self.retry_count = 0
                logger.info("Gate: expecting %s (from: %.50s)", expected_type, sentence)
                return

        # If agent says "thank you" / "let me check" after collecting input, release gate
        if any(w in lower for w in ["thank you", "let me check", "one moment", "verified"]):
            self.waiting_for_input = False
            self.expecting = ExpectedInput.NONE

    def validate_caller_input(self, transcript: str) -> ValidationResult:
        """Validate the caller's ASR transcript against what we're expecting.

        Returns ValidationResult with confirmation or retry prompt.
        """
        self.caller_turns += 1
        text = transcript.strip()
        if not text:
            return ValidationResult()

        # If not waiting for specific input, just pass through
        if not self.waiting_for_input or self.expecting == ExpectedInput.NONE:
            return ValidationResult(valid=True)

        result = ValidationResult()

        if self.expecting == ExpectedInput.PHONE:
            result = self._validate_phone(text)
        elif self.expecting == ExpectedInput.DOB:
            result = self._validate_dob(text)
        elif self.expecting == ExpectedInput.CONFIRMATION:
            result = self._validate_confirmation(text)
        elif self.expecting == ExpectedInput.ACCOUNT_NUMBER:
            result = self._validate_account(text)
        elif self.expecting == ExpectedInput.FREE_TEXT:
            result = ValidationResult(valid=True, extracted_value=text)

        if result.valid:
            self.waiting_for_input = False
            self.expecting = ExpectedInput.NONE
            self.retry_count = 0
            if result.extracted_value:
                entity_key = self.expecting if self.expecting != ExpectedInput.NONE else "text"
                self.collected[entity_key] = result.extracted_value
            logger.info("Gate: input VALID — %s = %s", self.expecting, result.extracted_value[:30] if result.extracted_value else "ok")
        else:
            self.retry_count += 1
            if self.retry_count > self.max_retries:
                # Give up waiting, let conversation flow
                self.waiting_for_input = False
                self.expecting = ExpectedInput.NONE
                logger.info("Gate: max retries reached, releasing gate")
                result.valid = True
            else:
                logger.info("Gate: input INVALID (retry %d/%d)", self.retry_count, self.max_retries)

        return result

    def is_blocking(self) -> bool:
        """True if the gate is waiting for caller input and should suppress agent output."""
        return self.waiting_for_input

    def _validate_phone(self, text: str) -> ValidationResult:
        # Try structured match first
        match = _PHONE_RE.search(text.replace(" ", ""))
        if match:
            phone = re.sub(r"[\s\-]", "", match.group(1))
            return ValidationResult(
                valid=True,
                extracted_value=phone,
                confirmation_text=f"I have your number as {phone}.",
            )
        # Try extracting digits from spoken text
        digits = re.sub(r"[^\d]", "", text)
        if len(digits) >= 10:
            phone = digits[-10:]
            return ValidationResult(
                valid=True,
                extracted_value=phone,
                confirmation_text=f"I have your number as {phone}.",
            )
        return ValidationResult(
            valid=False,
            retry_prompt="I couldn't catch that. Could you please repeat your mobile number?",
        )

    def _validate_dob(self, text: str) -> ValidationResult:
        match = _DOB_RE.search(text)
        if match:
            dob = match.group(1)
            return ValidationResult(
                valid=True,
                extracted_value=dob,
                confirmation_text=f"Date of birth noted as {dob}.",
            )
        # Check for spoken month names
        lower = text.lower()
        if any(m in lower for m in _MONTH_WORDS):
            return ValidationResult(
                valid=True,
                extracted_value=text.strip(),
                confirmation_text="Date of birth noted.",
            )
        # Check for digit sequences that look like dates
        digits = re.findall(r"\d+", text)
        if len(digits) >= 2:
            return ValidationResult(
                valid=True,
                extracted_value=text.strip(),
                confirmation_text="Date of birth noted.",
            )
        return ValidationResult(
            valid=False,
            retry_prompt="I couldn't catch your date of birth. Could you please say it again?",
        )

    def _validate_confirmation(self, text: str) -> ValidationResult:
        if _YES_RE.search(text):
            return ValidationResult(valid=True, extracted_value="yes")
        if _NO_RE.search(text):
            return ValidationResult(valid=True, extracted_value="no")
        return ValidationResult(
            valid=False,
            retry_prompt="Sorry, I didn't catch that. Could you say yes or no?",
        )

    def _validate_account(self, text: str) -> ValidationResult:
        digits = re.sub(r"[^\d]", "", text)
        if len(digits) >= 8:
            return ValidationResult(
                valid=True,
                extracted_value=digits,
                confirmation_text=f"Account number noted as {digits}.",
            )
        return ValidationResult(
            valid=False,
            retry_prompt="I couldn't catch your account number. Could you please repeat it?",
        )
