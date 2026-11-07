"""
evals/golden.py  –  Phase 13.1 (D-047)
The golden question set: load it, and check that it is still grounded in the runbooks it came from.

Every in-scope item names the runbook section its answer comes from, lists the short facts a correct answer must
contain (`expected_facts`, used for scoring in 13.2), and carries a reference answer. validate() proves, offline:
each fact really appears in that section (so the set cannot drift from the docs), each fact appears in the
reference answer (so a perfect answer scores 100%), and each section name is one the app's own chunker produces
(so it can be compared with the `heading` of a source returned by /ask). Items that must be refused name terms
that must NOT appear in any runbook, so they stay out of scope if the docs change.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from scripts.ingest import DOCS_DIR, split_by_headings

GOLDEN_PATH = Path(__file__).with_name("golden_set.json")

# The fixed refusal in app/llm.py's SYSTEM_INSTRUCTION; tests/test_golden_set.py checks the two stay in step.
REFUSAL_ANSWER = "I don't have enough information in the knowledge base to answer that."

KINDS = frozenset({"numeric", "procedure", "command", "factual", "diagnosis", "list", "refusal"})
MIN_ITEMS, MAX_ITEMS = 15, 20          # the build guide: "a golden set of 15–20 Q&A pairs"
MIN_ITEMS_PER_DOC = 2

_PUNCTUATION = str.maketrans({"–": "-", "—": "-", "‑": "-", "’": "'", "‘": "'", "“": '"', "”": '"'})


def normalize(text: str) -> str:
    """Lower-case, one space between words, typographic dashes and quotes plain, Markdown code/bold marks removed.
    Used on both sides of every comparison, so `kubectl rollout undo` matches **kubectl rollout undo**."""
    return " ".join(text.translate(_PUNCTUATION).replace("`", "").replace("*", "").casefold().split())


@dataclass(frozen=True)
class GoldenItem:
    id: str
    question: str
    kind: str
    expected_answer: str
    expected_facts: tuple[str, ...] = ()
    source_doc: Optional[str] = None        # file name in data/docs/, None for items that must be refused
    source_section: Optional[str] = None    # the heading the chunker gives the section
    must_refuse: bool = False
    absent_terms: tuple[str, ...] = field(default=())   # refusal items only: terms no runbook may contain


def load_golden_set(path: Path = GOLDEN_PATH) -> list[GoldenItem]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        GoldenItem(
            id=item["id"], question=item["question"], kind=item["kind"], expected_answer=item["expected_answer"],
            expected_facts=tuple(item.get("expected_facts", [])), source_doc=item.get("source_doc"),
            source_section=item.get("source_section"), must_refuse=item.get("must_refuse", False),
            absent_terms=tuple(item.get("absent_terms", [])),
        )
        for item in data["items"]
    ]


def load_runbook_sections(docs_dir: Path = DOCS_DIR) -> dict[str, dict[str, str]]:
    """{file name: {heading: section text}} exactly as the app's chunker splits each runbook."""
    sections: dict[str, dict[str, str]] = {}
    for path in sorted(docs_dir.glob("*.md")):
        by_heading: dict[str, str] = {}
        for heading, body in split_by_headings(path.read_text(encoding="utf-8")):
            by_heading.setdefault(heading, f"{heading}\n{body}")
        sections[path.name] = by_heading
    return sections


def validate(items: list[GoldenItem], sections: Optional[dict[str, dict[str, str]]] = None) -> list[str]:
    """Every problem found, as readable strings; an empty list means the set is sound."""
    sections = load_runbook_sections() if sections is None else sections
    problems: list[str] = []

    if not MIN_ITEMS <= len(items) <= MAX_ITEMS:
        problems.append(f"set has {len(items)} items; the guide asks for {MIN_ITEMS}-{MAX_ITEMS}")
    for label, values in (("id", [i.id for i in items]), ("question", [normalize(i.question) for i in items])):
        for value in sorted({v for v in values if values.count(v) > 1}):
            problems.append(f"duplicate {label}: {value!r}")

    all_docs_text = normalize(" ".join(text for doc in sections.values() for text in doc.values()))
    per_doc: dict[str, int] = {}

    for item in items:
        where = item.id
        if not re.fullmatch(r"g\d{2}", item.id):
            problems.append(f"{where}: id must look like g01")
        if not item.question.strip().endswith("?") or not 15 <= len(item.question) <= 200:
            problems.append(f"{where}: question must end with '?' and be 15-200 characters")
        if item.kind not in KINDS:
            problems.append(f"{where}: unknown kind {item.kind!r}")
        if len(item.expected_answer.strip()) < 20:
            problems.append(f"{where}: expected_answer is too short")

        if item.must_refuse:
            if item.kind != "refusal":
                problems.append(f"{where}: a must_refuse item must have kind 'refusal'")
            if item.expected_answer != REFUSAL_ANSWER:
                problems.append(f"{where}: expected_answer must be the standard refusal")
            if item.source_doc or item.source_section or item.expected_facts:
                problems.append(f"{where}: a refusal item has no source_doc, source_section or expected_facts")
            if not item.absent_terms:
                problems.append(f"{where}: a refusal item needs absent_terms")
            for term in item.absent_terms:
                if normalize(term) in all_docs_text:
                    problems.append(f"{where}: {term!r} appears in the runbooks, so this question is no longer out of scope")
            continue

        if item.kind == "refusal" or item.absent_terms:
            problems.append(f"{where}: only must_refuse items use kind 'refusal' or absent_terms")
        doc = sections.get(item.source_doc or "")
        if doc is None:
            problems.append(f"{where}: source_doc {item.source_doc!r} is not a file in data/docs/")
            continue
        per_doc[item.source_doc] = per_doc.get(item.source_doc, 0) + 1
        section = doc.get(item.source_section or "")
        if section is None:
            problems.append(f"{where}: {item.source_section!r} is not a section of {item.source_doc}")
            continue
        if not 2 <= len(item.expected_facts) <= 5:
            problems.append(f"{where}: expected_facts must list 2-5 facts, found {len(item.expected_facts)}")
        for fact in item.expected_facts:
            if len(fact.strip()) < 2:
                problems.append(f"{where}: fact {fact!r} is too short to be a meaningful check")
            if normalize(fact) not in normalize(section):
                problems.append(f"{where}: fact {fact!r} does not appear in {item.source_doc} > {item.source_section}")
            if normalize(fact) not in normalize(item.expected_answer):
                problems.append(f"{where}: fact {fact!r} is missing from its own expected_answer")

    for doc in sections:
        if per_doc.get(doc, 0) < MIN_ITEMS_PER_DOC:
            problems.append(f"{doc} has {per_doc.get(doc, 0)} question(s); at least {MIN_ITEMS_PER_DOC} are expected")
    if not any(i.must_refuse for i in items):
        problems.append("the set has no question that must be refused")
    return problems
