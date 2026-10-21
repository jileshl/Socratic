"""Guardrail policies: Minor protection, PII masking, injection defense, answer leak checks."""

import re
from typing import Any
from socratic_tutor import config


def check_input_guardrails(text: str) -> dict[str, Any]:
    """Scan incoming student text for prompt injection, inappropriate content, and distress."""
    # Pattern checks
    injection_patterns = [
        r"ignore (all )?previous instructions",
        r"system override",
        r"i am (the|your) teacher",
        r"print (the )?answer key"
    ]
    is_injection = any(re.search(p, text, re.IGNORECASE) for p in injection_patterns)
    
    # Distress patterns
    distress_patterns = [
        r"hurt myself",
        r"kill myself",
        r"depressed"
    ]
    is_distress = any(re.search(p, text, re.IGNORECASE) for p in distress_patterns)
    
    # PII scrubbing (phone numbers, emails)
    sanitized = re.sub(r"\b\d{10}\b", "[PHONE_MASKED]", text)
    sanitized = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b", "[EMAIL_MASKED]", sanitized)
    
    return {
        "sanitized_query": sanitized,
        "is_injection": is_injection,
        "is_distress": is_distress,
        "passed": not (is_injection or is_distress)
    }


def check_answer_leak(response: str, expected_answer: str | None) -> bool:
    """Return True if the response contains the direct numeric or final solution in practice mode."""
    if not expected_answer:
        return False
    # If final answer string directly matches or appears prominently
    clean_ans = expected_answer.strip().lower()
    clean_resp = response.strip().lower()
    if clean_ans in clean_resp:
        return True
    return False
