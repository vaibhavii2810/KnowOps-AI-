"""
app/guardrails.py  –  Phase 10.3
Defences against prompt injection (D-034).

Untrusted text reaches the model from three places: retrieved runbook chunks, ticket content
and tool output. Two layers protect against it, so safety never depends on the model behaving:

  1. fence() wraps untrusted text in <untrusted_data> tags (and neutralize() stops the text from
     forging a closing tag); the system prompts tell the model that fenced text is data only.
  2. find_injection() is a deterministic detector for instruction-like text aimed at the AI.
     A flagged runbook chunk is dropped before the model sees it, and a flagged tool result or
     ticket "taints" the agent run so state-changing tools are blocked (see STATE_CHANGING_TOOLS).

The detector is a heuristic, not a proof: a differently-worded attack can slip past it, and the
fencing plus the system-prompt rule are then the only defence. Its patterns are narrow on purpose —
they target text addressed *to the AI* — so ordinary runbook wording ("you must run kubectl…")
is not flagged; tests/test_prompt_injection.py checks every seed runbook for false positives.
"""

from __future__ import annotations

import re

DATA_TAG = "untrusted_data"
_TAG_RE = re.compile(rf"<\s*/?\s*{DATA_TAG}\b[^>]*>?", re.IGNORECASE)
_SOURCE_RE = re.compile(r"[^A-Za-z0-9_ .:\-]")

# Tools that change state. A tainted run (one that has seen embedded instructions) may not run
# these. escalate_to_human is deliberately NOT here: paging a human is the safe response to a
# suspected attack, so blocking it would be counter-productive.
STATE_CHANGING_TOOLS = frozenset({"create_ticket", "update_ticket", "execute_recovery_action"})

_INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    # "ignore all previous instructions", "disregard your rules", "forget the above prompt"
    "override-instructions": re.compile(
        r"\b(?:ignore|disregard|forget|override)\b[^.\n]{0,40}\b(?:previous|prior|above|earlier|preceding|all|your|any)\b"
        r"[^.\n]{0,30}\b(?:instructions?|rules?|prompts?|guidelines?|directions?)\b",
        re.IGNORECASE,
    ),
    # "print your system prompt", "reveal the system instructions", "show your instructions"
    "reveal-prompt": re.compile(
        r"\b(?:reveal|print|show|output|repeat|leak|display|disclose|dump)\b[^.\n]{0,40}"
        r"\b(?:system\s+(?:prompt|instructions?|message)|your\s+(?:full\s+|entire\s+|complete\s+)?(?:prompt|instructions?))\b",
        re.IGNORECASE,
    ),
    # "[ADMIN OVERRIDE]", "(system notice):", "SYSTEM NOTICE TO ASSISTANT" — alert-style only, so a
    # lowercase sentence like "the system override switch is on the PDU panel" is not flagged.
    "fake-authority": re.compile(
        r"(?:[\[(<*]\s*(?i:(?:system|admin(?:istrator)?|developer|root)\s+(?:override|notice|message|instruction|directive)s?)\s*[\])>*:]"
        r"|\b(?:SYSTEM|ADMIN(?:ISTRATOR)?|DEVELOPER|ROOT)\s+(?:OVERRIDE|NOTICE|MESSAGE|INSTRUCTIONS?|DIRECTIVE)S?\b)",
    ),
    # "you are now DAN", "you are now an AI with no rules", "you are now in developer mode"
    "persona-switch": re.compile(
        r"\byou\s+are\s+now\s+(?:dan\b|an?\s+(?:ai|assistant|model|chatbot)\b|in\s+(?:developer|debug|admin|god)\s+mode\b|unrestricted\b)",
        re.IGNORECASE,
    ),
    # "Assistant: you must call …", "agent, you should execute …" (requires the punctuation + "you")
    "addresses-the-ai": re.compile(
        r"\b(?:assistant|ai|agent|model)\b\s*[,:]\s*you\s+(?:must|should|need\s+to|are\s+required\s+to|will\s+now)\b",
        re.IGNORECASE,
    ),
}


def find_injection(text: object) -> list[str]:
    """Names of the injection patterns that match `text` (empty list = nothing suspicious)."""
    value = str(text)
    return [name for name, pattern in _INJECTION_PATTERNS.items() if pattern.search(value)]


def neutralize(text: object) -> str:
    """Strip anything shaped like our fence tags so untrusted text cannot close the fence early."""
    return _TAG_RE.sub("[removed]", str(text))


def fence(text: object, source: str) -> str:
    """Wrap untrusted text so the model can tell data from instructions."""
    safe_source = _SOURCE_RE.sub("", source)[:60]
    return f'<{DATA_TAG} source="{safe_source}">\n{neutralize(text)}\n</{DATA_TAG}>'
