"""
tests/test_golden_set.py  –  Phase 13.1 (D-047)
The golden question set is sound and still grounded in the runbooks. Offline: only reads evals/golden_set.json and
data/docs/*.md. The second half feeds the validator deliberately broken sets, to prove it notices each defect.
"""

import json
from dataclasses import replace

import pytest

from app.llm import SYSTEM_INSTRUCTION
from evals.golden import (
    GOLDEN_PATH, KINDS, MAX_ITEMS, MAX_VARIANTS_PER_FACT, MIN_ITEMS, REFUSAL_ANSWER, GoldenItem, accepted_forms,
    fact_present, load_golden_set, load_runbook_sections, normalize, validate,
)

pytestmark = pytest.mark.usefixtures("no_network")

ALLOWED_KEYS = {"id", "question", "kind", "expected_answer", "expected_facts", "source_doc", "source_section",
                "must_refuse", "absent_terms", "fact_variants"}


@pytest.fixture(scope="module")
def items():
    return load_golden_set()


@pytest.fixture(scope="module")
def sections():
    return load_runbook_sections()


# --- the shipped set -------------------------------------------------------------------------------------

def test_the_shipped_golden_set_is_valid_and_grounded_in_the_runbooks(items, sections):
    assert validate(items, sections) == []


def test_it_has_the_size_and_spread_the_guide_asks_for(items, sections):
    in_scope = [i for i in items if not i.must_refuse]
    assert MIN_ITEMS <= len(items) <= MAX_ITEMS
    assert len(in_scope) == 16 and len(items) - len(in_scope) == 3
    assert {i.source_doc for i in in_scope} == set(sections)                    # every runbook is exercised
    assert len({i.kind for i in in_scope}) >= 5                                 # not 16 versions of one question
    assert sum(len(i.expected_facts) for i in in_scope) >= 40


def test_the_json_uses_only_known_fields_and_every_field_is_loaded():
    raw = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert raw["version"] == 1
    for item in raw["items"]:
        assert set(item) <= ALLOWED_KEYS, set(item) - ALLOWED_KEYS


def test_the_refusal_answer_is_the_one_the_app_is_told_to_give():
    assert REFUSAL_ANSWER in SYSTEM_INSTRUCTION


def test_each_refusal_item_names_terms_absent_from_every_runbook(items, sections):
    everything = normalize(" ".join(text for doc in sections.values() for text in doc.values()))
    refusals = [i for i in items if i.must_refuse]
    assert refusals and all(i.absent_terms for i in refusals)
    for item in refusals:
        for term in item.absent_terms:
            assert normalize(term) not in everything, (item.id, term)


def test_a_perfect_answer_would_score_full_marks(items):
    """13.2 will count how many expected_facts an answer contains; the reference answer must contain all of them."""
    for item in items:
        if not item.must_refuse:
            assert all(normalize(f) in normalize(item.expected_answer) for f in item.expected_facts), item.id


# --- normalize() -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("fact,answer", [
    ("kubectl rollout undo", "Run `kubectl rollout undo deployment/knowops-api`"),
    ("War Room", "Create a **War Room** in Slack"),
    ("P2 - High", "That is P2 – High"),                      # en dash in the runbook, hyphen in the fact
    ("don't wait", "Escalate (don’t wait)"),                 # curly apostrophe
    ("exponential backoff", "uses   Exponential\nBackoff"),   # case and whitespace
    ("-pooler", "the pooled (`-pooler`) string"),
])
def test_normalize_makes_formatting_differences_irrelevant(fact, answer):
    assert normalize(fact) in normalize(answer)


def test_normalize_does_not_make_different_facts_match():
    assert normalize("--to-revision=3") not in normalize("kubectl rollout undo --to-revision=5")
    assert normalize("4 hours") not in normalize("an RTO of 14 hour window")


# --- the validator catches each kind of defect ----------------------------------------------------------

def problems_after(items, sections, index, **changes):
    broken = list(items)
    broken[index] = replace(broken[index], **changes)
    return validate(broken, sections)


def contains(problems, text):
    return any(text in p for p in problems)


def test_a_fact_that_is_not_in_the_cited_section_is_caught(items, sections):
    problems = problems_after(items, sections, 0, expected_facts=("4 hours", "99 hours"),
                              expected_answer=items[0].expected_answer + " Also 99 hours.")
    assert contains(problems, "g01: fact '99 hours' does not appear in disaster_recovery_runbook.md")


def test_a_fact_missing_from_its_own_reference_answer_is_caught(items, sections):
    problems = problems_after(items, sections, 0, expected_answer="The targets are four hours and one hour.")
    assert contains(problems, "is missing from its own expected_answer")


def test_a_fact_taken_from_the_wrong_section_is_caught(items, sections):
    """g04's facts (pg_ctl promote, db-replica-01) live only in 4.2; cite 2. Incident Classification instead."""
    problems = problems_after(items, sections, 3, source_section="2. Incident Classification")
    assert contains(problems, "g04: fact 'pg_ctl promote' does not appear in disaster_recovery_runbook.md > 2. Incident")


def test_short_numeric_facts_can_match_a_neighbouring_section_so_they_are_a_weak_check():
    """Known limit of keyword scoring (D-047): g01's '4 hours' and '1 hour' also appear in the severity table, so an
    answer quoting a P1/P3 time would still contain them. Distinctive facts (commands, names) do not have this problem."""
    sections = load_runbook_sections()["disaster_recovery_runbook.md"]
    assert normalize("4 hours") in normalize(sections["2. Incident Classification"])
    assert normalize("1 hour") in normalize(sections["2. Incident Classification"])


def test_an_unknown_document_or_section_is_caught(items, sections):
    assert contains(problems_after(items, sections, 0, source_doc="no_such_runbook.md"), "is not a file in data/docs/")
    assert contains(problems_after(items, sections, 0, source_section="9. Nothing Here"), "is not a section of")


def test_too_few_or_too_short_facts_are_caught(items, sections):
    assert contains(problems_after(items, sections, 0, expected_facts=("4 hours",)), "must list 2-5 facts")
    assert contains(problems_after(items, sections, 0, expected_facts=("4 hours", "1")), "too short")


def test_duplicates_are_caught(items, sections):
    assert contains(problems_after(items, sections, 1, id="g01"), "duplicate id: 'g01'")
    assert contains(problems_after(items, sections, 1, question=items[0].question.upper()), "duplicate question")


def test_a_bad_kind_or_id_or_question_is_caught(items, sections):
    assert contains(problems_after(items, sections, 0, kind="trivia"), "unknown kind")
    assert contains(problems_after(items, sections, 0, id="q1"), "id must look like g01")
    assert contains(problems_after(items, sections, 0, question="Tell me about RTO"), "must end with '?'")


def test_the_set_size_must_stay_within_the_guides_range(items, sections):
    assert contains(validate(items[:10], sections), "the guide asks for 15-20")
    padded = items + [replace(items[0], id=f"g{n}", question=f"Variant {n}?") for n in range(20, 25)]
    assert contains(validate(padded, sections), "the guide asks for 15-20")


def test_a_runbook_with_too_few_questions_is_caught(items, sections):
    without_on_call = [i for i in items if i.source_doc != "on_call_guide.md"]
    problems = validate(without_on_call + [replace(items[0], id="g90", question="Padding question one?"),
                                           replace(items[0], id="g91", question="Padding question two?")], sections)
    assert contains(problems, "on_call_guide.md has 0 question(s)")


def test_a_refusal_item_that_has_become_answerable_is_caught(items, sections):
    refusal = next(n for n, i in enumerate(items) if i.must_refuse)
    problems = problems_after(items, sections, refusal, absent_terms=("kubernetes",))
    assert contains(problems, "appears in the runbooks, so this question is no longer out of scope")


def test_a_refusal_item_must_expect_the_standard_refusal_and_no_source(items, sections):
    refusal = next(n for n, i in enumerate(items) if i.must_refuse)
    assert contains(problems_after(items, sections, refusal, expected_answer="Probably tea, I think."), "standard refusal")
    assert contains(problems_after(items, sections, refusal, source_doc="on_call_guide.md"), "has no source_doc")
    assert contains(problems_after(items, sections, refusal, absent_terms=()), "needs absent_terms")
    assert contains(problems_after(items, sections, refusal, kind="factual"), "kind 'refusal'")


def test_an_in_scope_item_cannot_pose_as_a_refusal(items, sections):
    assert contains(problems_after(items, sections, 0, kind="refusal"), "only must_refuse items")


def test_a_set_with_no_refusal_items_is_caught(items, sections):
    keep = [i for i in items if not i.must_refuse]
    assert contains(validate(keep + [replace(keep[0], id="g90", question="Padding question one?")], sections),
                    "no question that must be refused")


# --- accepted variants (D-049) -------------------------------------------------------------------------

def item_g09(items):
    return next(n for n, i in enumerate(items) if i.id == "g09")


def test_a_fact_is_satisfied_by_itself_or_by_any_accepted_variant(items):
    g09 = items[item_g09(items)]
    assert accepted_forms(g09, "Git repository") == ("Git repository", "Git repositories")
    assert accepted_forms(g09, "ConfigMaps") == ("ConfigMaps",)                       # no variants listed
    for wording in ("in a Git repository (even private)", "in **Git repositories**, even private ones"):
        assert fact_present(g09, "Git repository", wording)
    assert not fact_present(g09, "Git repository", "use GitOps tooling")             # a different thing
    assert not fact_present(g09, "ConfigMaps", "never in a Git repositories")         # variants are per fact


def test_the_shipped_set_uses_variants_only_for_a_wording_difference():
    """g09's variant is the plural of its fact (D-049); every variant in the set must stay that modest."""
    for item in load_golden_set():
        for fact, forms in item.fact_variants.items():
            assert fact in item.expected_facts and 1 <= len(forms) <= MAX_VARIANTS_PER_FACT
    g09 = next(i for i in load_golden_set() if i.id == "g09")
    assert g09.fact_variants == {"Git repository": ("Git repositories",)}


def test_the_canonical_fact_is_still_checked_against_the_runbook_even_when_variants_exist(items, sections):
    """A variant never has to appear in the runbook, but the fact it stands for does."""
    g09 = item_g09(items)
    assert "git repositories" not in normalize(sections["kubernetes_operations.md"]["8. Secrets Management"])
    assert validate(items, sections) == []
    problems = problems_after(items, sections, g09, expected_facts=("AWS Secrets Manager", "ConfigMaps", "Git repo"),
                              fact_variants={"Git repo": ("Git repositories",)},
                              expected_answer=items[g09].expected_answer.replace("Git repository", "Git repo"))
    assert problems == []                                                             # "Git repo" is in the section
    problems = problems_after(items, sections, g09, fact_variants={"Git repository": ("Git repositories",)},
                              expected_facts=("AWS Secrets Manager", "ConfigMaps", "Svn repository"))
    assert contains(problems, "fact 'Svn repository' does not appear in kubernetes_operations.md")


def test_a_variant_for_a_fact_the_item_does_not_have_is_caught(items, sections):
    problems = problems_after(items, sections, item_g09(items), fact_variants={"Mercurial": ("Hg",)})
    assert contains(problems, "g09: fact_variants has an entry for 'Mercurial', which is not one of its expected_facts")


def test_empty_too_many_repeated_and_too_short_variants_are_caught(items, sections):
    g09 = item_g09(items)
    assert contains(problems_after(items, sections, g09, fact_variants={"Git repository": ()}), "must have 1-3 variants")
    four = ("Git repos", "Git repositories", "git-repositories", "Git trees")
    assert contains(problems_after(items, sections, g09, fact_variants={"Git repository": four}), "must have 1-3 variants")
    assert contains(problems_after(items, sections, g09, fact_variants={"Git repository": ("GIT  REPOSITORY",)}),
                    "repeats the fact or another variant")
    assert contains(problems_after(items, sections, g09, fact_variants={"Git repository": ("Git repos", "git repos")}),
                    "repeats the fact or another variant")
    assert contains(problems_after(items, sections, g09, fact_variants={"Git repository": ("g",)}), "too short")


def test_a_refusal_item_cannot_carry_variants(items, sections):
    refusal = next(n for n, i in enumerate(items) if i.must_refuse)
    problems = problems_after(items, sections, refusal, fact_variants={"anything": ("else",)})
    assert contains(problems, "has no source_doc, source_section, expected_facts or fact_variants")


def test_the_dataclass_is_immutable():
    item = GoldenItem(id="g01", question="Why?", kind="factual", expected_answer="Because.")
    with pytest.raises(Exception):
        item.id = "g02"
    assert "refusal" in KINDS
