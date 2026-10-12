"""
scripts/ingest.py  –  Phase 2.2
Knowledge-base ingestion pipeline.

Usage:
    python scripts/ingest.py                    # ingest all docs in data/docs/
    python scripts/ingest.py --file path/to.md  # ingest a single file
    python scripts/ingest.py --reset            # wipe existing data then ingest all

How it works:
    1. Walk data/docs/ for *.md files (or use --file)
    2. Extract YAML front-matter for title / document-id metadata
    3. Split the document into semantic chunks on Markdown heading boundaries
       (## and ### headings act as natural section delimiters)
    4. Optionally further split large chunks at a max-token boundary (overlap window)
    5. Call embed_document() for every chunk  →  768-d vector via Gemini
    6. Upsert the document record and INSERT all chunks into Neon PostgreSQL
    7. Print a clean progress summary

Schema (managed by scripts/init_db.sql):
    documents(id, source, title, created_at)
    chunks(id, document_id, chunk_index, heading, content, embedding, created_at)
"""

from __future__ import annotations

import argparse
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

# Target chunk size in characters (≈ 300 tokens @ 4 chars/token)
CHUNK_SIZE = 1_200

# Number of characters to overlap between consecutive text-split chunks
CHUNK_OVERLAP = 150

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
    sections: list[tuple[str, str]] = []

    matches = list(heading_pattern.finditer(text))
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


def make_chunks(text: str) -> list[tuple[str, str]]:
    """
    Full chunking pipeline for one document:
      1. Split on heading boundaries   →  coarse semantic sections
      2. Further split large sections  →  fine-grained overlap chunks

    Returns:
        List of (heading, chunk_text) tuples ready for embedding.
    """
    chunks: list[tuple[str, str]] = []
    sections = split_by_headings(text)

    for heading, body in sections:
        if len(body) <= CHUNK_SIZE:
            if len(body) >= MIN_CHUNK_CHARS:
                chunks.append((heading, body))
        else:
            for sub in split_text_with_overlap(body):
                sub = sub.strip()
                if len(sub) >= MIN_CHUNK_CHARS:
                    chunks.append((heading, sub))

    return chunks


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def upsert_document(conn, source: str, title: str) -> int:
    """
    Insert a document record if it doesn't exist, or update title if it does.

    Returns the document's database id.
    """
    existing = conn.execute(
        "SELECT id FROM documents WHERE source = %s", (source,)
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE documents SET title = %s WHERE id = %s",
            (title, existing[0]),
        )
        return existing[0]

    row = conn.execute(
        "INSERT INTO documents (source, title) VALUES (%s, %s) RETURNING id",
        (source, title),
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

def ingest_file(filepath: Path, conn, verbose: bool = True) -> dict:
    """
    Ingest a single Markdown file into the database.

    Returns a summary dict with counts.
    """
    raw_text = filepath.read_text(encoding="utf-8")

    # Derive metadata
    _, body = extract_frontmatter(raw_text)
    title = extract_title_from_markdown(body) or filepath.stem.replace("_", " ").title()
    source = str(filepath.relative_to(PROJECT_ROOT))

    if verbose:
        print(f"\n📄 Ingesting: {source}")
        print(f"   Title   : {title}")

    # Upsert the document row
    doc_id = upsert_document(conn, source, title)
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

    # Collect files to ingest
    if args.file:
        files = [args.file.resolve()]
    else:
        files = sorted(DOCS_DIR.glob("**/*.md"))
        files = [f for f in files if not f.name.startswith(".")]

    if not files:
        print("❌ No Markdown files found. Add .md files to data/docs/ and retry.")
        sys.exit(1)

    print("=" * 60)
    print("  KnowOps AI — Knowledge Base Ingestion Pipeline")
    print("  Phase 2.2")
    print("=" * 60)
    print(f"  Documents to ingest : {len(files)}")
    print(f"  Docs directory      : {DOCS_DIR}")
    print(f"  Chunk size          : {CHUNK_SIZE:,} chars  |  overlap: {CHUNK_OVERLAP}")
    print(f"  Embedding model     : gemini-embedding-001 (768d)")
    print("=" * 60)

    summaries: list[dict] = []

    with get_conn() as conn:
        if args.reset:
            print("\n🗑️  --reset flag detected. Wiping documents + chunks tables...")
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM documents")
            print("   Done.\n")

        for filepath in files:
            try:
                summary = ingest_file(filepath, conn, verbose=not args.quiet)
                summaries.append(summary)
            except Exception as exc:
                print(f"\n❌ Failed to ingest {filepath}: {exc}")
                summaries.append({"source": str(filepath), "inserted": 0, "skipped": 0, "total_chunks": 0})

    # Final summary
    total_inserted = sum(s.get("inserted", 0) for s in summaries)
    total_skipped = sum(s.get("skipped", 0) for s in summaries)
    total_docs = len(summaries)

    print("\n" + "=" * 60)
    print("  Ingestion Complete!")
    print("=" * 60)
    print(f"  Documents processed : {total_docs}")
    print(f"  Chunks embedded     : {total_inserted}")
    print(f"  Chunks skipped      : {total_skipped}")
    print()
    print("  Per-document summary:")
    for s in summaries:
        status = "✅" if s.get("skipped", 0) == 0 else "⚠️ "
        print(
            f"  {status} {s.get('source', 'unknown'):50s}  "
            f"{s.get('inserted', 0):3d} chunks"
        )
    print("=" * 60)
    print("\n✅ Knowledge base ready. You can now run the API and test /ask.")


if __name__ == "__main__":
    main()
