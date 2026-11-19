"""Code-side defences against prompt injection and bad extractions.

The prompt asks Claude to ignore instructions inside messages, but a prompt is not a
guarantee. These checks run on Claude's output in plain code, so even a fully successful
injection can't add pints: anything suspicious is HELD (not counted) until a human approves it.
"""
from __future__ import annotations

import re

from . import config

INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|rules|messages)",
    r"disregard (the |all |your )?(instructions|rules|system)",
    r"\bsystem\s*(prompt|message)?\s*:",
    r"\byou are now\b",
    r"\bnew instructions\b",
    r"\b(record_drinks|tool call|function call|json)\b",
    r"</?\s*(message|recent_messages|system|instructions)\s*>",
    r"\b(admin|developer|bot owner) (says|said|wants|approved)\b",
]
_INJECTION = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)


def looks_like_injection(text: str | None) -> bool:
    return bool(_INJECTION.search(text or ""))


def hold_reasons(text: str | None, extraction: dict) -> list[str]:
    """Reasons to hold a message instead of counting it. Empty list = safe to count."""
    reasons = []
    if extraction.get("suspected_injection"):
        reasons.append("Claude flagged an instruction inside the message")
    if looks_like_injection(text):
        reasons.append("message text matches an injection pattern")
    drinks = extraction.get("drinks") or []
    total = sum(max(int(d.get("quantity") or 1), 1) for d in drinks)
    if total > config.MAX_DRINKS_PER_MESSAGE:
        reasons.append(f"{total} drinks in one message (limit {config.MAX_DRINKS_PER_MESSAGE})")
    return reasons
