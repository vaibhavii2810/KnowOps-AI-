"""
evals/hallucination.py  –  Phase 13.4 (D-051)
Flag answers that are *likely* to contain something the retrieved runbook text does not support. Pure functions, no
network: they look only at the answer, the sources /ask returned (with their text), the question, and the runbook titles.

A flag is a pointer for a human, not a verdict: each check is a heuristic with known blind spots (listed in D-051), and a
flagged answer can be correct while an unflagged one can be wrong. Refusals make no claims, so they are never flagged.

  no_context            answered although retrieval returned nothing — it spoke from its own knowledge
  uncited               answered, but names none of the retrieved documents (by title or section heading)
  phantom_citation      names a runbook that was not among the retrieved sources
  unsupported_quantity  a number with a unit ("6 hours", "70%", "512Mi") that is in neither the retrieved text nor the question
  unsupported_code      inline code or a command in a code block that is not in the retrieved text
  answered_out_of_scope the question should have been refused and was answered
"""

from __future__ import annotations

import re

from evals.golden import GoldenItem, normalize
from evals.results import (
    ANSWERED_OUT_OF_SCOPE, NO_CONTEXT, PHANTOM_CITATION, UNCITED, UNSUPPORTED_CODE, UNSUPPORTED_QUANTITY, AskResult, Flag,
)

MIN_CODE_CHARS = 4          # shorter code spans ("1Gi", "ls") are too generic to be a meaningful check

_QUANTITY = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?)[\s-]?"
    r"(%|(?:ms|seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?|replicas?|attempts?|nodes?|pods?|cores?"
    r"|mi|gi|mb|gb|kb)\b)",
    re.IGNORECASE,
)
# The same quantity written as a setting, as in `kubectl scale --replicas=5`: "5 replicas" and "replicas=5" are one fact.
_KEYED_QUANTITY = re.compile(r"\b(replicas|attempts|nodes|pods|cores)\s*[=:]\s*(\d+(?:\.\d+)?)\b", re.IGNORECASE)
_EXACT_UNITS = {"%", "ms", "mi", "gi", "mb", "gb", "kb"}
_UNIT_PREFIXES = (("sec", "s"), ("min", "min"), ("hour", "h"), ("hr", "h"), ("day", "d"), ("week", "w"),
                  ("replica", "replica"), ("attempt", "attempt"), ("node", "node"), ("pod", "pod"), ("core", "core"))
_FENCED_BLOCK = re.compile(r"```[\w-]*\n(.*?)```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")


def _unit_family(unit: str) -> str:
    unit = unit.lower()
    if unit in _EXACT_UNITS:
        return unit
    return next(family for prefix, family in _UNIT_PREFIXES if unit.startswith(prefix))


def quantities(text: str) -> dict[tuple[str, str], str]:
    """{(number, unit family): the text as written} for every number-with-unit in `text`. 'minutes', 'mins' and '5-minute'
    are one family; '5.0' and '5' are one number; 'replicas=5' counts as 5 replicas. Bare numbers (list markers, ids)
    are ignored on purpose."""
    def clean(number: str) -> str:
        return number.rstrip("0").rstrip(".") if "." in number else number

    found: dict[tuple[str, str], str] = {}
    for match in _QUANTITY.finditer(text):
        found.setdefault((clean(match.group(1)), _unit_family(match.group(2))), match.group(0).strip())
    for match in _KEYED_QUANTITY.finditer(text):
        found.setdefault((clean(match.group(2)), _unit_family(match.group(1))), match.group(0).strip())
    return found


def code_spans(answer: str) -> list[str]:
    """Inline `code` spans and the command lines of fenced code blocks (comment lines skipped), long enough to check."""
    spans: list[str] = []

    def from_block(block: re.Match) -> str:
        for line in block.group(1).splitlines():
            line = line.strip().rstrip("\\").strip()
            if line and not line.startswith("#"):
                spans.append(line)
        return " "

    without_blocks = _FENCED_BLOCK.sub(from_block, answer)
    spans += [m.group(1).strip() for m in _INLINE_CODE.finditer(without_blocks)]
    return [s for s in dict.fromkeys(spans) if len(s) >= MIN_CODE_CHARS]


def find_flags(item: GoldenItem, ask: AskResult, refused: bool, known_titles: tuple[str, ...]) -> tuple[Flag, ...]:
    """Likely-hallucination flags for one answer. `refused` is True when the answer made no claims (a refusal)."""
    if ask.error is not None or ask.status != 200 or refused:
        return ()
    flags: list[Flag] = []
    answer = normalize(ask.answer)
    sources = ask.sources

    if item.must_refuse:
        flags.append(Flag(ANSWERED_OUT_OF_SCOPE))
    if not sources:
        flags.append(Flag(NO_CONTEXT))
    elif not any((s.title and normalize(s.title) in answer) or (s.heading and normalize(s.heading) in answer)
                 for s in sources):
        flags.append(Flag(UNCITED))

    # Which documents were retrieved is only known if every source says which document it is; otherwise skip this check
    # rather than accuse an answer of citing a document we cannot rule out.
    if all(s.title for s in sources):
        retrieved_titles = {normalize(s.title) for s in sources}
        question = normalize(item.question)
        for title in known_titles:
            wanted = normalize(title)
            if wanted in answer and wanted not in retrieved_titles and wanted not in question:
                flags.append(Flag(PHANTOM_CITATION, title))

    context = " ".join([item.question] + [f"{s.title} {s.heading} {s.content}" for s in sources])
    supported = quantities(context)
    flags += [Flag(UNSUPPORTED_QUANTITY, text)
              for key, text in sorted(quantities(ask.answer).items(), key=lambda kv: kv[1]) if key not in supported]
    context_text = normalize(context)
    flags += [Flag(UNSUPPORTED_CODE, span[:80]) for span in code_spans(ask.answer) if normalize(span) not in context_text]
    return tuple(flags)
