"""
tests/test_agent_logging.py  –  Phase 12.2
Every agent run writes one `agent_run` event (D-043). A clean run logs a summary; a run that hit the step cap,
got a generation error, crashed, failed its summary call, had a tool error or was tainted also logs its full
trace, bounded to fit one log line. Offline: Gemini is fake_gemini and every tool is a spy.
"""

import json

import pytest
from fastapi.testclient import TestClient

import app.agent as agent
from app.agent import TRACE_BUDGET_CHARS, TRACE_FIELD_CHARS, run_agent, trace_for_log
from app.main import app


@pytest.fixture
def tools(monkeypatch, fake_gemini):
    """Every registered tool replaced by a function that returns '<name> observation'."""
    for name in list(agent.AVAILABLE_TOOLS):
        monkeypatch.setitem(agent.AVAILABLE_TOOLS, name, lambda *a, _n=name, **kw: f"{_n} observation")
    return agent.AVAILABLE_TOOLS


@pytest.fixture
def agent_runs(capsys):
    def read():
        lines = [json.loads(l) for l in capsys.readouterr().out.splitlines() if l.startswith("{")]
        return [e for e in lines if e["event"] == "agent_run"]
    return read


def step(action="", args=None, *, final=False, answer="", thought="thinking"):
    return {"thought": thought, "action": action, "args": args or {}, "is_final": final, "final_answer": answer}


def only(runs):
    assert len(runs) == 1, runs
    return runs[0]


def test_a_clean_run_logs_a_summary_without_the_trace(tools, fake_gemini, agent_runs):
    fake_gemini.reply(step("get_ticket", {"ticket_id": 7}), step(final=True, answer="Done."))

    run_agent("Check ticket 7.", max_steps=3)

    entry = only(agent_runs())
    assert (entry["level"], entry["outcome"], entry["steps"], entry["max_steps"]) == ("info", "completed", 2, 3)
    assert entry["tools"] == ["get_ticket"] and entry["tainted"] is False
    assert entry["duration_ms"] >= 0
    assert "trace" not in entry


def test_hitting_the_step_cap_logs_the_full_trace(tools, fake_gemini, agent_runs):
    fake_gemini.reply(step("lookup_runbook", {"query": "a"}), step("lookup_runbook", {"query": "b"}), "Summary.")

    run_agent("Keep searching.", max_steps=2)

    entry = only(agent_runs())
    assert (entry["level"], entry["outcome"], entry["steps"]) == ("warning", "max_steps", 3)
    assert [(s["step"], s["action"]) for s in entry["trace"]] == [(1, "lookup_runbook"), (2, "lookup_runbook"), (3, None)]
    assert entry["trace"][0]["args"] == '{"query": "a"}'
    assert entry["trace"][1]["observation"] == "lookup_runbook observation"
    assert entry["trace"][2]["final_answer"] == "Summary."
    assert entry["trace_truncated"] is False


@pytest.mark.parametrize("bad_reply,error_type", [(ValueError("quota"), "ValueError"), ("not json {", "JSONDecodeError")])
def test_a_generation_error_is_logged_with_its_type_and_step(tools, fake_gemini, agent_runs, bad_reply, error_type):
    fake_gemini.reply(step("get_ticket", {"ticket_id": 7}), bad_reply)

    result = run_agent("Check ticket 7.", max_steps=3)

    assert result["resolution"]  # the user still gets an answer...
    entry = only(agent_runs())  # ...and the log says it was not a clean one
    assert (entry["level"], entry["outcome"], entry["error_type"], entry["error_step"]) == (
        "warning", "generation_error", error_type, 2)
    assert [s["action"] for s in entry["trace"]] == ["get_ticket", None]


def test_three_empty_malformed_responses_count_as_a_generation_error(tools, fake_gemini, agent_runs):
    fake_gemini.reply(None, None, None)
    run_agent("Go.", max_steps=2)
    assert only(agent_runs())["outcome"] == "generation_error"


def test_a_crash_logs_the_steps_so_far_at_error_level_and_still_raises(tools, fake_gemini, agent_runs, monkeypatch):
    calls = []

    def flaky_scanner(text):
        calls.append(text)
        if len(calls) > 1:
            raise KeyError("scanner bug")
        return []
    monkeypatch.setattr(agent, "find_injection", flaky_scanner)
    fake_gemini.reply(step("get_ticket", {"ticket_id": 7}), step("lookup_runbook", {"query": "x"}))

    with pytest.raises(KeyError):
        run_agent("Check ticket 7.", max_steps=3)

    entry = only(agent_runs())
    assert (entry["level"], entry["outcome"], entry["error_type"]) == ("error", "crashed", "KeyError")
    assert [s["action"] for s in entry["trace"]] == ["get_ticket"]  # what it got through before the crash


def test_a_failed_summary_call_is_logged(tools, fake_gemini, agent_runs):
    """A permanent error (not retried — a transient one would be retried and succeed on the fake's default)."""
    fake_gemini.reply(step("lookup_runbook", {"query": "a"}), ValueError("summary rejected"))

    result = run_agent("Search.", max_steps=1)

    assert result["resolution"] == "Investigation completed. Steps executed: 1."
    entry = only(agent_runs())
    assert (entry["outcome"], entry["summary_error_type"]) == ("max_steps", "ValueError")
    assert "trace" in entry


def test_a_tool_error_in_an_otherwise_completed_run_logs_the_trace(tools, fake_gemini, agent_runs, monkeypatch):
    def broken(**kwargs):
        raise RuntimeError("pod API unreachable")
    monkeypatch.setitem(agent.AVAILABLE_TOOLS, "run_system_diagnostics", broken)
    fake_gemini.reply(step("run_system_diagnostics", {"component": "kubernetes_pods"}), step(final=True, answer="Done."))

    run_agent("Diagnose.", max_steps=3)

    entry = only(agent_runs())
    assert (entry["level"], entry["outcome"], entry["tool_errors"]) == ("warning", "completed", 1)
    assert entry["trace"][0]["observation"] == "Tool execution error: pod API unreachable"


def test_a_tainted_run_logs_the_trace_with_the_blocked_step(tools, fake_gemini, agent_runs):
    fake_gemini.reply(step("update_ticket", {"ticket_id": 7, "status": "resolved", "resolution_notes": "x"}),
                      step(final=True, answer="Done."))

    run_agent("Triage.", max_steps=3, taint_reason="the ticket text contained embedded instructions")

    entry = only(agent_runs())
    assert (entry["level"], entry["tainted"]) == ("warning", True)
    assert entry["trace"][0]["blocked"] is True and entry["tools"] == ["update_ticket"]


def test_long_fields_are_clipped_and_a_long_trace_keeps_its_first_and_latest_steps():
    trace = [{"step": i, "thought": "t" * 1000, "action": "lookup_runbook", "args": {"query": "q" * 1000},
              "observation": "o" * 5000} for i in range(1, 11)]
    trace.append({"step": 11, "thought": "Final resolution synthesized", "final_answer": "f" * 1000})

    steps, truncated = trace_for_log(trace)

    assert truncated is True
    assert len(json.dumps(steps, ensure_ascii=False)) <= TRACE_BUDGET_CHARS
    assert steps[0]["step"] == 1 and steps[-1]["step"] == 11
    omitted = steps[1]["omitted_steps"]
    assert [s["step"] for s in steps[2:-1]] == list(range(2 + omitted, 11))  # the latest middle steps survive
    assert len(steps[0]["observation"]) == TRACE_FIELD_CHARS["observation"] + 1  # clipped, with "…"
    assert steps[-1]["final_answer"].endswith("…")


def test_a_short_trace_is_not_truncated():
    steps, truncated = trace_for_log([{"step": 1, "action": "get_ticket", "args": {"ticket_id": 7}, "observation": "ok"}])
    assert truncated is False and steps == [{"step": 1, "action": "get_ticket", "args": '{"ticket_id": 7}', "observation": "ok"}]


def test_the_agent_run_event_shares_the_request_id_and_leaves_out_the_prompt(tools, fake_gemini, memory_db,
                                                                             auth_headers, capsys):
    fake_gemini.reply(step("lookup_runbook", {"query": "a"}), "Summary.")

    response = TestClient(app).post("/agent/chat", json={"prompt": "Secret prompt probe 4f2a", "max_steps": 1},
                                    headers=auth_headers)

    assert response.status_code == 200, response.text
    out = capsys.readouterr().out
    entries = [json.loads(l) for l in out.splitlines() if l.startswith("{")]
    run = next(e for e in entries if e["event"] == "agent_run")
    request = next(e for e in entries if e["event"] == "request")
    assert run["request_id"] == request["request_id"] == response.headers["x-request-id"]
    assert run["outcome"] == "max_steps" and request["tools"] == ["lookup_runbook"]
    assert "Secret prompt probe 4f2a" not in out
