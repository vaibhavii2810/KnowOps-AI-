"""
evals/report.py  –  Phase 13.5 (D-052)
Turn finished runs into a JSON report and save it.

A report holds everything needed to read a run later without re-running it: when and how it ran, the model and code
version, a summary per run, every question's answer, sources, flags and timing, and — across repeated runs — which
questions did not come out the same every time. It never contains credentials or tokens: only answers, source
references (not their text) and run metadata.

    evals/reports/run-<UTC time>.json   written by every run; git-ignored, so scratch runs do not clutter the repo
    evals/reports/baseline-*.json       written on purpose (--report evals/reports/baseline-….json) and committed
"""

from __future__ import annotations

import hashlib
import json
import os
import statistics
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.config import settings
from evals.golden import GOLDEN_PATH
from evals.results import ERROR, ItemResult
from evals.scoring import DEFAULT_SLOW_MS, Summary, is_slow, summarise

SCHEMA_VERSION = 1
DEFAULT_REPORT_DIR = Path(__file__).with_name("reports")
REPO_ROOT = Path(__file__).resolve().parents[1]


def result_to_dict(result: ItemResult, slow_ms: float = DEFAULT_SLOW_MS) -> dict[str, Any]:
    ask, judge = result.ask, result.judge
    return {
        "id": result.item.id,
        "question": result.item.question,
        "kind": result.item.kind,
        "outcome": result.outcome,
        "passed": result.passed,
        "facts_found": list(result.facts_found),
        "facts_missing": list(result.facts_missing),
        "coverage": result.coverage,
        "retrieved": result.retrieved,
        "retrieval_rank": result.retrieval_rank,
        "refused": result.refused,
        "latency_ms": round(ask.latency_ms, 1),
        "slow": is_slow(result, slow_ms),
        "status": ask.status,
        "error": ask.error,
        "request_id": ask.request_id,
        "answer": ask.answer,
        "sources": [{"document": s.document, "heading": s.heading, "title": s.title, "similarity": s.similarity}
                    for s in ask.sources],
        "flags": [{"kind": f.kind, "detail": f.detail} for f in result.flags],
        "judge": None if judge is None else
        {"verdict": judge.verdict, "reason": judge.reason, "faithful": judge.faithful, "unsupported": judge.unsupported},
    }


def _plain(value: Any) -> Any:
    """Tuples become lists, so a report built in memory equals the same report read back from its JSON file."""
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def summary_to_dict(summary: Summary) -> dict[str, Any]:
    data = _plain(asdict(summary))
    data["accuracy"] = summary.accuracy
    return data


def question_stability(runs: list[list[ItemResult]], slow_ms: float = DEFAULT_SLOW_MS) -> list[dict[str, Any]]:
    """Per question, across runs: how often it passed, each run's outcome, which flags recurred, and its timing."""
    stability = []
    for question_id in dict.fromkeys(r.item.id for run in runs for r in run):
        mine = [r for run in runs for r in run if r.item.id == question_id]
        timed = [r.ask.latency_ms for r in mine if r.outcome != ERROR]
        flag_runs: dict[str, int] = {}
        for r in mine:
            for kind in dict.fromkeys(f.kind for f in r.flags):
                flag_runs[kind] = flag_runs.get(kind, 0) + 1
        stability.append({
            "id": question_id,
            "runs": len(mine),
            "passes": sum(r.passed for r in mine),
            "outcomes": [r.outcome for r in mine],
            "same_outcome_every_run": len({r.outcome for r in mine}) == 1,
            "flag_runs": flag_runs,
            "slow_runs": sum(is_slow(r, slow_ms) for r in mine),
            "latency_ms": None if not timed else {
                "min": round(min(timed), 1), "median": round(statistics.median(timed), 1), "max": round(max(timed), 1)},
        })
    return stability


def git_state() -> dict[str, Any]:
    """The short commit hash and whether the working tree had uncommitted changes; None for each if git is unavailable."""
    def git(*args: str) -> Optional[str]:
        try:
            done = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    commit, status = git("rev-parse", "--short", "HEAD"), git("status", "--porcelain")
    return {"git_commit": commit, "git_dirty": None if status is None else bool(status)}


def environment_info() -> dict[str, Any]:
    return {
        "chat_model": settings.gemini_chat_model,
        "embed_model": settings.gemini_embed_model,
        "golden_set_sha256": hashlib.sha256(GOLDEN_PATH.read_bytes()).hexdigest(),
        **git_state(),
    }


def build_report(
    runs: list[list[ItemResult]],
    *,
    started_at: datetime,
    finished_at: datetime,
    target: dict[str, Any],
    options: dict[str, Any],
    slow_ms: float = DEFAULT_SLOW_MS,
    complete: bool = True,
    environment: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    run_summaries = [summarise(run, slow_ms) for run in runs]
    accuracies = [s.accuracy for s in run_summaries if s.accuracy is not None]
    stability = question_stability(runs, slow_ms)
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "python -m evals",
        "complete": complete,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "target": target,
        "options": options,
        "environment": environment if environment is not None else environment_info(),
        "overall": {
            "runs": len(runs),
            "accuracy_per_run": accuracies,
            "accuracy_mean": statistics.fmean(accuracies) if accuracies else None,
            "accuracy_min": min(accuracies) if accuracies else None,
            "accuracy_max": max(accuracies) if accuracies else None,
            "unstable_questions": [q["id"] for q in stability if not q["same_outcome_every_run"]],
        },
        "runs": [
            {"index": index, "summary": summary_to_dict(summary), "results": [result_to_dict(r, slow_ms) for r in run]}
            for index, (run, summary) in enumerate(zip(runs, run_summaries), start=1)
        ],
        "stability": stability,
    }


def default_report_path(now: Optional[datetime] = None, directory: Optional[Path] = None) -> Path:
    now = now or datetime.now(timezone.utc)
    return (DEFAULT_REPORT_DIR if directory is None else directory) / f"run-{now.strftime('%Y-%m-%dT%H-%M-%SZ')}.json"


def write_report(report: dict[str, Any], path: Path) -> Path:
    """Write the report as JSON, all at once: a crash or Ctrl-C mid-write leaves the old file (or none), never half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)          # never leave a half-written file behind
        raise
    return path
