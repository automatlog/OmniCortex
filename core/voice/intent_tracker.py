"""
Intent Tracker — per-session intent classification, follow-up prediction,
and RAG prefetch for the voice pipeline.

Starts with keyword-based classification. Can be upgraded to ML classifier later.
"""
import logging
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Default intent keyword map ──────────────────────────────────────
# Each intent maps to a list of keyword patterns (case-insensitive)
_DEFAULT_INTENT_KEYWORDS: Dict[str, List[str]] = {
    "loan_balance": [
        r"\bloan\b", r"\bbalance\b", r"\boutstanding\b", r"\bowed\b", r"\bprincipal\b",
    ],
    "payment": [
        r"\bpay\b", r"\bpayment\b", r"\binstallment\b", r"\bemi\b", r"\bbill\b",
    ],
    "interest_rate": [
        r"\binterest\b", r"\brate\b", r"\bapr\b", r"\bpercentage\b",
    ],
    "due_date": [
        r"\bdue\b", r"\bdeadline\b", r"\bwhen.*pay\b", r"\bnext.*date\b",
    ],
    "account_info": [
        r"\baccount\b", r"\bprofile\b", r"\bdetails\b", r"\binformation\b",
    ],
    "transaction_history": [
        r"\btransaction\b", r"\bhistory\b", r"\bstatement\b", r"\brecent\b",
    ],
    "complaint": [
        r"\bcomplaint\b", r"\bissue\b", r"\bproblem\b", r"\bescalat\b", r"\bmanager\b",
    ],
    "escalation": [
        r"\bmanager\b", r"\bsupervisor\b", r"\bhuman\b", r"\breal person\b",
        r"\bescalate\b", r"\bhigher authority\b", r"\bsenior\b",
    ],
    "transfer_request": [
        r"\btransfer\b", r"\bconnect me\b", r"\bswitch\b", r"\banother agent\b",
        r"\bsomeone else\b", r"\bdifferent.*department\b", r"\btechnical\s*support\b",
    ],
    "greeting": [
        r"\bhello\b", r"\bhi\b", r"\bhey\b", r"\bgood\s*(morning|afternoon|evening)\b",
    ],
    "farewell": [
        r"\bbye\b", r"\bgoodbye\b", r"\bthank\b", r"\bthanks\b", r"\bend\b",
    ],
    "general_query": [
        r"\bwhat\b", r"\bhow\b", r"\bwhen\b", r"\bwho\b", r"\bwhere\b", r"\bwhy\b",
        r"\bexplain\b", r"\btell me\b", r"\bdescribe\b", r"\bcan you\b",
    ],
}

# ── Follow-up prediction map ────────────────────────────────────────
# After detecting intent X, predict these likely follow-up intents
_DEFAULT_FOLLOW_UP_MAP: Dict[str, List[str]] = {
    "loan_balance": ["payment", "interest_rate", "due_date"],
    "payment": ["due_date", "loan_balance", "transaction_history"],
    "interest_rate": ["loan_balance", "payment"],
    "due_date": ["payment", "loan_balance"],
    "account_info": ["transaction_history", "loan_balance"],
    "transaction_history": ["payment", "account_info"],
    "complaint": ["escalation", "account_info"],
    "escalation": ["complaint", "transfer_request"],
    "transfer_request": ["escalation"],
    "greeting": ["account_info", "general_query"],
    "farewell": [],
    "general_query": ["account_info"],
}

# ── RAG query templates per intent ──────────────────────────────────
_INTENT_RAG_QUERIES: Dict[str, str] = {
    "loan_balance": "loan balance outstanding amount principal",
    "payment": "payment options installment EMI schedule",
    "interest_rate": "interest rate APR percentage annual",
    "due_date": "payment due date deadline schedule",
    "account_info": "account details profile information",
    "transaction_history": "transaction history statement recent activity",
    "complaint": "complaint escalation resolution process",
    "escalation": "escalation policy supervisor manager handoff",
    "transfer_request": "transfer routing department agent support",
}

# ── Transfer-triggering intents ───────────────────────────────────────
TRANSFER_INTENTS = {"escalation", "transfer_request", "complaint"}


class IntentTracker:
    """Per-session intent tracker with follow-up prediction."""

    def __init__(
        self,
        agent_intent_keywords: Optional[Dict[str, List[str]]] = None,
        agent_follow_up_map: Optional[Dict[str, List[str]]] = None,
    ):
        self._keywords = agent_intent_keywords or _DEFAULT_INTENT_KEYWORDS
        self._follow_ups = agent_follow_up_map or _DEFAULT_FOLLOW_UP_MAP
        self._compiled: Dict[str, List[re.Pattern]] = {}
        for intent, patterns in self._keywords.items():
            self._compiled[intent] = [re.compile(p, re.IGNORECASE) for p in patterns]

        self.intent_history: List[str] = []
        self.prefetch_cache: Dict[str, List[dict]] = {}

    def classify_intent(self, transcript: str) -> str:
        """Classify transcript into an intent using keyword matching.

        Returns the intent with the most keyword hits, or "general_query" as fallback.
        """
        scores: Dict[str, int] = {}
        for intent, patterns in self._compiled.items():
            hits = sum(1 for p in patterns if p.search(transcript))
            if hits > 0:
                scores[intent] = hits

        if not scores:
            # Check if it's at least a question
            if transcript.rstrip().endswith("?"):
                best = "general_query"
            else:
                best = "general_query"
        else:
            best = max(scores, key=scores.get)

        self.intent_history.append(best)
        if len(self.intent_history) > 20:
            self.intent_history = self.intent_history[-20:]

        return best

    def is_query_intent(self, transcript: str) -> bool:
        """Enhanced replacement for the old regex-based _is_query_intent().

        Returns True if any meaningful intent is detected (not just greeting/farewell).
        """
        intent = self.classify_intent(transcript)
        non_actionable = {"greeting", "farewell"}
        return intent not in non_actionable

    def predict_next_intents(self) -> List[str]:
        """Predict likely follow-up intents based on the last classified intent."""
        if not self.intent_history:
            return []
        last = self.intent_history[-1]
        return self._follow_ups.get(last, [])

    def get_prefetch_queries(self) -> List[str]:
        """Convert predicted follow-up intents into RAG search queries."""
        predicted = self.predict_next_intents()
        queries = []
        for intent in predicted:
            q = _INTENT_RAG_QUERIES.get(intent)
            if q:
                queries.append(q)
        return queries

    def get_current_intent(self) -> Optional[str]:
        """Return the most recently classified intent."""
        return self.intent_history[-1] if self.intent_history else None

    def get_intent_context(self) -> str:
        """Return a brief context string about recent intents for LLM prompting."""
        if not self.intent_history:
            return ""
        recent = self.intent_history[-3:]
        return f"Recent caller intents: {', '.join(recent)}"

    def is_transfer_intent(self, intent: Optional[str] = None) -> bool:
        """Check if the given (or current) intent suggests a transfer/escalation."""
        target = intent or self.get_current_intent()
        return target in TRANSFER_INTENTS

    def get_escalation_urgency(self) -> float:
        """Score 0-1 indicating how urgently the caller wants escalation.

        Based on recent intent history — repeated complaints/escalations increase urgency.
        """
        if not self.intent_history:
            return 0.0
        recent = self.intent_history[-5:]
        escalation_count = sum(1 for i in recent if i in TRANSFER_INTENTS)
        return min(escalation_count / 3.0, 1.0)

    def cache_prefetch(self, intent: str, results: List[dict]):
        """Store prefetched RAG results for a predicted intent."""
        self.prefetch_cache[intent] = results

    def get_cached(self, intent: str) -> Optional[List[dict]]:
        """Retrieve cached RAG results for an intent, if available."""
        return self.prefetch_cache.pop(intent, None)
