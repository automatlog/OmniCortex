"""
Guardrails Module
Basic Input/Output validation and safety checks.
"""
from typing import Tuple

# Blacklisted keywords for prompt injection and jailbreak filtering
BLACKLIST = [
    "ignore previous instructions",
    "ignore all instructions",
    "disregard your instructions",
    "forget your instructions",
    "system prompt",
    "you are a hacked",
    "write a exploits",
    "act as dan",
    "jailbreak",
    "reveal your prompt",
    "pretend you have no restrictions",
    "bypass your filters",
]

def validate_input(text: str) -> Tuple[bool, str]:
    """
    Validate user input.
    Returns (is_valid, reason)
    """
    text_lower = text.lower()
    
    # 1. Length Check
    if len(text) > 10000:
        return False, "Input too long (max 10000 chars)"
        
    # 2. Blacklist Check
    for term in BLACKLIST:
        if term in text_lower:
            return False, f"Blocked content detected: '{term}'"
            
    return True, "OK"


def validate_output(text: str) -> Tuple[bool, str]:
    """
    Validate LLM output.
    Returns (is_valid, reason)
    """
    # Placeholder for output validation (e.g., checking for leaked keys)
    if "sk-" in text and len(text) > 20: # Simple OpenAI Key check
        # Check if it looks like a key
        import re
        if re.search(r"sk-[a-zA-Z0-9]{20,}", text):
            return False, "Potential API Key leakage detected"
            
    return True, "OK"
