"""
Agent Router — decides when and where to transfer a voice call
between agents based on intent, sentiment, workflow state, and routing config.

Routing config lives in agent.logic["routing"] or agent.extra_data["routing"]:

    {
        "routing": {
            "transfer_rules": [
                {
                    "condition": "intent",
                    "intent": "complaint",
                    "target_agent_id": "escalation-agent-uuid",
                    "message": "Let me connect you with a specialist."
                },
                {
                    "condition": "intent",
                    "intent": "technical_help",
                    "target_agent_id": "tech-support-uuid",
                    "message": "Transferring you to technical support."
                },
                {
                    "condition": "sentiment",
                    "sentiment": "angry",
                    "min_score": 0.7,
                    "target_agent_id": "senior-agent-uuid",
                    "message": "I understand your frustration. Let me get a senior representative."
                },
                {
                    "condition": "keyword",
                    "keywords": ["manager", "supervisor", "human"],
                    "target_agent_id": "human-queue-uuid",
                    "message": "Connecting you with a manager now."
                },
                {
                    "condition": "language",
                    "language": "hi",
                    "target_agent_id": "hindi-agent-uuid",
                    "message": "Aapko Hindi mein madad ke liye transfer kar raha hoon."
                },
                {
                    "condition": "workflow_state",
                    "state": "farewell",
                    "target_agent_id": "survey-agent-uuid",
                    "message": "Before you go, would you mind a quick survey?"
                }
            ],
            "max_transfers_per_session": 3,
            "transfer_cooldown_s": 30
        }
    }
"""
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TransferDecision:
    """Result of a transfer evaluation."""
    should_transfer: bool = False
    target_agent_id: str = ""
    reason: str = ""
    message: str = ""               # spoken to caller before transfer
    rule_matched: str = ""          # which rule triggered


@dataclass
class TransferHistory:
    """Track transfers within a session to prevent loops."""
    transfers: List[Dict[str, Any]] = field(default_factory=list)
    last_transfer_time: float = 0.0

    def add(self, from_agent: str, to_agent: str, reason: str):
        self.transfers.append({
            "from": from_agent,
            "to": to_agent,
            "reason": reason,
            "time": time.monotonic(),
        })
        self.last_transfer_time = time.monotonic()

    @property
    def count(self) -> int:
        return len(self.transfers)


class AgentRouter:
    """Per-session agent router that evaluates transfer rules."""

    def __init__(self, routing_config: Optional[Dict] = None):
        self._rules: List[Dict] = []
        self._max_transfers: int = 3
        self._cooldown_s: float = 30.0
        self.transfer_history = TransferHistory()

        if routing_config and isinstance(routing_config, dict):
            self._rules = routing_config.get("transfer_rules", [])
            self._max_transfers = routing_config.get("max_transfers_per_session", 3)
            self._cooldown_s = routing_config.get("transfer_cooldown_s", 30.0)
            logger.info("AgentRouter loaded %d transfer rules", len(self._rules))

    @classmethod
    def from_agent(cls, agent: Optional[Dict]) -> "AgentRouter":
        """Create router from agent config. Returns no-op router if no routing defined."""
        if not agent:
            return cls()

        routing_cfg = None
        logic = agent.get("logic")
        if isinstance(logic, dict):
            routing_cfg = logic.get("routing")
        if not routing_cfg:
            extra = agent.get("extra_data")
            if isinstance(extra, dict):
                routing_cfg = extra.get("routing")

        return cls(routing_cfg)

    def has_rules(self) -> bool:
        return len(self._rules) > 0

    def evaluate(
        self,
        transcript: str,
        intent: str = "",
        sentiment: str = "",
        sentiment_score: float = 0.0,
        detected_language: str = "en",
        workflow_state: str = "",
        current_agent_id: str = "",
    ) -> TransferDecision:
        """Evaluate all transfer rules against current context.

        Returns TransferDecision with should_transfer=True if a rule matches.
        """
        # Guard: max transfers reached
        if self.transfer_history.count >= self._max_transfers:
            return TransferDecision()

        # Guard: cooldown period
        if self.transfer_history.last_transfer_time > 0:
            elapsed = time.monotonic() - self.transfer_history.last_transfer_time
            if elapsed < self._cooldown_s:
                return TransferDecision()

        for rule in self._rules:
            condition = rule.get("condition", "")
            target = rule.get("target_agent_id", "")
            message = rule.get("message", "")

            if not target:
                continue

            # Don't transfer to the current agent
            if target == current_agent_id:
                continue

            # Don't transfer back to an agent we already transferred from
            if any(t["from"] == target for t in self.transfer_history.transfers):
                continue

            matched = False
            reason = ""

            if condition == "intent" and intent:
                if intent == rule.get("intent", ""):
                    matched = True
                    reason = f"intent={intent}"

            elif condition == "keyword":
                keywords = rule.get("keywords", [])
                for kw in keywords:
                    if re.search(r"\b" + re.escape(kw) + r"\b", transcript, re.IGNORECASE):
                        matched = True
                        reason = f"keyword={kw}"
                        break

            elif condition == "sentiment" and sentiment:
                rule_sentiment = rule.get("sentiment", "")
                min_score = rule.get("min_score", 0.5)
                if sentiment == rule_sentiment and sentiment_score >= min_score:
                    matched = True
                    reason = f"sentiment={sentiment}({sentiment_score:.2f})"

            elif condition == "language" and detected_language:
                if detected_language == rule.get("language", ""):
                    matched = True
                    reason = f"language={detected_language}"

            elif condition == "workflow_state" and workflow_state:
                if workflow_state == rule.get("state", ""):
                    matched = True
                    reason = f"workflow_state={workflow_state}"

            if matched:
                logger.info("Transfer rule matched: %s -> agent %s (%s)",
                            condition, target[:8], reason)
                return TransferDecision(
                    should_transfer=True,
                    target_agent_id=target,
                    reason=reason,
                    message=message,
                    rule_matched=condition,
                )

        return TransferDecision()


# ── Sentiment analysis (lightweight, keyword-based) ──────────────────

_SENTIMENT_PATTERNS = {
    "angry": re.compile(
        r"\b(angry|furious|terrible|worst|horrible|disgusting|unacceptable|"
        r"stupid|useless|pathetic|sick of|fed up|ridiculous|absurd|outrageous|"
        r"damn|hell|pissed|suck|scam|fraud|cheat|liar|rubbish|trash)\b",
        re.IGNORECASE,
    ),
    "frustrated": re.compile(
        r"\b(frustrated|annoyed|irritated|disappointed|not happy|unhappy|"
        r"waste of time|again and again|same problem|still not|keep asking|"
        r"nobody helps|no one helps|don.?t understand|how many times)\b",
        re.IGNORECASE,
    ),
    "happy": re.compile(
        r"\b(thank you so much|excellent|wonderful|amazing|great job|"
        r"perfect|awesome|fantastic|brilliant|love it|appreciate|grateful|"
        r"very helpful|so helpful|best service)\b",
        re.IGNORECASE,
    ),
    "neutral": re.compile(r".*", re.DOTALL),  # fallback
}


def analyze_sentiment(transcript: str) -> tuple:
    """Simple keyword-based sentiment analysis.

    Returns (sentiment_label, confidence_score).
    """
    if not transcript or len(transcript.strip()) < 3:
        return "neutral", 0.0

    text = transcript.lower()

    # Count matches per category
    scores = {}
    for label, pattern in _SENTIMENT_PATTERNS.items():
        if label == "neutral":
            continue
        matches = pattern.findall(text)
        if matches:
            scores[label] = len(matches)

    if not scores:
        return "neutral", 0.5

    best = max(scores, key=scores.get)
    # Normalize confidence: more matches = higher confidence
    confidence = min(scores[best] / 3.0, 1.0)
    return best, confidence


# ── Entity extraction (simple pattern-based) ─────────────────────────

_ENTITY_PATTERNS = {
    "phone_number": re.compile(r"\b(\d{10}|\d{3}[-.\s]\d{3}[-.\s]\d{4})\b"),
    "account_number": re.compile(r"\b(\d{9,18})\b"),
    "email": re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"),
    "date": re.compile(
        r"\b(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}|"
        r"\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{2,4})\b",
        re.IGNORECASE,
    ),
    "amount": re.compile(r"(?:₹|rs\.?|inr|rupees?)\s*[\d,]+(?:\.\d{1,2})?", re.IGNORECASE),
    "name": re.compile(
        r"\b(?:my name is|i am|i'm|this is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b",
    ),
}


def extract_entities(transcript: str) -> Dict[str, str]:
    """Extract structured entities from transcript text.

    Returns dict of entity_type -> extracted_value.
    """
    entities = {}
    for entity_type, pattern in _ENTITY_PATTERNS.items():
        match = pattern.search(transcript)
        if match:
            value = match.group(1) if match.lastindex else match.group(0)
            entities[entity_type] = value.strip()
    return entities
