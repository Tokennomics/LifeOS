"""Input Sanitization, Prompt Injection Defense & XSS Shield.

Strips unsafe script tags to prevent XSS attacks and scans LLM prompts
against prompt-injection override patterns.
"""

import html
import re

INJECTION_PATTERNS = [
    r"ignore (all )?previous instructions",
    r"disregard (all )?prior (rules|instructions)",
    r"reveal (the )?system prompt",
    r"you are now an unrestricted",
    r"act as (dan|jailbroken|an unaligned ai)",
    r"override (system|safety) guidelines",
]


def sanitize_text(text: str) -> str:
    """Strips HTML tags, script tags, and escapes unsafe characters."""
    if not text:
        return ""

    # Remove script and style elements
    clean = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # Remove all HTML tags
    clean = re.sub(r"<[^>]+>", "", clean)
    # Unescape HTML entities then escape safely
    clean = html.escape(html.unescape(clean))
    return clean.strip()


def scan_prompt_injection(text: str) -> dict:
    """Scans text for prompt injection override attempts."""
    if not text:
        return {"is_suspicious": False, "detected_patterns": [], "sanitized_text": ""}

    detected = []
    text_lower = text.lower()

    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text_lower):
            detected.append(pattern)

    clean_txt = sanitize_text(text)

    return {
        "is_suspicious": len(detected) > 0,
        "detected_patterns": detected,
        "sanitized_text": clean_txt,
    }
