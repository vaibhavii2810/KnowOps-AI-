"""
tests/test_eval_hallucination.py  –  Phase 13.4 (D-051)
The likely-hallucination flags, offline. The retrieved sources in these tests carry the real runbook text, so what counts
as "supported" is exactly what the app would have retrieved.
"""

from dataclasses import replace

import pytest

from evals.golden import load_golden_set, load_runbook_sections
from evals.hallucination import MIN_CODE_CHARS, code_spans, find_flags, quantities
from evals.results import (
    ANSWERED_OUT_OF_SCOPE, NO_CONTEXT, PHANTOM_CITATION, UNCITED, UNSUPPORTED_CODE, UNSUPPORTED_QUANTITY, AskResult,
    SourceRef,
)

pytestmark = pytest.mark.usefixtures("no_network")

ITEMS = {item.id: item for item in load_golden_set()}
SECTIONS = load_runbook_sections()
TITLES = tuple(next(iter(doc)) for doc in SECTIONS.values())      # each file's first heading is its title


def source(doc, heading):
    return SourceRef(f"data/docs/{doc}", heading, 0.8, title=next(iter(SECTIONS[doc])), content=SECTIONS[doc][heading])


DR_OVERVIEW = source("disaster_recovery_runbook.md", "1. Overview")
DR_FAILOVER = source("disaster_recovery_runbook.md", "4.2 Manual Failover Steps")
K8S_ROLLBACK = source("kubernetes_operations.md", "4.3 Rollback")
K8S_CANARY = source("kubernetes_operations.md", "4.2 Canary Deployment")

RTO = ITEMS["g01"]            # What are the RTO and RPO targets for Tier-1 services?
SEVERITY = ITEMS["g02"]       # ... a partial outage affecting more than 50% of users ...
FAILOVER = ITEMS["g04"]
COOKIES = ITEMS["g17"]
REFUSAL = "I don't have enough information in the knowledge base to answer that."


def ask(answer, *sources, status=200, error=None):
    return AskResult(status=status, answer=answer, sources=tuple(sources), latency_ms=1.0, error=error)


def kinds(flags):
    return [f.kind for f in flags]


def flags_for(item, answer, *sources, refused=False):
    return find_flags(item, ask(answer, *sources), refused, TITLES)


GOOD_RTO = "Based on the Disaster Recovery Runbook (1. Overview): the RTO target is 4 hours and the RPO target is 1 hour."


# --- quantities ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("a,b", [
    ("4 hours", "4-hour"), ("4 hours", "4 Hours"), ("4 hours", "4 hrs"), ("4 hours", "4 hr"), ("5 minutes", "5.0 minutes"), ("5 minutes", "5 mins"),
    ("5 minutes", "5-min"), ("30 seconds", "30 secs"), ("10 replicas", "replicas=10"), ("3 attempts", "attempts: 3"),
])
def test_the_same_quantity_written_two_ways_is_one_quantity(a, b):
    assert set(quantities(a)) == set(quantities(b)) and len(quantities(a)) == 1


def test_quantities_keep_the_text_as_written_and_cover_the_runbooks_units():
    found = quantities("Within 15 minutes use 512Mi and 70% CPU; scale to 10 replicas; wait 500ms; it takes 2 days.")
    assert found == {("15", "min"): "15 minutes", ("512", "mi"): "512Mi", ("70", "%"): "70%",
                     ("10", "replica"): "10 replicas", ("500", "ms"): "500ms", ("2", "d"): "2 days"}


@pytest.mark.parametrize("text", [
    "1. Acknowledge the alert", "port 8080 is open", "the p95 target", "GEMINI_API_503 fired", "version v2.3.1",
    "maxReplicas: 10", "10 million requests", "ap-southeast-1", "revision 3",
])
def test_bare_numbers_identifiers_and_lookalike_words_are_not_quantities(text):
    assert quantities(text) == {}


def test_a_different_number_or_a_different_unit_is_a_different_quantity():
    assert set(quantities("4 hours")) != set(quantities("6 hours"))
    assert set(quantities("4 hours")) != set(quantities("4 minutes"))


# --- code spans ----------------------------------------------------------------------------------------------

def test_inline_code_is_collected_and_short_or_repeated_spans_are_not():
    answer = "Run `kubectl rollout undo` then `ls`, `kubectl rollout undo` again, and set `1Gi`."
    assert code_spans(answer) == ["kubectl rollout undo"]
    assert MIN_CODE_CHARS == 4


def test_fenced_block_lines_are_checked_one_by_one_without_comments_or_continuations():
    answer = "Steps:\n```bash\n# check pods\nkubectl get pods -n production\nkubectl rollout undo deployment/x \\\n```\nthen `pg_ctl promote`."
    assert code_spans(answer) == ["kubectl get pods -n production", "kubectl rollout undo deployment/x", "pg_ctl promote"]


# --- the flags -----------------------------------------------------------------------------------------------

def test_a_faithful_cited_answer_is_not_flagged():
    assert flags_for(RTO, GOOD_RTO, DR_OVERVIEW) == ()


def test_an_answer_that_quotes_the_runbooks_own_wording_and_commands_is_not_flagged():
    answer = ("According to the Disaster Recovery Runbook (4.2 Manual Failover Steps): SSH to the standby, run "
              "`pg_ctl promote -D /var/lib/postgresql/16/main`, then `psql -c \"SELECT pg_is_in_recovery();\"`.")
    assert flags_for(FAILOVER, answer, DR_FAILOVER) == ()


def test_answering_with_nothing_retrieved_is_flagged_no_context():
    assert kinds(flags_for(RTO, "The RTO is usually a few hours.")) == [NO_CONTEXT]


def test_an_answer_that_names_none_of_the_retrieved_documents_is_flagged_uncited():
    assert kinds(flags_for(RTO, "The RTO target is 4 hours and the RPO target is 1 hour.", DR_OVERVIEW)) == [UNCITED]


@pytest.mark.parametrize("citation", [
    "Disaster Recovery Runbook",
    "disaster recovery runbook",
    "(*Source: Disaster Recovery Runbook › 1. Overview*)",
    "section 1. Overview of this document",                # by heading alone
])
def test_citing_by_title_or_by_section_heading_counts_as_cited(citation):
    assert UNCITED not in kinds(flags_for(RTO, f"{citation}: RTO 4 hours, RPO 1 hour.", DR_OVERVIEW))


def test_citing_a_runbook_that_was_not_retrieved_is_a_phantom_citation():
    answer = "Per the Kubernetes Cluster Operations Guide and the Disaster Recovery Runbook, the RTO is 4 hours."
    flags = flags_for(RTO, answer, DR_OVERVIEW)
    assert [(f.kind, f.detail) for f in flags] == [(PHANTOM_CITATION, "Kubernetes Cluster Operations Guide")]


def test_naming_a_runbook_the_question_itself_named_is_not_a_phantom_citation():
    asked = replace(RTO, question="What does the Kubernetes Cluster Operations Guide say about the RTO?")
    answer = "The Kubernetes Cluster Operations Guide does not cover it; the Disaster Recovery Runbook says RTO is 4 hours."
    assert PHANTOM_CITATION not in kinds(find_flags(asked, ask(answer, DR_OVERVIEW), False, TITLES))
    assert PHANTOM_CITATION in kinds(find_flags(RTO, ask(answer, DR_OVERVIEW), False, TITLES))   # same answer, not asked about


def test_a_runbook_cited_with_nothing_retrieved_is_a_phantom_citation_and_its_numbers_have_no_support():
    flags = flags_for(RTO, "The Disaster Recovery Runbook says the RTO is 4 hours.")
    assert kinds(flags) == [NO_CONTEXT, PHANTOM_CITATION, UNSUPPORTED_QUANTITY]


def test_a_number_that_is_not_in_the_retrieved_text_is_an_unsupported_quantity():
    wrong = GOOD_RTO.replace("4 hours", "6 hours")                            # the runbook says 4 hours
    flags = flags_for(RTO, wrong, DR_OVERVIEW)
    assert [(f.kind, f.detail) for f in flags] == [(UNSUPPORTED_QUANTITY, "6 hours")]


def test_a_quantity_written_differently_or_taken_from_the_question_is_supported():
    assert flags_for(RTO, GOOD_RTO.replace("4 hours", "4-hour"), DR_OVERVIEW) == ()
    asked_about_50 = "Disaster Recovery Runbook: more than 50% of users means P2, which has an RTO of 2 hours."
    severity_source = source("disaster_recovery_runbook.md", "2. Incident Classification")
    assert flags_for(SEVERITY, asked_about_50, severity_source) == ()          # 50% is in the question and the table


def test_a_quantity_the_runbook_writes_as_a_setting_is_supported():
    answer = "Per the Kubernetes Cluster Operations Guide (4.2 Canary Deployment), scale to 5 replicas once healthy."
    assert flags_for(ITEMS["g07"], answer, K8S_CANARY) == ()


def test_an_invented_command_is_an_unsupported_code_flag_and_a_runbook_command_is_not():
    answer = ("Per the Kubernetes Cluster Operations Guide (4.3 Rollback): run `kubectl rollout undo "
              "deployment/knowops-api` or, to wipe everything, `kubectl delete namespace production`.")
    flags = flags_for(ITEMS["g05"], answer, K8S_ROLLBACK)
    assert [(f.kind, f.detail) for f in flags] == [(UNSUPPORTED_CODE, "kubectl delete namespace production")]


def test_an_invented_line_in_a_code_block_is_caught_too():
    answer = ("Per the Disaster Recovery Runbook (4.2 Manual Failover Steps):\n```bash\n"
              "pg_ctl promote -D /var/lib/postgresql/16/main\nsystemctl restart postgresql\n```")
    assert [(f.kind, f.detail) for f in flags_for(FAILOVER, answer, DR_FAILOVER)] == [(UNSUPPORTED_CODE, "systemctl restart postgresql")]


def test_answering_an_out_of_scope_question_is_flagged_and_keeps_the_other_flags():
    flags = flags_for(COOKIES, "Cream the butter and sugar, then bake for 12 minutes.")
    assert kinds(flags) == [ANSWERED_OUT_OF_SCOPE, NO_CONTEXT, UNSUPPORTED_QUANTITY]


def test_refusals_and_failed_calls_are_never_flagged():
    assert find_flags(COOKIES, ask(REFUSAL), True, TITLES) == ()
    assert find_flags(RTO, ask("", status=503, error="HTTP 503"), False, TITLES) == ()
    assert find_flags(RTO, ask(GOOD_RTO, DR_OVERVIEW, status=500), False, TITLES) == ()


def test_flags_come_in_a_fixed_order_and_each_quantity_is_reported_once():
    answer = "It takes 9 hours or 9-hour windows, 7 minutes, and `kubectl nuke everything`."
    flags = flags_for(RTO, answer, DR_OVERVIEW)
    assert [(f.kind, f.detail) for f in flags] == [
        (UNCITED, ""), (UNSUPPORTED_QUANTITY, "7 minutes"), (UNSUPPORTED_QUANTITY, "9 hours"),
        (UNSUPPORTED_CODE, "kubectl nuke everything"),
    ]


def test_sources_without_a_title_do_not_cause_phantom_citations_or_crashes():
    untitled = SourceRef("data/docs/disaster_recovery_runbook.md", "1. Overview", 0.8, content="RTO Target: 4 hours")
    flags = flags_for(RTO, "The Kubernetes Cluster Operations Guide says the RTO is 4 hours.", untitled)
    assert PHANTOM_CITATION not in kinds(flags)       # we cannot tell which documents were retrieved, so we do not accuse
