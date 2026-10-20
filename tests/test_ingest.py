from scripts.ingest import CHUNK_SIZE, DOCS_DIR, make_chunks


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


def test_seed_docs_keep_failover_commands():
    text = (DOCS_DIR / "disaster_recovery_runbook.md").read_text(encoding="utf-8")
    assert any("pg_ctl promote" in c for _, c in make_chunks(text))


def test_seed_docs_chunk_within_limit():
    for path in DOCS_DIR.glob("*.md"):
        for _, content in make_chunks(path.read_text(encoding="utf-8")):
            assert len(content) <= CHUNK_SIZE, (path.name, len(content))
