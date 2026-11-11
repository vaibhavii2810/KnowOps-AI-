import pytest

from scripts.ingest import (
    CHUNK_SIZE, DOCS_DIR, MIN_CHUNK_CHARS, compute_content_hash, ingest_file, make_chunks, reindex_knowledge_base,
)
from app.db import get_conn


def test_chunks_respect_size_and_paragraphs():
    para = "word " * 60  # ~300 chars
    doc = f"# Title\n\n## Section\n\n{para}\n\n{para}\n\n{para}"
    chunks = make_chunks(doc)
    assert len(chunks) == 3  # two 300-char paragraphs can't share a 500-char chunk
    assert all(h == "Section" for h, _ in chunks)
    assert all(c.strip() == para.strip() for _, c in chunks)


def test_shell_comments_in_code_fences_are_not_headings():
    doc = (
        "# Runbook\n\n## 4.2 Manual Failover Steps\n\n"
        "```bash\n# 1. Promote the replica to primary\npg_ctl promote -D /var/lib/postgresql/16/main\n"
        "# 2. Confirm promotion\npsql -c 'SELECT pg_is_in_recovery();'\n```\n"
    )
    chunks = make_chunks(doc)
    assert [h for h, _ in chunks] == ["4.2 Manual Failover Steps"]
    assert "pg_ctl promote" in chunks[0][1]


def test_short_section_is_not_lost_from_the_index():
    """Bug #6 (external bug report, Medium, D-060): a section under MIN_CHUNK_CHARS (80) used to be
    silently dropped — a one-line emergency contact or command could never be retrieved at all."""
    doc = "# Runbook\n\n## Emergency Contacts\n\nCall +1-555-0100.\n\n## Normal Section\n\n" + "word " * 60
    chunks = make_chunks(doc)
    assert any(h == "Emergency Contacts" and "+1-555-0100" in c for h, c in chunks)


def test_a_short_section_is_merged_into_a_neighbor_not_left_as_a_tiny_fragment():
    """The short piece survives by joining a neighboring piece within the same heading, so the index
    never ends up with a standalone sub-80-char chunk either. The paragraph is sized (~494 chars) so
    pack_paragraphs itself is forced to put "Short tail." in its own piece first — otherwise packing
    would combine them before make_chunks' merge step ever runs, and this test wouldn't exercise it."""
    para = "word " * 99  # ~494 chars: + the 11-char tail would be 507, over CHUNK_SIZE, so packed separately
    doc = f"# Title\n\n## Section\n\n{para}\n\nShort tail.\n"
    chunks = make_chunks(doc)
    assert len(chunks) == 1  # the short tail joined the paragraph, not a second tiny chunk
    assert "Short tail." in chunks[0][1]


def test_a_document_that_is_only_short_sections_keeps_every_one():
    """Nothing to merge into at all — each section stays its own (short) chunk rather than vanishing."""
    doc = "# Contacts\n\n## On-call\n\nCall +1-555-0100.\n\n## Escalation\n\nPage the SRE lead.\n"
    chunks = make_chunks(doc)
    assert [h for h, _ in chunks] == ["On-call", "Escalation"]
    assert "+1-555-0100" in chunks[0][1] and "SRE lead" in chunks[1][1]


def test_seed_docs_keep_failover_commands():
    text = (DOCS_DIR / "disaster_recovery_runbook.md").read_text(encoding="utf-8")
    assert any("pg_ctl promote" in c for _, c in make_chunks(text))


def test_seed_docs_chunk_within_limit():
    """D-060: a chunk is ~CHUNK_SIZE, not a hard ceiling — merging a short piece into a near-full
    neighbor (so a short section is never dropped outright) can push a little past it. The ceiling
    here allows exactly that one merge's worth of overage, not unbounded growth."""
    for path in DOCS_DIR.glob("*.md"):
        for _, content in make_chunks(path.read_text(encoding="utf-8")):
            assert len(content) <= CHUNK_SIZE + MIN_CHUNK_CHARS, (path.name, len(content))


def test_compute_content_hash_is_deterministic_and_content_sensitive():
    """Phase 9.1 (D-029): the hash must be stable for identical content and change on any edit."""
    a = compute_content_hash("# Doc\n\nSome text.")
    b = compute_content_hash("# Doc\n\nSome text.")
    c = compute_content_hash("# Doc\n\nSome DIFFERENT text.")
    assert a == b
    assert a != c
    assert len(a) == 64  # sha256 hex digest


def test_ingest_file_skips_unchanged_content_without_embedding(tmp_path, monkeypatch, db_backend):
    """
    Phase 9.1 (D-029): re-ingesting a file whose content hasn't changed must not call
    embed_document at all (the whole point — GET /cron/reindex should be free and fast
    on a normal night when nothing in data/docs/ changed).
    """
    embed_calls = []
    monkeypatch.setattr(
        "scripts.ingest.embed_document",
        lambda text: embed_calls.append(text) or [0.0] * 768,
    )

    # A real file under DOCS_DIR, so `filepath.relative_to(PROJECT_ROOT)` works like production.
    test_file = DOCS_DIR / "_test_9_1_tmp.md"
    source = test_file.relative_to(DOCS_DIR.parents[1]).as_posix()
    body_v1 = "Some content here for the regression test. " * 3  # > 80 chars, clears MIN_CHUNK_CHARS
    test_file.write_text(f"# Temp Doc\n\n## Section\n\n{body_v1}\n", encoding="utf-8")

    try:
        with get_conn() as conn:
            first = ingest_file(test_file, conn, verbose=False)
            assert first["unchanged"] is False
            assert first["inserted"] > 0
            assert len(embed_calls) == first["inserted"]

            # Re-ingest the exact same content — must skip entirely, zero new embed calls.
            calls_before = len(embed_calls)
            second = ingest_file(test_file, conn, verbose=False)
            assert second["unchanged"] is True
            assert len(embed_calls) == calls_before  # no new Gemini calls

            # Now actually change the content — must re-embed.
            body_v2 = "Some DIFFERENT content for the regression test now. " * 3
            test_file.write_text(f"# Temp Doc\n\n## Section\n\n{body_v2}\n", encoding="utf-8")
            third = ingest_file(test_file, conn, verbose=False)
            assert third["unchanged"] is False
            assert len(embed_calls) > calls_before
    finally:
        test_file.unlink(missing_ok=True)
        with get_conn() as conn:
            conn.execute("DELETE FROM documents WHERE source = %s", (source,))


@pytest.mark.live
def test_ingest_stores_a_real_embedding_that_is_still_findable_by_retrieve():
    """Bug #25 (external bug report, Low, D-080): get_conn() no longer registers pgvector's adapter by
    default — insert_chunk() keeps it explicitly (get_conn(vectors=True)). This is the live round trip
    proving that explicit path still works end to end with a real Gemini embedding, not a mocked one:
    ingest a temp file, then retrieve() a matching question and confirm the chunk comes back."""
    test_file = DOCS_DIR / "_test_25_tmp.md"
    source = test_file.relative_to(DOCS_DIR.parents[1]).as_posix()
    unique_phrase = "Zorbatron flux capacitor realignment procedure"
    test_file.write_text(
        f"# Temp Doc\n\n## {unique_phrase}\n\n"
        f"To realign the zorbatron flux capacitor, first power down the quantum relay. " * 3,
        encoding="utf-8",
    )
    try:
        with get_conn(vectors=True) as conn:
            result = ingest_file(test_file, conn, verbose=False)
            assert result["inserted"] > 0

        from app.rag import retrieve
        hits = retrieve(unique_phrase, top_k=1, threshold=0.0)
        assert hits
        assert hits[0].heading == unique_phrase
    finally:
        test_file.unlink(missing_ok=True)
        with get_conn() as conn:
            conn.execute("DELETE FROM documents WHERE source = %s", (source,))


def test_reindex_removes_documents_whose_file_is_gone(tmp_path, monkeypatch, db_backend):
    """
    Bug #5 (external bug report, Medium, D-059): deleting a runbook from data/docs/ used to leave its
    document and chunks in the DB forever, so a retired procedure kept being retrieved and cited as
    current guidance. reindex_knowledge_base() now removes any stored document whose file is gone
    (chunks follow via ON DELETE CASCADE).
    """
    monkeypatch.setattr("scripts.ingest.embed_document", lambda text: [0.0] * 768)
    monkeypatch.setattr("scripts.ingest.EMBED_SLEEP_SECONDS", 0)  # free-tier pacing; pointless here too

    test_file = DOCS_DIR / "_test_9_1_bug5_tmp.md"
    source = test_file.relative_to(DOCS_DIR.parents[1]).as_posix()
    body = "Some content here for the regression test. " * 3  # > 80 chars, clears MIN_CHUNK_CHARS
    test_file.write_text(f"# Temp Doc\n\n## Section\n\n{body}\n", encoding="utf-8")

    try:
        first = reindex_knowledge_base(force=False, verbose=False)
        assert first["documents_removed"] == 0
        assert any(s["source"] == source for s in first["summaries"])

        test_file.unlink()  # the file "disappears" from data/docs/, like a retired runbook

        second = reindex_knowledge_base(force=False, verbose=False)
        assert second["documents_removed"] == 1
        assert not any(s["source"] == source for s in second["summaries"])

        with get_conn() as conn:
            assert conn.execute("SELECT id FROM documents WHERE source = %s", (source,)).fetchone() is None
    finally:
        test_file.unlink(missing_ok=True)
        with get_conn() as conn:
            conn.execute("DELETE FROM documents WHERE source = %s", (source,))
