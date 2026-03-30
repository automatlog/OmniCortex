"""
Agent Workflow State Machine — manages conversation flow stages
for voice agents (e.g. greeting → verification → service → farewell).

Workflow config is stored in agent.logic["workflow"] or agent.extra_data["workflow"].
"""
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Example workflow schema (stored in agent.logic["workflow"]) ──────
# {
#     "states": ["greeting", "identity_verification", "service", "farewell"],
#     "initial_state": "greeting",
#     "transitions": {
#         "greeting": {
#             "next": "identity_verification",
#             "condition": "any_response",
#             "prompt_override": "Greet the caller warmly. Ask for their account number.",
#             "max_turns": 2
#         },
#         "identity_verification": {
#             "next": "service",
#             "condition": "identity_verified",
#             "prompt_override": "Verify the caller's identity. Ask for date of birth or last 4 of SSN.",
#             "required_entities": ["account_number"],
#             "max_turns": 3
#         },
#         "service": {
#             "next": "farewell",
#             "condition": "query_resolved",
#             "prompt_override": null
#         },
#         "farewell": {
#             "next": null,
#             "condition": "end",
#             "prompt_override": "Thank the caller and wish them a good day."
#         }
#     }
# }

# ── Condition evaluators ─────────────────────────────────────────────
_CONDITION_PATTERNS: Dict[str, re.Pattern] = {
    "any_response": re.compile(r".+", re.DOTALL),
    "identity_verified": re.compile(
        r"(?:account|verify|verified|confirm|date of birth|dob|ssn|social|birthday)",
        re.IGNORECASE,
    ),
    "query_resolved": re.compile(
        r"(?:thank|thanks|that.?s all|nothing else|no more|goodbye|bye|done)",
        re.IGNORECASE,
    ),
    "end": re.compile(r"(?:bye|goodbye|end|hang up|disconnect)", re.IGNORECASE),
}


class AgentWorkflow:
    """Per-session conversation workflow state machine."""

    def __init__(self, workflow_config: Dict[str, Any]):
        self._config = workflow_config
        self._states: List[str] = workflow_config.get("states", [])
        self._transitions: Dict[str, Dict] = workflow_config.get("transitions", {})
        self.current_state: str = workflow_config.get("initial_state", "")
        self._turns_in_state: int = 0
        self._collected_entities: Dict[str, str] = {}

        if not self._states or not self.current_state:
            logger.warning("Workflow has no states or initial_state — will be a no-op")

    @classmethod
    def from_agent(cls, agent: Optional[Dict]) -> Optional["AgentWorkflow"]:
        """Create workflow from agent config. Returns None if no workflow defined."""
        if not agent:
            return None

        # Check logic field first, then extra_data
        workflow_cfg = None
        logic = agent.get("logic")
        if isinstance(logic, dict):
            workflow_cfg = logic.get("workflow")
        if not workflow_cfg:
            extra = agent.get("extra_data")
            if isinstance(extra, dict):
                workflow_cfg = extra.get("workflow")

        if not workflow_cfg or not isinstance(workflow_cfg, dict):
            return None

        states = workflow_cfg.get("states", [])
        if not states:
            return None

        logger.info("Loading agent workflow: %d states, initial=%s",
                     len(states), workflow_cfg.get("initial_state", "?"))
        return cls(workflow_cfg)

    def get_current_prompt_override(self) -> Optional[str]:
        """Return the prompt override for the current state, if any."""
        if not self.current_state:
            return None
        transition = self._transitions.get(self.current_state, {})
        return transition.get("prompt_override")

    def is_active(self) -> bool:
        """Return True if the workflow has states and a current state."""
        return bool(self._states and self.current_state)

    def advance(self, transcript: str, answer: str = "") -> Optional[str]:
        """Check if the current state's condition is met and transition.

        Args:
            transcript: The caller's latest utterance
            answer: The agent's latest response

        Returns:
            New prompt_override if state changed, None otherwise.
        """
        if not self.current_state:
            return None

        self._turns_in_state += 1
        transition = self._transitions.get(self.current_state, {})

        # Check max_turns forced transition
        max_turns = transition.get("max_turns", 0)
        force_advance = max_turns > 0 and self._turns_in_state >= max_turns

        # Check condition
        condition_name = transition.get("condition", "any_response")
        condition_met = self._check_condition(condition_name, transcript, answer)

        if condition_met or force_advance:
            next_state = transition.get("next")
            if next_state and next_state in self._states:
                prev = self.current_state
                self.current_state = next_state
                self._turns_in_state = 0
                logger.info("Workflow: %s -> %s (condition=%s, forced=%s)",
                            prev, next_state, condition_name, force_advance)
                return self.get_current_prompt_override()
            elif next_state is None:
                # Terminal state
                logger.info("Workflow reached terminal state: %s", self.current_state)
                self.current_state = ""
                return None

        return None

    def get_transfer_target(self) -> Optional[str]:
        """Return the transfer_to_agent for the current state, if configured.

        Workflow transitions can specify:
            "transfer_to_agent": "agent-uuid"
        to trigger an agent transfer when that state is reached.
        """
        if not self.current_state:
            return None
        transition = self._transitions.get(self.current_state, {})
        return transition.get("transfer_to_agent")

    def is_blocked(self, intent: str) -> bool:
        """Check if the current state blocks a given intent.

        For example, account queries are blocked during identity verification.
        """
        if not self.current_state:
            return False

        transition = self._transitions.get(self.current_state, {})
        blocked_intents = transition.get("blocked_intents", [])
        return intent in blocked_intents

    def get_state_info(self) -> Dict[str, Any]:
        """Return current workflow state for status messages."""
        return {
            "state": self.current_state,
            "turns_in_state": self._turns_in_state,
            "entities": dict(self._collected_entities),
        }

    def collect_entity(self, name: str, value: str):
        """Store a collected entity (e.g., account_number from caller)."""
        self._collected_entities[name] = value

    def has_required_entities(self) -> bool:
        """Check if all required entities for the current state are collected."""
        if not self.current_state:
            return True
        transition = self._transitions.get(self.current_state, {})
        required = transition.get("required_entities", [])
        return all(e in self._collected_entities for e in required)

    def _check_condition(self, condition: str, transcript: str, answer: str) -> bool:
        """Evaluate a transition condition against the transcript/answer."""
        pattern = _CONDITION_PATTERNS.get(condition)
        if pattern:
            return bool(pattern.search(transcript) or pattern.search(answer))

        # Custom condition — treat as regex on transcript
        try:
            return bool(re.search(condition, transcript, re.IGNORECASE))
        except re.error:
            return False
