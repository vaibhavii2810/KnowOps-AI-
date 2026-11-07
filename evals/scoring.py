"""
evals/scoring.py  –  Phase 13.2 (D-048)
Score one answer against its golden item, and summarise a whole run. Pure functions, no network.

Scoring is by keyword: an in-scope answer passes only if it contains every expected fact (compared with
golden.normalize(), so Markdown, case, dashes and quotes do not matter). Coverage — the share of facts found — is
reported alongside as the softer measure. Refusal items pass only if the assistant declined.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from evals.golden import GoldenItem, fact_present, normalize
from evals.results import (
    ERROR, FALSE_REFUSAL, MISSING_FACTS, PASS, SHOULD_HAVE_REFUSED, AskResult, ItemResult,
)

_REFUSAL_PHRASE = normalize("I don't have enough information")
_SHORT_ANSWER_CHARS = 160

DEFAULT_SLOW_MS = 5000.0     # the build guide's example threshold for "slow"


def is_refusal(answer: str) -> bool:
    """True if the assistant declined: it says it lacks the information and either opens with that or is brief.
    An answer that gives a full procedure and only adds 'I don't have enough information about X' at the end is not one.
    (One that opens with the phrase and then goes on is a refusal here; score_item still counts it as an answer if it
    contains the expected facts.)"""
    text = normalize(answer)
    return _REFUSAL_PHRASE in text and (text.startswith(_REFUSAL_PHRASE) or len(text) <= _SHORT_ANSWER_CHARS)


def retrieval_rank(item: GoldenItem, ask: AskResult) -> Optional[int]:
    """1-based position of the item's source section among the cited sources, or None if it was not cited."""
    for position, source in enumerate(ask.sources, start=1):
        if Path(source.document).name == item.source_doc and source.heading == item.source_section:
            return position
    return None


def score_item(item: GoldenItem, ask: AskResult) -> ItemResult:
    if ask.error is not None or ask.status != 200:
        return ItemResult(item=item, ask=ask, outcome=ERROR)

    refused = is_refusal(ask.answer)
    if item.must_refuse:
        return ItemResult(item=item, ask=ask, outcome=PASS if refused else SHOULD_HAVE_REFUSED)

    rank = retrieval_rank(item, ask)
    found = tuple(f for f in item.expected_facts if fact_present(item, f, ask.answer))
    missing = tuple(f for f in item.expected_facts if f not in found)
    # A hedge followed by the real answer ("I don't have enough information about X, but ...") is an answer, not a
    # refusal: it is a false refusal only if it declined and contains none of the expected facts.
    outcome = FALSE_REFUSAL if refused and not found else (PASS if not missing else MISSING_FACTS)
    return ItemResult(
        item=item, ask=ask, outcome=outcome, facts_found=found, facts_missing=missing,
        coverage=len(found) / len(item.expected_facts), retrieval_rank=rank, retrieved=rank is not None,
    )


def is_slow(result: ItemResult, threshold_ms: float) -> bool:
    """Strictly over the threshold. A question with no response is never slow: a timeout is not a latency measurement."""
    return result.outcome != ERROR and result.ask.latency_ms > threshold_ms


def percentile(values: list[float], q: int) -> float:
    """Nearest-rank percentile: the smallest value that at least q% of the values are at or below."""
    ordered = sorted(values)
    return ordered[max(1, math.ceil(q * len(ordered) / 100)) - 1]


@dataclass(frozen=True)
class LatencyStats:
    count: int                                   # questions that got a response
    mean_ms: float
    median_ms: float
    p95_ms: float
    max_ms: float
    threshold_ms: float
    slow: tuple[tuple[str, float], ...]          # (question id, ms) over the threshold, slowest first

    @property
    def slow_count(self) -> int:
        return len(self.slow)


def latency_stats(results: list[ItemResult], threshold_ms: float = DEFAULT_SLOW_MS) -> Optional[LatencyStats]:
    answered = [r for r in results if r.outcome != ERROR]
    if not answered:
        return None
    times = [r.ask.latency_ms for r in answered]
    slow = sorted(((r.item.id, r.ask.latency_ms) for r in answered if is_slow(r, threshold_ms)), key=lambda p: -p[1])
    return LatencyStats(
        count=len(times), mean_ms=statistics.fmean(times), median_ms=statistics.median(times),
        p95_ms=percentile(times, 95), max_ms=max(times), threshold_ms=threshold_ms, slow=tuple(slow),
    )


@dataclass(frozen=True)
class Summary:
    total: int
    passed: int
    errors: int
    in_scope_total: int
    in_scope_passed: int
    false_refusals: int
    mean_coverage: Optional[float]          # over in-scope questions that got a response
    retrieval_hits: int
    retrieval_total: int
    mrr: Optional[float]                    # mean of 1/rank over in-scope questions that got a response
    refusal_total: int
    refusals_correct: int
    answered_out_of_scope: int
    judged: int
    judge_counts: dict[str, int]
    judge_agrees: int                       # judge said "correct" exactly when the keyword check passed
    latency: Optional[LatencyStats] = None

    @property
    def accuracy(self) -> Optional[float]:
        return self.passed / self.total if self.total else None


def summarise(results: list[ItemResult], slow_ms: float = DEFAULT_SLOW_MS) -> Summary:
    answered_in_scope = [r for r in results if not r.item.must_refuse and r.outcome != ERROR]
    judged = [r for r in results if r.judge is not None]
    judge_counts: dict[str, int] = {}
    for r in judged:
        judge_counts[r.judge.verdict] = judge_counts.get(r.judge.verdict, 0) + 1
    return Summary(
        total=len(results),
        passed=sum(r.passed for r in results),
        errors=sum(r.outcome == ERROR for r in results),
        in_scope_total=sum(not r.item.must_refuse for r in results),
        in_scope_passed=sum(r.passed for r in results if not r.item.must_refuse),
        false_refusals=sum(r.outcome == FALSE_REFUSAL for r in results),
        mean_coverage=(sum(r.coverage for r in answered_in_scope) / len(answered_in_scope)) if answered_in_scope else None,
        retrieval_hits=sum(bool(r.retrieved) for r in answered_in_scope),
        retrieval_total=len(answered_in_scope),
        mrr=(sum(1 / r.retrieval_rank if r.retrieval_rank else 0.0 for r in answered_in_scope) / len(answered_in_scope))
        if answered_in_scope else None,
        refusal_total=sum(r.item.must_refuse for r in results),
        refusals_correct=sum(r.passed for r in results if r.item.must_refuse),
        answered_out_of_scope=sum(r.outcome == SHOULD_HAVE_REFUSED for r in results),
        judged=len(judged),
        judge_counts=judge_counts,
        judge_agrees=sum((r.judge.verdict == "correct") == r.passed for r in judged),
        latency=latency_stats(results, slow_ms),
    )
