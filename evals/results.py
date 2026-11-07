"""
evals/results.py  –  Phase 13.2 (D-048)
The plain data the evaluation passes around: what /ask returned, how one question scored, and the judge's opinion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from evals.golden import GoldenItem

# How one question ended up (ItemResult.outcome)
PASS = "PASS"                                # in scope: every expected fact is in the answer; refusal item: it refused
MISSING_FACTS = "MISSING_FACTS"              # in scope, answered, but at least one expected fact is absent
FALSE_REFUSAL = "FALSE_REFUSAL"              # in scope, but the assistant said it did not know
SHOULD_HAVE_REFUSED = "SHOULD_HAVE_REFUSED"  # out of scope, but the assistant produced an answer
ERROR = "ERROR"                              # no usable response (HTTP error, timeout, ...)
OUTCOMES = (PASS, MISSING_FACTS, FALSE_REFUSAL, SHOULD_HAVE_REFUSED, ERROR)


@dataclass(frozen=True)
class SourceRef:
    """One citation from /ask's `sources`."""
    document: str      # relative file path, e.g. data/docs/on_call_guide.md
    heading: str
    similarity: float


@dataclass(frozen=True)
class AskResult:
    """What one call to /ask gave back (or why there is no answer)."""
    status: int
    answer: str
    sources: tuple[SourceRef, ...]
    latency_ms: float
    request_id: Optional[str] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class Judgement:
    """The optional Gemini judge's opinion of one answer; verdict is correct / partial / incorrect / unparseable / error."""
    verdict: str
    reason: str = ""


@dataclass(frozen=True)
class ItemResult:
    item: GoldenItem
    ask: AskResult
    outcome: str
    facts_found: tuple[str, ...] = ()
    facts_missing: tuple[str, ...] = ()
    coverage: Optional[float] = None          # share of expected facts found; None for refusal items and errors
    retrieval_rank: Optional[int] = None      # 1-based position of the expected section among the sources; None = absent
    retrieved: Optional[bool] = None          # whether the expected section was cited at all; None when not applicable
    judge: Optional[Judgement] = None

    @property
    def passed(self) -> bool:
        return self.outcome == PASS
