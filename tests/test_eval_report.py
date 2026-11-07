"""
tests/test_eval_report.py  –  Phase 13.5 (D-052)
The JSON report: what goes in it, what must never go in it, the cross-run stability maths, and saving it safely.
Offline: it builds reports from scored results and writes only under pytest's temporary folders.
"""

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.config import settings
from evals import report as report_module
from evals.golden import GOLDEN_PATH, load_golden_set
from evals.report import (
    SCHEMA_VERSION, build_report, default_report_path, environment_info, git_state, question_stability, result_to_dict,
    summary_to_dict, write_report,
)
from evals.results import AskResult, Flag, Judgement, SourceRef
from evals.scoring import score_item, summarise

pytestmark = pytest.mark.usefixtures("no_network")

ITEMS = {item.id: item for item in load_golden_set()}
ROLLBACK, HPA, COOKIES = ITEMS["g05"], ITEMS["g06"], ITEMS["g17"]
GOOD = "Per the Kubernetes Cluster Operations Guide (4.3 Rollback): `kubectl rollout undo deployment/knowops-api --to-revision=3`."
REFUSAL = "I don't have enough information in the knowledge base to answer that."
SOURCE = SourceRef("data/docs/kubernetes_operations.md", "4.3 Rollback", 0.82, title="Kubernetes Cluster Operations Guide",
                   content="kubectl rollout undo deployment/knowops-api --to-revision=3 -n production")
START = datetime(2026, 11, 7, 17, 28, 15, tzinfo=timezone.utc)
FINISH = datetime(2026, 11, 7, 17, 31, 2, tzinfo=timezone.utc)
ENVIRONMENT = {"chat_model": "m", "embed_model": "e", "golden_set_sha256": "0" * 64, "git_commit": "abc1234", "git_dirty": False}


def ask(answer, *sources, ms=1000.0, status=200, error=None):
    return AskResult(status=status, answer=answer, sources=tuple(sources), latency_ms=ms, request_id="kops-eval-x", error=error)


def scored(item, answer, *sources, ms=1000.0, **kwargs):
    return score_item(item, ask(answer, *sources, ms=ms, **kwargs))


def make_report(runs, **overrides):
    arguments = dict(started_at=START, finished_at=FINISH, target={"mode": "in-process", "url": None},
                     options={"repeat": len(runs)}, environment=ENVIRONMENT)
    return build_report(runs, **{**arguments, **overrides})


# --- one question ---------------------------------------------------------------------------------------------

def test_a_question_result_carries_everything_needed_to_review_it_later():
    result = scored(ROLLBACK, GOOD, SOURCE, ms=6234.56)
    data = result_to_dict(result)
    assert (data["id"], data["kind"], data["outcome"], data["passed"]) == ("g05", "command", "PASS", True)
    assert (data["facts_found"], data["facts_missing"], data["coverage"]) == (["rollout undo", "--to-revision=3"], [], 1.0)
    assert (data["retrieved"], data["retrieval_rank"], data["refused"]) == (True, 1, False)
    assert (data["latency_ms"], data["slow"], data["status"], data["error"]) == (6234.6, True, 200, None)
    assert data["answer"] == GOOD and data["request_id"] == "kops-eval-x" and data["question"] == ROLLBACK.question
    assert data["sources"] == [{"document": SOURCE.document, "heading": "4.3 Rollback", "title": SOURCE.title, "similarity": 0.82}]
    assert data["flags"] == [] and data["judge"] is None


def test_flags_the_judge_and_the_slow_threshold_are_recorded():
    from dataclasses import replace
    result = replace(scored(ROLLBACK, "It takes 9 hours.", SOURCE, ms=3000.0),
                     judge=Judgement("incorrect", "wrong", False, "invents 9 hours"))
    assert result_to_dict(result, slow_ms=2000.0)["slow"] is True and result_to_dict(result, slow_ms=5000.0)["slow"] is False
    data = result_to_dict(result)
    assert [f["kind"] for f in data["flags"]] == ["uncited", "unsupported_quantity"]
    assert data["judge"] == {"verdict": "incorrect", "reason": "wrong", "faithful": False, "unsupported": "invents 9 hours"}


def test_a_failed_question_is_recorded_with_its_error_and_is_never_slow():
    data = result_to_dict(scored(ROLLBACK, "", ms=90_000.0, status=503, error="HTTP 503: down"))
    assert (data["outcome"], data["error"], data["status"], data["slow"], data["coverage"]) == ("ERROR", "HTTP 503: down", 503, False, None)


def test_the_retrieved_text_is_not_stored_only_where_it_came_from():
    secret_text = "SENTINEL-RETRIEVED-TEXT-DO-NOT-STORE"
    source = SourceRef(SOURCE.document, SOURCE.heading, 0.8, title=SOURCE.title, content=secret_text)
    assert secret_text not in json.dumps(make_report([[scored(ROLLBACK, GOOD, source)]]))


def test_a_summary_becomes_plain_json_with_its_derived_accuracy():
    run = [scored(ROLLBACK, GOOD, SOURCE, ms=7000.0), scored(HPA, REFUSAL), scored(COOKIES, REFUSAL)]
    data = summary_to_dict(summarise(run))
    assert (data["total"], data["passed"], data["errors"]) == (3, 2, 0) and data["accuracy"] == pytest.approx(2 / 3)
    assert data["latency"]["slow"] == [["g05", 7000.0]] and data["hallucination"]["answered"] == 1
    assert json.loads(json.dumps(data)) == data


# --- stability across runs ----------------------------------------------------------------------------------------

def three_runs():
    pass_fast = lambda ms: scored(ROLLBACK, GOOD, SOURCE, ms=ms)                         # noqa: E731
    fail = lambda ms: scored(ROLLBACK, "Run kubectl rollout undo.", SOURCE, ms=ms)        # noqa: E731  (misses a fact)
    cookies = lambda: scored(COOKIES, REFUSAL)                                           # noqa: E731
    return [[pass_fast(2000), cookies()], [fail(8000), cookies()], [pass_fast(6000), cookies()]]


def test_stability_counts_passes_outcomes_and_timing_per_question():
    stability = {q["id"]: q for q in question_stability(three_runs())}
    g05 = stability["g05"]
    assert (g05["runs"], g05["passes"], g05["outcomes"]) == (3, 2, ["PASS", "MISSING_FACTS", "PASS"])
    assert g05["same_outcome_every_run"] is False and g05["slow_runs"] == 2
    assert g05["latency_ms"] == {"min": 2000.0, "median": 6000.0, "max": 8000.0}
    assert stability["g17"]["same_outcome_every_run"] is True and stability["g17"]["passes"] == 3


def test_a_flag_is_counted_once_per_run_however_many_times_it_is_raised_and_errors_have_no_latency():
    twice = lambda: scored(ROLLBACK, "It takes 9 hours or 8 minutes.", SOURCE)             # noqa: E731  two quantity flags
    broken = scored(ROLLBACK, "", status=503, error="HTTP 503", ms=60_000.0)
    stability = question_stability([[twice()], [twice()], [broken]])[0]
    assert stability["flag_runs"] == {"uncited": 2, "unsupported_quantity": 2}
    assert stability["latency_ms"] == {"min": 1000.0, "median": 1000.0, "max": 1000.0}     # the failed call is left out
    assert question_stability([[broken]])[0]["latency_ms"] is None


# --- the report -----------------------------------------------------------------------------------------------------

def test_a_report_has_the_documented_shape_and_survives_a_json_round_trip():
    report = make_report(three_runs(), options={"repeat": 3, "judge": False})
    assert (report["schema_version"], report["tool"], report["complete"]) == (SCHEMA_VERSION, "python -m evals", True)
    assert (report["started_at"], report["finished_at"]) == ("2026-11-07T17:28:15+00:00", "2026-11-07T17:31:02+00:00")
    assert report["target"] == {"mode": "in-process", "url": None} and report["options"] == {"repeat": 3, "judge": False}
    assert report["environment"] == ENVIRONMENT
    assert [run["index"] for run in report["runs"]] == [1, 2, 3] and all(len(run["results"]) == 2 for run in report["runs"])
    assert report["runs"][1]["summary"]["passed"] == 1 and report["runs"][1]["results"][0]["outcome"] == "MISSING_FACTS"
    assert [q["id"] for q in report["stability"]] == ["g05", "g17"]
    assert json.loads(json.dumps(report)) == report


def test_the_overall_block_gives_accuracy_per_run_and_names_the_unstable_questions():
    overall = make_report(three_runs())["overall"]
    assert overall["runs"] == 3 and overall["accuracy_per_run"] == [1.0, 0.5, 1.0]
    assert overall["accuracy_mean"] == pytest.approx(2.5 / 3) and (overall["accuracy_min"], overall["accuracy_max"]) == (0.5, 1.0)
    assert overall["unstable_questions"] == ["g05"]


def test_an_interrupted_report_says_so_and_an_empty_one_has_no_averages():
    assert make_report(three_runs()[:1], complete=False)["complete"] is False
    empty = make_report([])
    assert empty["overall"]["accuracy_mean"] is None and empty["runs"] == [] and empty["stability"] == []


def test_the_real_environment_block_names_the_model_the_golden_set_and_the_code_version():
    environment = environment_info()
    assert environment["chat_model"] == settings.gemini_chat_model and environment["embed_model"] == settings.gemini_embed_model
    assert environment["golden_set_sha256"] == hashlib.sha256(GOLDEN_PATH.read_bytes()).hexdigest()
    assert {"git_commit", "git_dirty"} <= set(environment)


@pytest.mark.parametrize("status,dirty", [("", False), (" M app/main.py\n?? new.py\n", True)])
def test_the_report_says_which_commit_ran_and_whether_the_tree_had_uncommitted_changes(monkeypatch, status, dirty):
    def scripted_git(command, **kwargs):
        stdout = "abc1234\n" if command[1] == "rev-parse" else status
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")
    monkeypatch.setattr(report_module.subprocess, "run", scripted_git)
    assert git_state() == {"git_commit": "abc1234", "git_dirty": dirty}


def test_a_git_failure_gives_unknown_not_a_wrong_answer(monkeypatch):
    monkeypatch.setattr(report_module.subprocess, "run",
                        lambda command, **kw: subprocess.CompletedProcess(command, 128, stdout="", stderr="not a repo"))
    assert git_state() == {"git_commit": None, "git_dirty": None}


def test_without_git_the_code_version_is_unknown_rather_than_an_error(monkeypatch):
    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")
    monkeypatch.setattr(report_module.subprocess, "run", no_git)
    assert git_state() == {"git_commit": None, "git_dirty": None}


def test_no_credential_or_token_can_end_up_in_a_report(monkeypatch):
    sentinels = {"app_password": "SENTINEL-PASSWORD-1", "jwt_secret": "SENTINEL-JWT-SECRET-2", "gemini_api_key": "SENTINEL-KEY-3",
                 "cron_secret": "SENTINEL-CRON-4", "database_url": "SENTINEL-DB-5"}
    for name, value in sentinels.items():
        monkeypatch.setattr(settings, name, value)
    text = json.dumps(build_report(three_runs(), started_at=START, finished_at=FINISH,
                                   target={"mode": "http", "url": "https://example.test"}, options={"repeat": 3}))
    assert not [v for v in sentinels.values() if v in text] and "SENTINEL" not in text


# --- saving it --------------------------------------------------------------------------------------------------------

def test_the_default_report_name_is_a_sortable_utc_timestamp_in_the_report_folder(reports_dir):
    assert default_report_path(START) == reports_dir / "run-2026-11-07T17-28-15Z.json"
    assert default_report_path(START, directory=Path("/x")) == Path("/x/run-2026-11-07T17-28-15Z.json")
    assert default_report_path(START) < default_report_path(FINISH)                       # names sort in time order


def test_a_report_is_written_as_readable_json_with_its_text_intact(tmp_path):
    answer = "RTO – 4 hours › see section 1"
    path = write_report(make_report([[scored(ROLLBACK, answer, SOURCE)]]), tmp_path / "deep" / "er" / "r.json")
    text = path.read_text(encoding="utf-8")
    assert text.endswith("}\n") and '\n  "schema_version": 1' in text           # indented, ends with a newline
    assert answer in text                                                         # not escaped to – / ›
    assert json.loads(text)["runs"][0]["results"][0]["answer"] == answer
    assert [p.name for p in path.parent.iterdir()] == ["r.json"]                  # no temporary file left


def test_a_failed_save_leaves_the_old_report_untouched_and_no_temporary_file(tmp_path, monkeypatch):
    path = tmp_path / "r.json"
    path.write_text("OLD REPORT", encoding="utf-8")

    def broken_replace(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(report_module.os, "replace", broken_replace)
    with pytest.raises(OSError, match="disk full"):
        write_report(make_report([[scored(ROLLBACK, GOOD, SOURCE)]]), path)
    assert path.read_text(encoding="utf-8") == "OLD REPORT" and [p.name for p in tmp_path.iterdir()] == ["r.json"]


def test_scratch_runs_are_git_ignored_and_a_baseline_is_not():
    """The policy in evals/report.py's docstring, checked against the real .gitignore."""
    def ignored(name):
        return subprocess.run(["git", "check-ignore", "-q", name], cwd=report_module.REPO_ROOT).returncode == 0
    assert ignored("evals/reports/run-2026-11-07T17-28-15Z.json")
    assert ignored("evals/reports/run-2026-11-07T17-28-15Z.json.tmp")
    assert not ignored("evals/reports/baseline-2026-11-07.json")


@pytest.fixture
def reports_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(report_module, "DEFAULT_REPORT_DIR", tmp_path / "reports")
    return tmp_path / "reports"
