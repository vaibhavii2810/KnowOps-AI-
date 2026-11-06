"""
tests/test_agent_dispatch.py  –  Phase 11.2
Unit tests for run_agent()'s tool dispatch, fully offline: Gemini is a scripted fake_gemini and every
tool in AVAILABLE_TOOLS is swapped for a spy, so these test the loop's routing, not the tools.
"""

import pytest

from app import agent
from app.agent import AVAILABLE_TOOLS, run_agent


class Spy:
    def __init__(self, name, result=None, error=None):
        self.name = name
        self.calls = []
        self.result = result if result is not None else f"{name} observation"
        self.error = error

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def spies(monkeypatch, fake_gemini):
    """Replace every registered tool with a spy (and use fake_gemini, so nothing leaves the process)."""
    replaced = {name: Spy(name) for name in AVAILABLE_TOOLS}
    for name, spy in replaced.items():
        monkeypatch.setitem(agent.AVAILABLE_TOOLS, name, spy)
    return replaced


def step(action="", args=None, *, final=False, answer="", thought="thinking"):
    return {"thought": thought, "action": action, "args": args or {}, "is_final": final, "final_answer": answer}


TOOL_CALLS = {
    "lookup_runbook": {"query": "database failover"},
    "get_ticket": {"ticket_id": 7},
    "create_ticket": {"subject": "API 500s", "description": "Gemini 503s", "priority": "P2"},
    "update_ticket": {"ticket_id": 7, "status": "resolved", "resolution_notes": "Fixed."},
    "escalate_to_human": {"ticket_id": None, "reason": "Full outage"},
    "run_system_diagnostics": {"component": "database"},
    "execute_recovery_action": {"action": "rollback_deployment", "target": "deployment/knowops-api"},
}


def test_every_registered_tool_has_a_dispatch_case():
    assert set(TOOL_CALLS) == set(AVAILABLE_TOOLS)


@pytest.mark.parametrize("tool", sorted(TOOL_CALLS))
def test_each_tool_is_dispatched_with_its_arguments(tool, spies, fake_gemini):
    fake_gemini.reply(step(tool, TOOL_CALLS[tool]), step(final=True, answer="Done."))

    result = run_agent("Handle the incident.", max_steps=3)

    assert spies[tool].calls == [((), TOOL_CALLS[tool])]  # the right tool, with exactly these kwargs
    assert all(not s.calls for name, s in spies.items() if name != tool)  # and no other tool
    first = result["steps"][0]
    assert (first["action"], first["args"], first["observation"]) == (tool, TOOL_CALLS[tool], f"{tool} observation")
    assert result["resolution"] == "Done."


def test_the_observation_is_fed_back_fenced_into_the_next_prompt(spies, fake_gemini):
    spies["get_ticket"].result = "Ticket #7: database is down"
    fake_gemini.reply(step("get_ticket", {"ticket_id": 7}), step(final=True, answer="Done."))

    run_agent("Check ticket 7.", max_steps=3)

    first_prompt, second_prompt = (call["contents"] for call in fake_gemini.chat_calls)
    assert "Ticket #7: database is down" not in first_prompt
    assert "Observation 1:" in second_prompt and "Ticket #7: database is down" in second_prompt
    assert '<untrusted_data source="tool: get_ticket">' in second_prompt  # fenced as data (D-034)


def test_list_args_are_passed_positionally_and_a_scalar_as_one_argument(spies, fake_gemini):
    fake_gemini.reply(
        step("get_ticket", [7]),
        {"thought": "t", "action": "lookup_runbook", "args": "kubernetes rollback", "is_final": False},
        step(final=True, answer="Done."),
    )

    run_agent("Go.", max_steps=3)

    assert spies["get_ticket"].calls == [((7,), {})]
    assert spies["lookup_runbook"].calls == [(("kubernetes rollback",), {})]


@pytest.mark.parametrize("action", ["", "drop_all_tables", "LOOKUP_RUNBOOK"])
def test_an_unknown_or_missing_action_runs_nothing_and_ends_the_loop(action, spies, fake_gemini):
    fake_gemini.reply(step(action, {"query": "x"}, thought="I am done.", answer="Final answer."))

    result = run_agent("Go.", max_steps=5)

    assert all(not s.calls for s in spies.values())
    assert len(fake_gemini.chat_calls) == 1
    assert result["resolution"] == "Final answer."


def test_without_a_final_answer_the_thought_becomes_the_answer(spies, fake_gemini):
    fake_gemini.reply(step("", thought="Nothing needed."))
    assert run_agent("Go.", max_steps=5)["resolution"] == "Nothing needed."


def test_a_tool_that_raises_becomes_an_observation_and_the_loop_continues(spies, fake_gemini):
    spies["run_system_diagnostics"].error = RuntimeError("pod API unreachable")
    fake_gemini.reply(step("run_system_diagnostics", {"component": "kubernetes_pods"}), step(final=True, answer="Done."))

    result = run_agent("Diagnose.", max_steps=3)

    assert result["steps"][0]["observation"] == "Tool execution error: pod API unreachable"
    assert result["resolution"] == "Done."
    assert len(fake_gemini.chat_calls) == 2


def test_wrong_argument_names_are_reported_back_to_the_model_not_raised(fake_gemini):
    """Uses the real tool: a hallucinated keyword is a TypeError, which the loop turns into an observation."""
    fake_gemini.reply(step("execute_recovery_action", {"verb": "restart"}), step(final=True, answer="Done."))

    result = run_agent("Fix it.", max_steps=3)

    assert result["steps"][0]["observation"].startswith("Tool execution error:")
    assert "verb" in result["steps"][0]["observation"]


def test_a_tool_call_bundled_with_is_final_still_runs_and_ends_the_loop(spies, fake_gemini):
    """Offline twin of the live D-027 regression test in test_agent.py."""
    fake_gemini.reply(step("update_ticket", TOOL_CALLS["update_ticket"], final=True, answer="Ticket resolved."))

    result = run_agent("Resolve ticket 7.", max_steps=3)

    assert spies["update_ticket"].calls == [((), TOOL_CALLS["update_ticket"])]
    assert len(fake_gemini.chat_calls) == 1
    assert result["resolution"] == "Ticket resolved."


@pytest.mark.parametrize("max_steps", [1, 3])
def test_max_steps_caps_tool_calls_then_one_summary_call(max_steps, spies, fake_gemini):
    """A model that never stops asking for tools is cut off after max_steps; one synthesis call
    (plain text, not JSON mode) then writes the resolution."""
    tool_steps = [step("lookup_runbook", {"query": f"try {i}"}) for i in range(max_steps)]
    fake_gemini.reply(*tool_steps, "Summary after the cap.")

    result = run_agent("Keep searching forever.", max_steps=max_steps)

    assert [c[1]["query"] for c in spies["lookup_runbook"].calls] == [f"try {i}" for i in range(max_steps)]
    assert len(fake_gemini.chat_calls) == max_steps + 1  # every step, plus the synthesis call
    summary_call = fake_gemini.chat_calls[-1]
    assert "Write the final SRE incident resolution report" in summary_call["contents"]
    assert "response_mime_type" not in summary_call["config"]
    assert result["total_steps"] == max_steps + 1
    assert result["resolution"] == "Summary after the cap."


def test_later_prompts_carry_the_whole_history(spies, fake_gemini):
    fake_gemini.reply(
        step("get_ticket", {"ticket_id": 7}, thought="first look"),
        step("run_system_diagnostics", {"component": "database"}, thought="then diagnose"),
        step(final=True, answer="Done."),
    )

    run_agent("Investigate ticket 7.", max_steps=5)

    third_prompt = fake_gemini.chat_calls[2]["contents"]
    assert "Task: Investigate ticket 7." in third_prompt
    assert third_prompt.index("Thought 1: first look") < third_prompt.index("Thought 2: then diagnose")
    assert "get_ticket observation" in third_prompt and "run_system_diagnostics observation" in third_prompt


# --- Phase 12 follow-up (D-045): the summary after a capped run must be plain text --------------------------

def test_the_summary_prompt_drops_the_json_format_instructions_but_keeps_the_task_and_steps(spies, fake_gemini):
    spies["get_ticket"].result = "Ticket #7: database is down"
    fake_gemini.reply(step("get_ticket", {"ticket_id": 7}), "Summary.")

    run_agent("Investigate ticket 7.", max_steps=1)

    summary = fake_gemini.chat_calls[-1]["contents"]
    assert "Format your thought and next action as JSON" in fake_gemini.chat_calls[0]["contents"]  # steps still use it
    assert "Format your thought and next action as JSON" not in summary
    assert '"is_final"' not in summary
    assert summary.startswith("Task: Investigate ticket 7.")
    assert "Observation 1:" in summary and "Ticket #7: database is down" in summary
    assert "Do not answer in JSON" in summary


@pytest.mark.parametrize("reply,expected", [
    ('```json\n{"thought": "Diagnosed.", "final_answer": "Restart the worker pod."}\n```', "Restart the worker pod."),
    ('{"thought": "Diagnosed.", "final_answer": "Restart the worker pod."}', "Restart the worker pod."),
    ('```\n{"thought": "Only a thought."}\n```', "Only a thought."),
])
def test_a_json_wrapped_summary_is_unwrapped_to_its_answer(reply, expected, spies, fake_gemini):
    fake_gemini.reply(step("get_ticket", {"ticket_id": 7}), reply)
    assert run_agent("Investigate ticket 7.", max_steps=1)["resolution"] == expected


@pytest.mark.parametrize("text", [
    "Restart the worker pod.",
    "Run this:\n```bash\nkubectl rollout restart deployment/knowops-worker\n```\nthen watch the pods.",
    "```bash\nkubectl get pods\n```",
    '{"not": "an answer"}',
    "{ this is not json",
])
def test_plain_text_and_markdown_answers_are_left_alone(text):
    from app.agent import plain_text_answer
    assert plain_text_answer(text) == text
