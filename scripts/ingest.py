"""
scripts/ingest.py  –  Phase 2.2 / 9.1
Knowledge-base ingestion pipeline.

Usage:
    python scripts/ingest.py                    # ingest new/changed docs in data/docs/
    python scripts/ingest.py --file path/to.md  # force-ingest a single file
    python scripts/ingest.py --reset            # wipe existing data then ingest all

How it works:
    1. Walk data/docs/ for *.md files (or use --file)
    2. Extract YAML front-matter for title / document-id metadata
    3. Skip a file whose SHA-256 content hash matches what's already stored for it
       (Phase 9.1, D-029) — no re-chunk, no Gemini calls, no DB writes
    4. Split the document into semantic chunks on Markdown heading boundaries
       (## and ### headings act as natural section delimiters; `#` lines inside
       ``` code fences are ignored — they're shell comments, not headings)
    5. Optionally further split large chunks at a max-token boundary (overlap window)
    6. Call embed_document() for every chunk  →  768-d vector via Gemini
    7. Upsert the document record (with its new content hash) and INSERT all chunks
    8. Print a clean progress summary

reindex_knowledge_base() is the reusable entry point — used by main() below (the CLI)
and by GET /cron/reindex (app/main.py).

Schema (managed by scripts/init_db.sql):
    documents(id, source, title, content_hash, created_at)
    chunks(id, document_id, chunk_index, heading, content, embedding, created_at)
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import textwrap
import time
from pathlib import Path
from typing import Generator

# Allow running from the project root without installing the package
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.db import get_conn
from app.llm import embed_document

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DOCS_DIR = PROJECT_ROOT / "data" / "docs"

# Target chunk size in characters (build guide 3.2: ~500 chars ≈ 125 tokens)
CHUNK_SIZE = 500

# Overlap used only when a single line is longer than CHUNK_SIZE and must be hard-split
CHUNK_OVERLAP = 50

# Minimum characters a chunk must have to be worth embedding
MIN_CHUNK_CHARS = 80

# How long to sleep between Gemini API calls to respect free-tier rate limits
EMBED_SLEEP_SECONDS = 0.5


# ---------------------------------------------------------------------------
# Markdown parsing helpers
# ---------------------------------------------------------------------------

def extract_frontmatter(text: str) -> tuple[dict, str]:
    """
    Extract YAML-style front-matter block (--- key: value ---) from the top
    of a markdown document.

    Returns:
        (metadata_dict, body_without_frontmatter)
    """
    meta: dict = {}
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            fm_block = text[3:end].strip()
            body = text[end + 3:].strip()
            for line in fm_block.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip()
            return meta, body
    return meta, text


def extract_title_from_markdown(text: str) -> str:
    """Return the first # Heading found in the document body, or empty string."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


def split_by_headings(text: str) -> list[tuple[str, str]]:
    """
    Split a Markdown document into sections based on ## and ### headings.

    Returns:
        List of (heading_text, section_body) tuples.
        The preamble before the first heading is returned with heading "".
    """
    heading_pattern = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
    fence_pattern = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
    sections: list[tuple[str, str]] = []

    # `# comment` lines inside ``` fences are shell comments, not headings
    fences = [(m.start(), m.end()) for m in fence_pattern.finditer(text)]
    matches = [
        m for m in heading_pattern.finditer(text)
        if not any(start <= m.start() < end for start, end in fences)
    ]
    if not matches:
        return [("", text.strip())]

    # Text before the first heading
    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections.append(("", preamble))

    for i, match in enumerate(matches):
        heading_text = match.group(2).strip()
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        if body:
            sections.append((heading_text, body))

    return sections


def split_text_with_overlap(
    text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> Generator[str, None, None]:
    """
    Yield successive character-level chunks from *text* with a small overlap
    window so semantic context is not lost at chunk boundaries.
    """
    start = 0
    while start < len(text):
        end = start + size
        yield text[start:end]
        start += size - overlap


def split_units(body: str, size: int = CHUNK_SIZE) -> Generator[str, None, None]:
    """
    Yield paragraphs no longer than *size*. An oversized paragraph is broken
    into its lines; only a single line longer than *size* is hard-split.
    """
    for para in re.split(r"\n\s*\n", body):
        para = para.strip()
        if len(para) <= size:
            yield para
            continue
        for line in para.splitlines():
            line = line.strip()
            if len(line) <= size:
                yield line
            else:
                yield from split_text_with_overlap(line, size)


def pack_paragraphs(body: str, size: int = CHUNK_SIZE) -> list[str]:
    """Greedily join paragraph units into pieces of at most *size* characters."""
    pieces: list[str] = []
    current = ""
    for unit in split_units(body, size):
        if not unit:
            continue
        if current and len(current) + 2 + len(unit) > size:
            pieces.append(current)
            current = unit
        else:
            current = f"{current}\n\n{unit}" if current else unit
    if current:
        pieces.append(current)
    return pieces


def make_chunks(text: str) -> list[tuple[str, str]]:
    """
    Full chunking pipeline for one document:
      1. Split on heading boundaries        →  coarse semantic sections
      2. Pack each section's paragraphs     →  ~CHUNK_SIZE pieces, never mid-paragraph
         unless a single line is itself too long

    Returns:
        List of (heading, chunk_text) tuples ready for embedding.
    """
    chunks: list[tuple[str, str]] = []

    for heading, body in split_by_headings(text):
        for piece in pack_paragraphs(body):
            piece = piece.strip()
            if len(piece) >= MIN_CHUNK_CHARS:
                chunks.append((heading, piece))

    return chunks


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def compute_content_hash(raw_text: str) -> str:
    """
    SHA-256 of the raw file content (frontmatter included, so a title/metadata-only
    edit still counts as a change). Used to detect new-or-changed files for
    GET /cron/reindex (Phase 9.1, D-029) without re-embedding unchanged ones.
    """
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


def get_stored_document(conn, source: str) -> tuple[int, str] | None:
    """Return (id, content_hash) for a previously-ingested document, or None if new."""
    row = conn.execute(
        "SELECT id, content_hash FROM documents WHERE source = %s", (source,)
    ).fetchone()
    return (row[0], row[1]) if row else None


def upsert_document(conn, source: str, title: str, content_hash: str) -> int:
    """
    Insert a document record if it doesn't exist, or update title + content_hash if it does.

    Returns the document's database id.
    """
    existing = conn.execute(
        "SELECT id FROM documents WHERE source = %s", (source,)
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE documents SET title = %s, content_hash = %s WHERE id = %s",
            (title, content_hash, existing[0]),
        )
        return existing[0]

    row = conn.execute(
        "INSERT INTO documents (source, title, content_hash) VALUES (%s, %s, %s) RETURNING id",
        (source, title, content_hash),
    ).fetchone()
    return row[0]


def delete_existing_chunks(conn, document_id: int) -> None:
    """Remove all chunks for a document so we can re-index from scratch."""
    conn.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))


def insert_chunk(
    conn,
    document_id: int,
    chunk_index: int,
    heading: str,
    content: str,
    embedding: list[float],
) -> None:
    """Insert a single embedded chunk into the chunks table."""
    conn.execute(
        """
        INSERT INTO chunks (document_id, chunk_index, heading, content, embedding)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (document_id, chunk_index, heading, content, embedding),
    )


# ---------------------------------------------------------------------------
# Per-file ingestion
# ---------------------------------------------------------------------------

def ingest_file(filepath: Path, conn, verbose: bool = True, force: bool = False) -> dict:
    """
    Ingest a single Markdown file into the database.

    If the file's content hash matches what's already stored for it and `force`
    is False, this is a no-op — no re-chunking, no Gemini calls, no DB writes
    (Phase 9.1, D-029): nightly cron runs stay fast and free when nothing changed.

    Returns a summary dict with counts (and "unchanged": True if skipped).
    """
    raw_text = filepath.read_text(encoding="utf-8")
    content_hash = compute_content_hash(raw_text)

    # Derive metadata
    _, body = extract_frontmatter(raw_text)
    title = extract_title_from_markdown(body) or filepath.stem.replace("_", " ").title()
    source = filepath.relative_to(PROJECT_ROOT).as_posix()  # same key on Windows and Vercel

    existing = get_stored_document(conn, source)
    if existing and not force and existing[1] == content_hash:
        if verbose:
            print(f"\n⏭️  Unchanged, skipping: {source}")
        return {
            "source": source, "title": title, "doc_id": existing[0],
            "total_chunks": 0, "inserted": 0, "skipped": 0, "unchanged": True,
        }

    if verbose:
        print(f"\n📄 Ingesting: {source}")
        print(f"   Title   : {title}")

    # Upsert the document row
    doc_id = upsert_document(conn, source, title, content_hash)
    delete_existing_chunks(conn, doc_id)

    # Chunk the document
    chunks = make_chunks(body)
    if verbose:
        print(f"   Chunks  : {len(chunks)}")

    # Embed and insert each chunk
    inserted = 0
    skipped = 0
    for idx, (heading, content) in enumerate(chunks):
        try:
            embedding = embed_document(content)
            insert_chunk(conn, doc_id, idx, heading, content, embedding)
            inserted += 1

            if verbose:
                heading_display = f"[{heading[:40]}]" if heading else "[intro]"
                print(
                    f"   chunk {idx:03d} {heading_display:44s} "
                    f"({len(content):,} chars) → {len(embedding)}d ✓"
                )

            # Rate-limit friendly pause
            time.sleep(EMBED_SLEEP_SECONDS)

        except Exception as exc:
            skipped += 1
            print(f"   ⚠️  chunk {idx:03d} FAILED: {exc}")

    return {
        "source": source,
        "title": title,
        "doc_id": doc_id,
        "total_chunks": len(chunks),
        "inserted": inserted,
        "skipped": skipped,
        "unchanged": False,
    }


# ---------------------------------------------------------------------------
# Reusable sweep — called by the CLI (main, below) and by GET /cron/reindex
# (app/main.py, Phase 9.1)
# ---------------------------------------------------------------------------

def reindex_knowledge_base(force: bool = False, verbose: bool = True) -> dict:
    """
    Ingest every *.md file in data/docs/, skipping any whose content hash hasn't
    changed since it was last ingested (unless force=True, which also wipes the
    documents/chunks tables first — the --reset CLI flag).

    Returns an aggregate summary dict: counts plus the per-file summaries, so a
    caller (the cron endpoint or the CLI) can report exactly what happened.
    """
    files = sorted(DOCS_DIR.glob("**/*.md"))
    files = [f for f in files if not f.name.startswith(".")]

    summaries: list[dict] = []
    with get_conn() as conn:
        if force:
            if verbose:
                print("\n🗑️  --reset: wiping documents + chunks tables...")
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM documents")

        for filepath in files:
            try:
                summaries.append(ingest_file(filepath, conn, verbose=verbose, force=force))
            except Exception as exc:
                if verbose:
                    print(f"\n❌ Failed to ingest {filepath}: {exc}")
                summaries.append({
                    "source": str(filepath), "inserted": 0, "skipped": 0,
                    "total_chunks": 0, "unchanged": False, "error": str(exc),
                })

    return {
        "documents_total": len(summaries),
        "documents_reindexed": sum(1 for s in summaries if not s.get("unchanged")),
        "documents_unchanged": sum(1 for s in summaries if s.get("unchanged")),
        "chunks_embedded": sum(s.get("inserted", 0) for s in summaries),
        "chunks_skipped": sum(s.get("skipped", 0) for s in summaries),
        "summaries": summaries,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest Markdown documents into the KnowOps knowledge base."
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Path to a single .md file to ingest (default: all files in data/docs/)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Wipe all existing documents and chunks before ingesting.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-chunk progress output.",
    )
    args = parser.parse_args()
    verbose = not args.quiet

    print("=" * 60)
    print("  KnowOps AI — Knowledge Base Ingestion Pipeline")
    print("  Phase 2.2 / 9.1")
    print("=" * 60)
    print(f"  Docs directory      : {DOCS_DIR}")
    print(f"  Chunk size          : {CHUNK_SIZE:,} chars  |  overlap: {CHUNK_OVERLAP}")
    print(f"  Embedding model     : gemini-embedding-001 (768d)")
    print("=" * 60)

    if args.file:
        # Explicit single-file ingest — always force (ignore the content hash):
        # the user named this exact file, so re-ingest it regardless.
        filepath = args.file.resolve()
        if not filepath.exists():
            print(f"❌ File not found: {filepath}")
            sys.exit(1)
        with get_conn() as conn:
            summary = ingest_file(filepath, conn, verbose=verbose, force=True)
        print(f"\n✅ Ingested {summary['source']}: {summary['inserted']} chunks "
              f"({summary['skipped']} failed).")
        return

    result = reindex_knowledge_base(force=args.reset, verbose=verbose)

    print("\n" + "=" * 60)
    print("  Ingestion Complete!")
    print("=" * 60)
    print(f"  Documents total      : {result['documents_total']}")
    print(f"  Documents reindexed  : {result['documents_reindexed']}")
    print(f"  Documents unchanged  : {result['documents_unchanged']} (skipped — no content change)")
    print(f"  Chunks embedded      : {result['chunks_embedded']}")
    print(f"  Chunks skipped       : {result['chunks_skipped']}")
    print()
    print("  Per-document summary:")
    for s in result["summaries"]:
        if s.get("unchanged"):
            status = "⏭️  unchanged"
        elif s.get("skipped", 0) == 0:
            status = "✅"
        else:
            status = "⚠️ "
        print(f"  {status} {s.get('source', 'unknown'):50s}  {s.get('inserted', 0):3d} chunks")
    print("=" * 60)
    print("\n✅ Knowledge base ready. You can now run the API and test /ask.")


if __name__ == "__main__":
    main()
