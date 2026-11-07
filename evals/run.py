"""
evals/run.py  –  Phase 13.2 (D-048)
One command runs the golden set through /ask and prints how it did:

    python -m evals                      # in-process: the real route, with the database and Gemini key from .env
    python -m evals --url https://...    # against a deployed site (logs in with APP_USERNAME / APP_PASSWORD)
    python -m evals --judge              # also ask Gemini to grade each answer (extra quota, reported separately)
    python -m evals --only g01,g05       # just those questions
    python -m evals --slow-seconds 3     # flag questions slower than 3 s (default 5); flagged, never failed
    python -m evals --repeat 3           # run the set 3 times and show which questions are not stable (answers vary)
    python -m evals --report path.json   # save the JSON report there (default evals/reports/run-<time>.json); --no-report skips

Every run saves a JSON report (evals/report.py); Ctrl-C saves what had finished. Exit code: 0 finished, 1 finished but some
questions got no response or the report could not be saved, 2 could not start (bad option, invalid golden set, login
rejected), 130 interrupted. A run that finds wrong answers still exits 0: finding them is its job. It calls real services, so it is
never part of `pytest`.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from evals.client import EvalSetupError, HttpClient, InProcessClient
from evals.golden import GoldenItem, load_golden_set, validate
from evals.judge import judge_answer
from evals.report import build_report, default_report_path, question_stability, write_report
from evals.results import ERROR, JUDGE_UNFAITHFUL, AskResult, Flag, ItemResult
from evals.scoring import DEFAULT_SLOW_MS, is_slow, score_item, summarise

DEFAULT_HTTP_DELAY_SECONDS = 7.0   # keeps a deployed site under its 10 requests/minute limit on /ask
QUOTA_RETRIES = 2                  # extra tries for a question that hit Gemini's own quota (429 RESOURCE_EXHAUSTED)
DEFAULT_QUOTA_WAIT_SECONDS = 30.0
EXCERPT_CHARS = 220
SLOWEST_SHOWN = 3
FLAGGED_SHOWN = 6
MAX_REPEAT = 10                    # each run costs real Gemini quota; more than this is almost certainly a typo


def _ask_once(client, item: GoldenItem, top_k: Optional[int]) -> AskResult:
    try:
        return client.ask(item.question, top_k=top_k, tag=item.id)
    except Exception as exc:  # the shipped clients never raise; a custom one must not be able to end the run
        return AskResult(status=0, answer="", sources=(), latency_ms=0.0, error=f"{type(exc).__name__}: {str(exc)[:200]}")


def _hit_gemini_quota(ask: AskResult) -> bool:
    """/ask turns Gemini's 429 into a 503 whose detail still names it; a run of 19 questions can trip the free tier."""
    return ask.error is not None and ("RESOURCE_EXHAUSTED" in ask.error or "429" in ask.error)


def run_eval(
    items: list[GoldenItem],
    client,
    *,
    judge: bool = False,
    top_k: Optional[int] = None,
    delay: float = 0.0,
    quota_wait: float = DEFAULT_QUOTA_WAIT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    on_result: Optional[Callable[[ItemResult], None]] = None,
) -> list[ItemResult]:
    results: list[ItemResult] = []
    for position, item in enumerate(items):
        if position and delay:
            sleep(delay)
        ask = _ask_once(client, item, top_k)
        for _ in range(QUOTA_RETRIES):
            if not _hit_gemini_quota(ask):
                break
            sleep(quota_wait)              # the wait is outside the measured latency, which is the last attempt's
            ask = _ask_once(client, item, top_k)
        result = score_item(item, ask)
        if judge and result.outcome != ERROR:
            result = _with_judgement(result)
        results.append(result)
        if on_result:
            on_result(result)
    return results


def _with_judgement(result: ItemResult) -> ItemResult:
    judgement = judge_answer(result.item, result.ask.answer, result.ask.sources)
    flags = result.flags
    if judgement.faithful is False and not result.refused:     # a refusal makes no claims to be unfaithful
        flags += (Flag(JUDGE_UNFAITHFUL, judgement.unsupported),)
    return replace(result, judge=judgement, flags=flags)


def _excerpt(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= EXCERPT_CHARS else flat[:EXCERPT_CHARS] + "…"


def _secs(ms: float) -> str:
    return f"{ms / 1000:.1f} s"


def _limit(ms: float) -> str:
    """A threshold, shown exactly: 5.0 s, 2.5 s, 0.25 s (never rounded to one decimal, which would misstate it)."""
    seconds = ms / 1000
    return f"{seconds:.1f} s" if round(seconds, 1) == seconds else f"{seconds:g} s"


def format_result(result: ItemResult, slow_ms: float = DEFAULT_SLOW_MS) -> str:
    item = result.item
    if result.outcome == ERROR:
        detail, where = "no response", ""
    elif item.must_refuse:
        detail, where = ("refused" if result.passed else "answered"), ""
    else:
        detail = f"facts {len(result.facts_found)}/{len(item.expected_facts)}"
        where = f"  section #{result.retrieval_rank}" if result.retrieval_rank else "  section not cited"
    line = f"{item.id}  {result.outcome:<19} {detail}{where}  {_secs(result.ask.latency_ms)}"
    if is_slow(result, slow_ms):
        line += f"  SLOW (over {_limit(slow_ms)})"
    if result.flags:
        line += "  FLAGGED: " + ", ".join(dict.fromkeys(f.kind for f in result.flags))
    if result.judge is not None:
        line += f"  judge: {result.judge.verdict}"
    lines = [f"{line}\n      {_excerpt(item.question)}"]
    if not result.passed:
        if result.facts_missing:
            lines.append(f"      missing: {', '.join(result.facts_missing)}")
        shown = result.ask.error if result.ask.error else result.ask.answer
        lines.append(f"      answer: {_excerpt(shown)}")
    lines += [f"      flag {flag.kind}: {flag.detail}" if flag.detail else f"      flag {flag.kind}" for flag in result.flags]
    if result.judge is not None and result.judge.reason:
        lines.append(f"      judge said: {result.judge.reason}")
    return "\n".join(lines)


def _pct(numerator: float, denominator: float) -> str:
    return f"{100 * numerator / denominator:.1f}%" if denominator else "n/a"


def format_summary(results: list[ItemResult], slow_ms: float = DEFAULT_SLOW_MS, latency_note: str = "") -> str:
    s = summarise(results, slow_ms)
    lines = [
        "== Accuracy (an answer passes only if it contains every expected fact) ==",
        f"In-scope questions : {s.in_scope_passed}/{s.in_scope_total} passed ({_pct(s.in_scope_passed, s.in_scope_total)})"
        f" | mean fact coverage {_pct(s.mean_coverage, 1) if s.mean_coverage is not None else 'n/a'}"
        f" | wrongly refused {s.false_refusals}",
        f"Out-of-scope       : {s.refusals_correct}/{s.refusal_total} correctly refused"
        f" | answered anyway {s.answered_out_of_scope}",
        f"Overall            : {s.passed}/{s.total} ({_pct(s.passed, s.total)}) | questions with no response {s.errors}",
        f"Retrieval          : expected section cited for {s.retrieval_hits}/{s.retrieval_total} in-scope questions"
        f" ({_pct(s.retrieval_hits, s.retrieval_total)}) | mean reciprocal rank "
        f"{f'{s.mrr:.2f}' if s.mrr is not None else 'n/a'}",
    ]
    if s.latency is not None:
        lat = s.latency
        lines.append(f"Latency            : mean {_secs(lat.mean_ms)} | median {_secs(lat.median_ms)}"
                     f" | p95 {_secs(lat.p95_ms)} | max {_secs(lat.max_ms)}  ({lat.count} answered questions)")
        if lat.slow:
            shown = ", ".join(f"{qid} {_secs(ms)}" for qid, ms in lat.slow[:SLOWEST_SHOWN])
            lines.append(f"                     over {_limit(slow_ms)}: {lat.slow_count}/{lat.count}"
                         f" ({_pct(lat.slow_count, lat.count)}) — slowest {shown}")
        else:
            lines.append(f"                     over {_limit(slow_ms)}: none of {lat.count}")
        if latency_note:
            lines.append(f"                     ({latency_note})")
    if s.hallucination is not None and s.hallucination.answered:
        h = s.hallucination
        kinds = ", ".join(f"{kind} {n}" for kind, n in sorted(h.by_kind.items(), key=lambda kv: (-kv[1], kv[0])))
        lines.append(f"Likely hallucination: {h.flagged}/{h.answered} answers flagged ({_pct(h.flagged, h.answered)})"
                     + (f" — {kinds}" if kinds else ""))
        if h.flagged_items:
            shown = "; ".join(f"{qid} ({', '.join(kinds_)})" for qid, kinds_ in h.flagged_items[:FLAGGED_SHOWN])
            more = f"; and {len(h.flagged_items) - FLAGGED_SHOWN} more" if len(h.flagged_items) > FLAGGED_SHOWN else ""
            lines.append(f"                     flagged: {shown}{more}")
        lines.append("                     (heuristics that point a human at answers worth reading; they are not verdicts)")
    if s.judged:
        counts = ", ".join(f"{verdict} {n}" for verdict, n in sorted(s.judge_counts.items()))
        lines.append(f"Gemini judge       : {counts} | agrees with the keyword check on {s.judge_agrees}/{s.judged}")
    return "\n".join(lines)


def format_run_line(index: int, total: int, results: list[ItemResult], slow_ms: float = DEFAULT_SLOW_MS) -> str:
    """One line per run when a run is repeated (the full summary would be repeated N times)."""
    s = summarise(results, slow_ms)
    parts = [f"Run {index}/{total}: {s.passed}/{s.total} passed ({_pct(s.passed, s.total)})", f"no response {s.errors}"]
    if s.latency is not None:
        parts.append(f"median {_secs(s.latency.median_ms)}, {s.latency.slow_count} over {_limit(slow_ms)}")
    if s.hallucination is not None and s.hallucination.answered:
        parts.append(f"flagged {s.hallucination.flagged}/{s.hallucination.answered}")
    return " | ".join(parts)


def format_stability(runs: list[list[ItemResult]], slow_ms: float = DEFAULT_SLOW_MS) -> str:
    """After repeated runs: accuracy per run, and the questions that did not come out the same every time."""
    stability, total = question_stability(runs, slow_ms), len(runs)
    summaries = [summarise(run, slow_ms) for run in runs]
    rates = [s.accuracy for s in summaries if s.accuracy is not None]
    lines = [f"== Stability over {total} runs ==",
             "Accuracy per run   : " + ", ".join(f"{s.passed}/{s.total}" for s in summaries)
             + (f"  (mean {100 * sum(rates) / len(rates):.1f}%, min {100 * min(rates):.1f}%, max {100 * max(rates):.1f}%)"
                if rates else "")]
    unstable = [q for q in stability if not q["same_outcome_every_run"]]
    steady = len(stability) - len(unstable)
    lines.append(f"Same outcome every run: {steady}/{len(stability)} questions")
    if unstable:
        shown = "; ".join(f"{q['id']} passed {q['passes']}/{q['runs']} ({' → '.join(q['outcomes'])})" for q in unstable[:FLAGGED_SHOWN])
        more = f"; and {len(unstable) - FLAGGED_SHOWN} more" if len(unstable) > FLAGGED_SHOWN else ""
        lines.append(f"Not the same every run: {shown}{more}")
    recurring = [f"{q['id']} {kind} {n}/{q['runs']}" for q in stability for kind, n in q["flag_runs"].items()]
    lines.append("Hallucination flags: " + ("; ".join(recurring[:FLAGGED_SHOWN]) + (f"; and {len(recurring) - FLAGGED_SHOWN} more"
                                            if len(recurring) > FLAGGED_SHOWN else "") if recurring else "none in any run"))
    always_slow = sum(q["slow_runs"] == q["runs"] for q in stability)
    sometimes = sum(0 < q["slow_runs"] < q["runs"] for q in stability)
    lines.append(f"Over {_limit(slow_ms)}      : {always_slow} questions in every run, {sometimes} in some runs")
    return "\n".join(lines)


def _parse_args(argv: Optional[list[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m evals", description="Run the golden question set through /ask.")
    parser.add_argument("--url", help="base URL of a deployed site (default: run the route in this process)")
    parser.add_argument("--judge", action="store_true", help="also grade each answer with Gemini (opt-in; uses quota)")
    parser.add_argument("--only", help="comma-separated question ids to run, e.g. g01,g05")
    parser.add_argument("--top-k", type=int, default=None, help="how many chunks /ask retrieves (default: the API's)")
    parser.add_argument("--delay", type=float, default=None,
                        help=f"seconds between questions (default {DEFAULT_HTTP_DELAY_SECONDS:g} with --url, otherwise 0)")
    parser.add_argument("--slow-seconds", type=float, default=DEFAULT_SLOW_MS / 1000,
                        help="flag questions that take longer than this (default %(default)g); flagged, never failed")
    parser.add_argument("--quota-wait", type=float, default=DEFAULT_QUOTA_WAIT_SECONDS,
                        help="seconds to wait before retrying a question that hit Gemini's quota (retried up to "
                             f"{QUOTA_RETRIES} times; default %(default)g)")
    parser.add_argument("--repeat", type=int, default=1,
                        help=f"run the whole set this many times (1-{MAX_REPEAT}) and show which questions are not stable")
    saving = parser.add_mutually_exclusive_group()
    saving.add_argument("--report", type=Path, help="where to save the JSON report (default evals/reports/run-<time>.json)")
    saving.add_argument("--no-report", action="store_true", help="do not save a report")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None, client_factory: Optional[Callable] = None) -> int:
    args = _parse_args(argv)
    if args.slow_seconds <= 0:
        print("--slow-seconds must be greater than 0", file=sys.stderr)
        return 2
    slow_ms = args.slow_seconds * 1000
    if not 1 <= args.repeat <= MAX_REPEAT:
        print(f"--repeat must be between 1 and {MAX_REPEAT}", file=sys.stderr)
        return 2
    items = load_golden_set()
    problems = validate(items)
    if problems:
        print("The golden set is not sound, so nothing was run:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2
    if args.only:
        wanted = [part.strip() for part in args.only.split(",") if part.strip()]
        unknown = sorted(set(wanted) - {item.id for item in items})
        if unknown:
            print(f"Unknown question id(s): {', '.join(unknown)}", file=sys.stderr)
            return 2
        items = [item for item in items if item.id in wanted]
    delay = args.delay if args.delay is not None else (DEFAULT_HTTP_DELAY_SECONDS if args.url else 0.0)
    factory = client_factory or (lambda: HttpClient(args.url) if args.url else InProcessClient())

    target = args.url or "this process (real route, database and Gemini from .env)"
    times = f", {args.repeat} times" if args.repeat > 1 else ""
    print(f"Running {len(items)} question(s) against {target}{' with the Gemini judge' if args.judge else ''}{times}\n", flush=True)

    started_at = datetime.now(timezone.utc)
    runs: list[list[ItemResult]] = []
    in_progress: Optional[list[ItemResult]] = None
    interrupted = False
    try:
        with factory() as client:
            for index in range(1, args.repeat + 1):
                if args.repeat > 1:
                    print(f"--- Run {index}/{args.repeat} ---", flush=True)
                bucket: list[ItemResult] = []
                in_progress = bucket

                def show(result: ItemResult, bucket: list[ItemResult] = bucket) -> None:
                    bucket.append(result)
                    print(format_result(result, slow_ms), flush=True)

                runs.append(run_eval(items, client, judge=args.judge, top_k=args.top_k, delay=delay,
                                     quota_wait=args.quota_wait, on_result=show))
                in_progress = None
                if args.repeat > 1:
                    print(format_run_line(index, args.repeat, runs[-1], slow_ms) + "\n", flush=True)
    except EvalSetupError as exc:
        print(f"Could not start: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        interrupted = True
        if in_progress:                                  # keep the questions of the run that was under way
            runs.append(in_progress)
        print("\nInterrupted: saving what had finished.", file=sys.stderr)

    note = (f"measured over HTTP from this machine to {args.url}" if args.url else
            "measured in this process on this machine, with the database and Gemini from .env — not on a deployed site")
    if runs:
        print("\n" + (format_summary(runs[0], slow_ms, note) if len(runs) == 1 else format_stability(runs, slow_ms)))

    save_failed = False
    if runs and not args.no_report:
        report = build_report(
            runs, started_at=started_at, finished_at=datetime.now(timezone.utc), slow_ms=slow_ms, complete=not interrupted,
            target={"mode": "http" if args.url else "in-process", "url": args.url, "latency_note": note},
            options={"judge": args.judge, "top_k": args.top_k, "slow_seconds": args.slow_seconds, "delay": delay,
                     "repeat": args.repeat, "quota_wait": args.quota_wait, "only": [i.id for i in items] if args.only else None},
        )
        path = args.report or default_report_path()
        try:
            print(f"\nReport saved to {write_report(report, path)}")
        except OSError as exc:
            print(f"\nCould not save the report to {path}: {exc}", file=sys.stderr)
            save_failed = True
    if interrupted:
        return 130
    return 1 if save_failed or any(r.outcome == ERROR for run in runs for r in run) else 0


if __name__ == "__main__":
    sys.exit(main())
