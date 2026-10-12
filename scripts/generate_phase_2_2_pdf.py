import os
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.pdfgen import canvas


class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 9)
        self.setFillColor(colors.HexColor("#64748b"))

        if self._pageNumber > 1:
            self.drawString(54, 750, "KnowOps AI — Phase 2.2 Knowledge Base Ingestion Pipeline")
            self.setStrokeColor(colors.HexColor("#e2e8f0"))
            self.setLineWidth(0.5)
            self.line(54, 742, 558, 742)

        self.setStrokeColor(colors.HexColor("#e2e8f0"))
        self.setLineWidth(0.5)
        self.line(54, 45, 558, 45)
        self.drawString(54, 32, "Confidential — KnowOps AI Platform Implementation")
        self.drawRightString(558, 32, f"Page {self._pageNumber} of {page_count}")
        self.restoreState()


def build_pdf(filename="Phase_2_2_Technical_Report.pdf"):
    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        leftMargin=54, rightMargin=54,
        topMargin=54, bottomMargin=54
    )

    brand_dark   = colors.HexColor("#0f172a")
    brand_blue   = colors.HexColor("#2563eb")
    brand_green  = colors.HexColor("#16a34a")
    text_color   = colors.HexColor("#334155")
    code_bg      = colors.HexColor("#f8fafc")
    border_color = colors.HexColor("#cbd5e1")
    green_light  = colors.HexColor("#f0fdf4")
    green_border = colors.HexColor("#86efac")
    amber_light  = colors.HexColor("#fffbeb")
    amber_border = colors.HexColor("#fcd34d")

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('DocTitle', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=24, leading=28,
        textColor=brand_dark, spaceAfter=6)

    subtitle_style = ParagraphStyle('DocSubtitle', parent=styles['Normal'],
        fontName='Helvetica', fontSize=11, leading=16,
        textColor=colors.HexColor("#475569"), spaceAfter=14)

    h1_style = ParagraphStyle('H1', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=15, leading=19,
        textColor=brand_dark, spaceBefore=14, spaceAfter=6, keepWithNext=True)

    h2_style = ParagraphStyle('H2', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=11, leading=15,
        textColor=brand_blue, spaceBefore=10, spaceAfter=4, keepWithNext=True)

    body_style = ParagraphStyle('Body', parent=styles['Normal'],
        fontName='Helvetica', fontSize=9.5, leading=14,
        textColor=text_color, spaceAfter=6)

    code_style = ParagraphStyle('Code', parent=styles['Normal'],
        fontName='Courier', fontSize=8, leading=11,
        textColor=colors.HexColor("#0f172a"))

    th_style = ParagraphStyle('TH', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=8.5, leading=11, textColor=colors.white)

    td_style = ParagraphStyle('TD', parent=styles['Normal'],
        fontName='Helvetica', fontSize=8.5, leading=12, textColor=text_color)

    callout_blue = ParagraphStyle('CalloutBlue', parent=styles['Normal'],
        fontName='Helvetica', fontSize=9, leading=13,
        textColor=colors.HexColor("#1e3a8a"))

    callout_green = ParagraphStyle('CalloutGreen', parent=styles['Normal'],
        fontName='Helvetica', fontSize=9, leading=13,
        textColor=colors.HexColor("#14532d"))

    bullet_style = ParagraphStyle('Bullet', parent=styles['Normal'],
        fontName='Helvetica', fontSize=9.5, leading=13.5,
        textColor=text_color, spaceAfter=4, leftIndent=12)

    story = []

    # ── Title Block ──────────────────────────────────────────────────────────
    story.append(Paragraph("KnowOps AI: Phase 2.2 Architecture Report", title_style))
    story.append(Paragraph(
        "<b>Component:</b> Knowledge Base Ingestion Pipeline "
        "(<code>scripts/ingest.py</code>) &amp; IT Operations Runbooks<br/>"
        "<b>Date:</b> October 2026&nbsp;&nbsp;|&nbsp;&nbsp;"
        "<b>Sprint:</b> sprint-1-(base) / Phase 2",
        subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=brand_blue,
                             spaceBefore=0, spaceAfter=14))

    # ── 1. Executive Summary ─────────────────────────────────────────────────
    story.append(Paragraph("1. Executive Summary & Purpose", h1_style))
    story.append(Paragraph(
        "Phase 2.2 built the <b>Knowledge Base Ingestion Pipeline</b> — the mechanism "
        "that converts raw IT operations documents into searchable, AI-ready vector "
        "embeddings stored in Neon PostgreSQL. "
        "This is the foundation that gives KnowOps AI its <i>knowledge</i>: without it, "
        "the system cannot answer any operational questions. "
        "Every future RAG search query, grounded AI answer, and agent tool call depends "
        "directly on the data loaded in this phase.", body_style))

    box = Table([[Paragraph(
        "<b>Analogy:</b> If Phase 2.1 built the <i>AI brain</i>, Phase 2.2 is the "
        "<i>textbook</i> that fills it. The ingestion pipeline reads your IT runbooks, "
        "splits them into bite-sized pieces, converts each piece into a mathematical "
        "vector that captures its meaning, and stores it in the database — permanently "
        "ready for semantic search.",
        callout_blue)]], colWidths=[504])
    box.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#eff6ff")),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#93c5fd")),
        ('TOPPADDING', (0,0), (-1,-1), 8), ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING', (0,0), (-1,-1), 12), ('RIGHTPADDING', (0,0), (-1,-1), 12),
    ]))
    story.append(box)
    story.append(Spacer(1, 10))

    # ── 2. Pipeline Architecture ──────────────────────────────────────────────
    story.append(Paragraph("2. Pipeline Architecture — How the Ingestion Works", h1_style))
    story.append(Paragraph(
        "The ingestion pipeline in <code>scripts/ingest.py</code> follows a strict, "
        "deterministic 6-step process for every document:", body_style))

    steps = [
        ("Step 1 — File Discovery",
         "The pipeline scans <code>data/docs/</code> for all <code>*.md</code> files. "
         "It can also be pointed at a single file via <code>--file</code> or wiped and "
         "re-run from scratch with <code>--reset</code>."),
        ("Step 2 — Metadata Extraction",
         "Each document's <b>title</b> is extracted from its top-level "
         "<code># Heading</code>. A relative source path acts as a stable, unique "
         "document identifier for upsert logic."),
        ("Step 3 — Heading-Based Chunking",
         "The document is split on <code>##</code> and <code>###</code> Markdown headings. "
         "This keeps each chunk semantically coherent — a chunk about 'Database Failover Steps' "
         "stays together as a single unit rather than being cut mid-sentence."),
        ("Step 4 — Overlap Sub-Chunking",
         "Sections longer than 1,200 characters are further split with a 150-character "
         "overlap window. The overlap prevents loss of context at chunk boundaries — "
         "e.g., a procedure that spans two chunks still shares its intro sentence in both."),
        ("Step 5 — Embedding via Gemini",
         "<code>embed_document(chunk_text)</code> from Phase 2.1 is called for each chunk. "
         "The Gemini <code>text-embedding-004</code> model returns a 768-dimensional float "
         "vector that mathematically encodes the semantic meaning of that chunk."),
        ("Step 6 — Database Upsert",
         "The document row is inserted (or updated if already exists) in the "
         "<code>documents</code> table. All old chunks are deleted and fresh chunks "
         "with their embeddings, headings, and ordering index are inserted into "
         "<code>chunks</code>."),
    ]

    for title_text, body_text in steps:
        story.append(Paragraph(title_text, h2_style))
        story.append(Paragraph(body_text, body_style))

    # ── 3. Chunking Strategy ─────────────────────────────────────────────────
    story.append(Paragraph("3. Chunking Strategy — Design Decisions Explained", h1_style))

    strategy_data = [
        [Paragraph("Strategy", th_style), Paragraph("Value / Setting", th_style),
         Paragraph("Why This Was Chosen", th_style)],
        [Paragraph("<b>Primary split:</b> Markdown headings", td_style),
         Paragraph("<code>## / ###</code> boundaries", td_style),
         Paragraph("Runbook sections are already semantically grouped by authors. "
                   "Respecting these boundaries keeps related instructions together.", td_style)],
        [Paragraph("<b>Secondary split:</b> Character-level with overlap", td_style),
         Paragraph("1,200 chars / 150-char overlap", td_style),
         Paragraph("Prevents embeddings from exceeding the model's token limit while "
                   "preserving cross-boundary context so no step in a procedure is orphaned.", td_style)],
        [Paragraph("<b>Minimum chunk size</b>", td_style),
         Paragraph("80 characters", td_style),
         Paragraph("Filters out stub chunks (e.g., a heading with no body) that would "
                   "produce low-quality embeddings and waste API quota.", td_style)],
        [Paragraph("<b>Embedding model</b>", td_style),
         Paragraph("<code>text-embedding-004</code>, 768d", td_style),
         Paragraph("768 dimensions fit within pgvector's HNSW index limit of 2,000. "
                   "Higher dimensions increase accuracy but inflate storage and index time.", td_style)],
        [Paragraph("<b>Rate-limit pause</b>", td_style),
         Paragraph("0.5s between API calls", td_style),
         Paragraph("Prevents hitting Gemini free-tier rate limits (60 QPM) during "
                   "large batch ingestion runs.", td_style)],
    ]
    strat_table = Table(strategy_data, colWidths=[130, 110, 264])
    strat_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), brand_dark),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-1), 0.5, border_color),
        ('TOPPADDING', (0,0), (-1,-1), 6), ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 6), ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    story.append(strat_table)
    story.append(Spacer(1, 10))

    # ── 4. Knowledge Base Documents ───────────────────────────────────────────
    story.append(Paragraph("4. Knowledge Base Documents Loaded", h1_style))
    story.append(Paragraph(
        "Four production-grade IT operations runbooks were created and ingested into the "
        "Neon database. These represent real categories of operational knowledge that "
        "KnowOps AI will answer questions about:", body_style))

    kb_data = [
        [Paragraph("Document", th_style), Paragraph("File", th_style),
         Paragraph("Chunks", th_style), Paragraph("Topics Covered", th_style)],
        [Paragraph("<b>Disaster Recovery Runbook</b>", td_style),
         Paragraph("<code>disaster_recovery_runbook.md</code>", td_style),
         Paragraph("12", td_style),
         Paragraph("RTO/RPO targets, incident classification (P1–P4), first-response steps, "
                   "PostgreSQL manual failover, DNS cutover, Kubernetes rollback, PIR process, "
                   "escalation matrix.", td_style)],
        [Paragraph("<b>On-Call Guide &amp; Incident Response</b>", td_style),
         Paragraph("<code>on_call_guide.md</code>", td_style),
         Paragraph("17", td_style),
         Paragraph("On-call responsibilities, PagerDuty/Grafana/Datadog tooling, alert triage "
                   "decision tree, 5 common alert runbooks (CPU, DB pool, SSL, latency, Gemini 503), "
                   "shift handoff checklist.", td_style)],
        [Paragraph("<b>Kubernetes Operations Guide</b>", td_style),
         Paragraph("<code>kubernetes_operations.md</code>", td_style),
         Paragraph("16", td_style),
         Paragraph("EKS cluster management, deployment / rollback / canary strategies, "
                   "HPA auto-scaling config, node drain/uncordon, CrashLoopBackOff debugging, "
                   "secrets management via AWS CSI Driver, resource quotas.", td_style)],
        [Paragraph("<b>API Troubleshooting Guide</b>", td_style),
         Paragraph("<code>api_troubleshooting.md</code>", td_style),
         Paragraph("16", td_style),
         Paragraph("HTTP error codes (400–503), JWT auth issues, /ask endpoint failure modes, "
                   "slow vector search diagnosis, memory usage, rate limiting (429), "
                   "structured log format, DB query debugging SQL.", td_style)],
        [Paragraph("<b>TOTAL</b>", td_style), Paragraph("4 documents", td_style),
         Paragraph("<b>61</b>", td_style),
         Paragraph("Complete IT operations knowledge base, 0 failures.", td_style)],
    ]
    kb_table = Table(kb_data, colWidths=[120, 130, 42, 212])
    kb_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), brand_blue),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#f1f5f9")),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-1), 0.5, border_color),
        ('TOPPADDING', (0,0), (-1,-1), 6), ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 6), ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('ROWBACKGROUNDS', (0,1), (-1,-2), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    story.append(kb_table)
    story.append(Spacer(1, 10))

    # ── 5. Database Schema Updates ────────────────────────────────────────────
    story.append(Paragraph("5. Database Schema Changes in Phase 2.2", h1_style))
    story.append(Paragraph(
        "Two new columns were added to the <code>chunks</code> table in Neon PostgreSQL "
        "to support ordering and section-aware retrieval:", body_style))

    sql_code = (
        "ALTER TABLE chunks ADD COLUMN chunk_index INTEGER NOT NULL DEFAULT 0;<br/>"
        "ALTER TABLE chunks ADD COLUMN heading TEXT NOT NULL DEFAULT '';"
    )
    sql_block = Table([[Paragraph(sql_code, code_style)]], colWidths=[504])
    sql_block.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), code_bg),
        ('BOX', (0,0), (-1,-1), 0.5, border_color),
        ('TOPPADDING', (0,0), (-1,-1), 6), ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 10), ('RIGHTPADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(sql_block)
    story.append(Spacer(1, 8))

    schema_data = [
        [Paragraph("Column", th_style), Paragraph("Type", th_style),
         Paragraph("Purpose", th_style)],
        [Paragraph("<code>chunk_index</code>", td_style),
         Paragraph("INTEGER", td_style),
         Paragraph("Position of the chunk within its document (0, 1, 2...). "
                   "Used to reconstruct reading order and display adjacent context "
                   "during retrieval.", td_style)],
        [Paragraph("<code>heading</code>", td_style),
         Paragraph("TEXT", td_style),
         Paragraph("The Markdown section heading the chunk belongs to (e.g., '4.1 Detecting "
                   "Primary Database Failure'). Shown in API responses as source citations "
                   "so users know exactly which section was used.", td_style)],
    ]
    schema_table = Table(schema_data, colWidths=[100, 80, 324])
    schema_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), brand_dark),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-1), 0.5, border_color),
        ('TOPPADDING', (0,0), (-1,-1), 6), ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 6), ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    story.append(schema_table)
    story.append(Spacer(1, 10))

    # ── 6. Verification Results ───────────────────────────────────────────────
    story.append(Paragraph("6. Live Verification Results", h1_style))
    story.append(Paragraph(
        "After ingestion, a live semantic search was run against the Neon database "
        "to confirm the vector index is functional and retrieving the correct content:", body_style))

    story.append(Paragraph("Test Query: <i>\"How do I perform a database failover?\"</i>", h2_style))

    result_data = [
        [Paragraph("Rank", th_style), Paragraph("Similarity Score", th_style),
         Paragraph("Document", th_style), Paragraph("Section / Heading", th_style)],
        [Paragraph("#1", td_style), Paragraph("<b>0.7147</b>", td_style),
         Paragraph("Disaster Recovery Runbook", td_style),
         Paragraph("4.3 Verification — post-failover confirmation steps", td_style)],
        [Paragraph("#2", td_style), Paragraph("0.6967", td_style),
         Paragraph("Disaster Recovery Runbook", td_style),
         Paragraph("4.1 Detecting Primary Database Failure — alert signs and indicators", td_style)],
        [Paragraph("#3", td_style), Paragraph("0.6804", td_style),
         Paragraph("Disaster Recovery Runbook", td_style),
         Paragraph("Manual failover steps — DNS CNAME cutover with aws route53", td_style)],
    ]
    result_table = Table(result_data, colWidths=[35, 85, 140, 244])
    result_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), brand_green),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-1), 0.5, border_color),
        ('TOPPADDING', (0,0), (-1,-1), 6), ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 6), ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [green_light, colors.white]),
    ]))
    story.append(result_table)
    story.append(Spacer(1, 8))

    story.append(Table([[Paragraph(
        "<b>✅ Interpretation:</b> All top-3 results correctly identify the Disaster Recovery Runbook "
        "as the most relevant document — and specifically the failover-related sections. "
        "The similarity scores (0.68–0.71) are strong, confirming the embedding model has "
        "correctly encoded the semantic meaning of both the query and the stored chunks. "
        "An unrelated query like 'baking a cake' would score &lt; 0.2 against these chunks.",
        callout_green)]], colWidths=[504]))
    story[-1].setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), green_light),
        ('BOX', (0,0), (-1,-1), 1, green_border),
        ('TOPPADDING', (0,0), (-1,-1), 8), ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING', (0,0), (-1,-1), 12), ('RIGHTPADDING', (0,0), (-1,-1), 12),
    ]))
    story.append(Spacer(1, 12))

    # ── 7. How 2.2 is Used in the Rest of the Platform ────────────────────────
    story.append(Paragraph("7. How Phase 2.2 Feeds the Rest of the Platform", h1_style))
    story.append(Paragraph(
        "The data loaded in Phase 2.2 is consumed by every subsequent phase:", body_style))

    usage_data = [
        [Paragraph("Phase / Feature", th_style), Paragraph("Consumes 2.2 Data Via", th_style),
         Paragraph("What It Does With It", th_style)],
        [Paragraph("<b>Phase 2.3 — RAG Retrieval</b><br/><code>app/rag.py</code>", td_style),
         Paragraph("SQL: <code>ORDER BY embedding &lt;=&gt; query_vec LIMIT 5</code>", td_style),
         Paragraph("Finds the 5 most semantically similar chunks to a user query "
                   "using HNSW cosine search. Returns chunk text + heading + source "
                   "as grounded context.", td_style)],
        [Paragraph("<b>Phase 2.4 — RAG Evaluation</b><br/><code>tests/eval_rag.py</code>", td_style),
         Paragraph("Retrieves chunks, compares vs. ground truth", td_style),
         Paragraph("Tests retrieval precision. Confirms the right document section "
                   "appears in top-k results for benchmark queries.", td_style)],
        [Paragraph("<b>Phase 2.5 — /ask API Endpoint</b><br/><code>app/main.py</code>", td_style),
         Paragraph("RAG retrieval → <code>chat_completion(context_chunks)</code>", td_style),
         Paragraph("End-to-end: user submits a question → system retrieves relevant "
                   "chunks from the KB → Gemini generates a grounded answer citing the "
                   "correct runbook section.", td_style)],
        [Paragraph("<b>Phase 3 — AI Agent</b><br/><code>app/agent.py</code>", td_style),
         Paragraph("Knowledge base as a tool in the agent's tool belt", td_style),
         Paragraph("The agent calls the RAG retrieval tool autonomously during "
                   "multi-step reasoning — e.g., fetching the on-call guide mid-conversation "
                   "to answer a complex incident question.", td_style)],
    ]
    usage_table = Table(usage_data, colWidths=[130, 140, 234])
    usage_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), brand_blue),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-1), 0.5, border_color),
        ('TOPPADDING', (0,0), (-1,-1), 6), ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 6), ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    story.append(usage_table)
    story.append(Spacer(1, 12))

    # ── 8. CLI Usage Reference ─────────────────────────────────────────────────
    story.append(Paragraph("8. Running the Ingestion Pipeline — CLI Reference", h1_style))

    cli_rows = [
        ("Ingest all docs (first time)", "python scripts/ingest.py"),
        ("Re-ingest a single updated file", "python scripts/ingest.py --file data/docs/on_call_guide.md"),
        ("Wipe + full re-ingest (after schema change)", "python scripts/ingest.py --reset"),
        ("Quiet mode (no per-chunk output)", "python scripts/ingest.py --quiet"),
    ]
    for label, cmd in cli_rows:
        story.append(Paragraph(f"<b>{label}:</b>", body_style))
        cb = Table([[Paragraph(cmd, code_style)]], colWidths=[504])
        cb.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), code_bg),
            ('BOX', (0,0), (-1,-1), 0.5, border_color),
            ('TOPPADDING', (0,0), (-1,-1), 4), ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('LEFTPADDING', (0,0), (-1,-1), 10), ('RIGHTPADDING', (0,0), (-1,-1), 10),
        ]))
        story.append(cb)
        story.append(Spacer(1, 5))

    story.append(Spacer(1, 6))

    # ── 9. Next Steps ──────────────────────────────────────────────────────────
    story.append(Paragraph("9. Next Steps: Phase 2.3 — RAG Retrieval", h1_style))
    story.append(Paragraph(
        "With 61 chunks stored and indexed in Neon, Phase 2.3 will build "
        "<code>app/rag.py</code> — the retrieval layer that takes a user's natural "
        "language question, converts it to a query embedding using <code>embed_query()</code>, "
        "runs a cosine similarity search against the HNSW index, and returns the top-k "
        "most relevant chunks with their source metadata.", body_style))

    story.append(Paragraph("Phase 2.3 will implement:", h2_style))
    for item in [
        "<code>retrieve(query: str, top_k: int = 5) → list[ChunkResult]</code> — the core RAG function",
        "Threshold filtering — only return chunks with similarity &gt; 0.5 to avoid noise",
        "Source citation metadata — document title + section heading per result",
        "Integration into <code>chat_completion()</code> as the <code>context_chunks</code> input",
    ]:
        story.append(Paragraph(f"• {item}", bullet_style))

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"PDF generated: {os.path.abspath(filename)}")


if __name__ == "__main__":
    build_pdf()
