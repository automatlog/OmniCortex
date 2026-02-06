"""
PII Masking Module
Redacts sensitive information using Regex patterns.
Supported: Email, Phone, Credit Card, SSN, IP Address
"""
import re

PATTERNS = {
    "EMAIL": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
    "PHONE": r'\b(\+\d{1,2}\s)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b',
    "CREDIT_CARD": r'\b(?:\d{4}[- ]?){3}\d{4}\b',
    "SSN": r'\b\d{3}-\d{2}-\d{4}\b',
    "IP_ADDRESS": r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'
}

def mask_pii(text: str) -> str:
    """
    Redact PII from text.
    Returns masked text.
    """
    masked_text = text
    
    for label, pattern in PATTERNS.items():
        masked_text = re.sub(pattern, f"<{label}>", masked_text)
        
    if masked_text != text:
        # print(f"🛡️ PII Masked: {text} -> {masked_text}")
        pass
        
    return masked_text
