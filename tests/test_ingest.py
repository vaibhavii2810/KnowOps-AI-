from scripts.ingest import CHUNK_SIZE, DOCS_DIR, make_chunks


def test_chunks_respect_size_and_paragraphs():
    para = "word " * 60  # ~300 chars
    doc = f"# Title\n\n## Section\n\n{para}\n\n{para}\n\n{para}"
    chunks = make_chunks(doc)
    assert len(chunks) == 3  # two 300-char paragraphs can't share a 500-char chunk
    assert all(h == "Section" for h, _ in chunks)
    assert all(c.strip() == para.strip() for _, c in chunks)


def test_seed_docs_chunk_within_limit():
    for path in DOCS_DIR.glob("*.md"):
        for _, content in make_chunks(path.read_text(encoding="utf-8")):
            assert len(content) <= CHUNK_SIZE, (path.name, len(content))
