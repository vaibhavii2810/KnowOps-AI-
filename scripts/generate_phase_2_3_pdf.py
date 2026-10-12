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
            self.drawString(54, 750, "KnowOps AI — Phase 2.3 RAG Retrieval & Semantic Search Engine")
            self.setStrokeColor(colors.HexColor("#e2e8f0"))
            self.setLineWidth(0.5)
            self.line(54, 742, 558, 742)

        self.setStrokeColor(colors.HexColor("#e2e8f0"))
        self.setLineWidth(0.5)
        self.line(54, 45, 558, 45)
        self.drawString(54, 32, "Confidential — KnowOps AI Platform Implementation")
        self.drawRightString(558, 32, f"Page {self._pageNumber} of {page_count}")
        self.restoreState()


def build_pdf(filename="Phase_2_3_Technical_Report.pdf"):
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
    purple_light = colors.HexColor("#f5f3ff")
    purple_border= colors.HexColor("#c4b5fd")

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('DocTitle', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=24, leading=28,
        textColor=brand_dark, spaceAfter=6)

    subtitle_style = ParagraphStyle('DocSubtitle', parent=styles['Normal'],
        fontName='Helvetica', fontSize=11, leading=16,
        textColor=colors.HexColor("#475569"), spaceAfter=14)

    h1_style = ParagraphStyle('H1', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=14, leading=18,
        textColor=brand_dark, spaceBefore=14, spaceAfter=6, keepWithNext=True)

    h2_style = ParagraphStyle('H2', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=11, leading=15,
        textColor=brand_blue, spaceBefore=10, spaceAfter=4, keepWithNext=True)

    body_style = ParagraphStyle('Body', parent=styles['Normal'],
        fontName='Helvetica', fontSize=9.5, leading=14,
        textColor=text_color, spaceAfter=6)

    bullet_style = ParagraphStyle('Bullet', parent=styles['Normal'],
        fontName='Helvetica', fontSize=9.5, leading=14,
        textColor=text_color, leftIndent=14, spaceAfter=3)

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

    story = []

    # ── Header ────────────────────────────────────────────────────────────────
    story.append(Paragraph("KnowOps AI: Phase 2.3 Technical Report", title_style))
    story.append(Paragraph(
        "<b>Component:</b> RAG Retrieval Engine & REST API (<code>app/rag.py</code>, <code>app/schemas.py</code>, <code>app/main.py</code>)<br/>"
        "<b>Sprint:</b> sprint-1-(base) / Phase 2 &nbsp;|&nbsp; <b>Date:</b> October 2026 &nbsp;|&nbsp; <b>Status:</b> Completed &amp; Verified",
        subtitle_style
    ))
    story.append(HRFlowable(width="100%", thickness=2, color=brand_blue, spaceBefore=0, spaceAfter=12))

    # ── 1. Executive Summary ───────────────────────────────────────────────────
    story.append(Paragraph("1. Executive Summary & Purpose", h1_style))
    story.append(Paragraph(
        "Phase 2.3 delivers the <b>Retrieval Engine (RAG)</b> and the core <b>FastAPI Endpoints</b> "
        "of the KnowOps AI platform. In the preceding phases, Phase 2.1 established the Gemini LLM client "
        "and database connections, while Phase 2.2 ingested 4 critical operations runbooks into 61 chunk embeddings "
        "indexed via HNSW in Neon pgvector. "
        "<b>Phase 2.3 closes the loop between user queries and stored operational knowledge</b>, "
        "enabling real-time semantic search, citation-backed context assembly, and end-to-end question answering.",
        body_style
    ))

    # Analogy callout
    analogy_p = Paragraph(
        "<b>The Operational Analogy:</b><br/>"
        "• <b>Phase 2.1:</b> The AI reasoning engine (the brain) and vector memory store.<br/>"
        "• <b>Phase 2.2:</b> The document ingestion system (reading, chunking, and archiving runbooks into memory).<br/>"
        "• <b>Phase 2.3 (This Phase):</b> The <b>instant memory retrieval &amp; consultation desk</b>. "
        "When an engineer asks <i>'How do I perform a database failover?'</i>, Phase 2.3 instantly scans 61 vector "
        "embeddings, extracts the top relevant runbook sections in milliseconds, formats citations, "
        "and serves grounded operational answers via a production-grade REST API.",
        callout_blue
    )
    t = Table([[analogy_p]], colWidths=[504])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#eff6ff")),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#93c5fd")),
        ('TOPPADDING', (0,0), (-1,-1), 8), ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING', (0,0), (-1,-1), 12), ('RIGHTPADDING', (0,0), (-1,-1), 12),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    # ── 2. What Was Built in Phase 2.3 ──────────────────────────────────────────
    story.append(Paragraph("2. Core Deliverables Built in Phase 2.3", h1_style))

    deliv_data = [
        [
            Paragraph("Component", th_style),
            Paragraph("File", th_style),
            Paragraph("Primary Responsibilities & Key Functions", th_style)
        ],
        [
            Paragraph("<b>Pydantic Data Contracts</b>", td_style),
            Paragraph("<code>app/schemas.py</code>", td_style),
            Paragraph(
                "• <code>AskRequest</code>: Input validation (question 3-2000 chars, top_k 1-20, conversation_id)<br/>"
                "• <code>ChunkResult</code>: Typed representation of retrieved chunk + metadata + similarity score<br/>"
                "• <code>AskResponse</code>: Output schema containing AI answer, source citations, question echo<br/>"
                "• <code>HealthResponse</code>: Live health check response schema (DB status, doc/chunk stats)",
                td_style
            )
        ],
        [
            Paragraph("<b>RAG Retrieval Engine</b>", td_style),
            Paragraph("<code>app/rag.py</code>", td_style),
            Paragraph(
                "• <code>retrieve(query, top_k, threshold)</code>: Vectorizes query via <code>embed_query()</code>, "
                "queries pgvector HNSW index using cosine distance (<code>&lt;=&gt;</code>), applies threshold filtering (&ge; 0.45)<br/>"
                "• <code>format_context_for_llm(chunks)</code>: Generates markdown-cited context blocks<br/>"
                "• <code>retrieve_and_format(query, top_k)</code>: High-level orchestration pipeline",
                td_style
            )
        ],
        [
            Paragraph("<b>FastAPI REST Application</b>", td_style),
            Paragraph("<code>app/main.py</code>", td_style),
            Paragraph(
                "• <code>GET /health</code>: Real-time service monitoring checking DB connection and document/chunk counts<br/>"
                "• <code>POST /ask</code>: End-to-end RAG pipeline endpoint with CORS middleware, structured error handling, "
                "and automated OpenAPI documentation at <code>/docs</code> and <code>/redoc</code>",
                td_style
            )
        ],
    ]
    dt = Table(deliv_data, colWidths=[110, 104, 290])
    dt.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), brand_dark),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, code_bg]),
        ('GRID', (0,0), (-1,-1), 0.5, border_color),
        ('TOPPADDING', (0,0), (-1,-1), 5), ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 6), ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(dt)
    story.append(Spacer(1, 10))

    # ── 3. Step-by-Step RAG Execution Pipeline ──────────────────────────────────
    story.append(Paragraph("3. End-to-End RAG Architecture & Execution Flow", h1_style))
    story.append(Paragraph(
        "When an engineer sends a request to <code>POST /ask</code>, the system executes a 5-stage pipeline:",
        body_style
    ))

    flow_steps = [
        "<b>Step 1 — Input Validation:</b> FastAPI and Pydantic parse <code>AskRequest</code>. Reject empty queries or malformed payloads with HTTP 422.",
        "<b>Step 2 — Query Embedding:</b> Query text is embedded via Gemini <code>text-embedding-004</code> using task type <code>RETRIEVAL_QUERY</code>, producing a normalized 768-dimensional float vector.",
        "<b>Step 3 — pgvector HNSW Cosine Search:</b> PostgreSQL evaluates cosine distance <code>c.embedding &lt;=&gt; q::vector</code> against the 61-chunk HNSW index. Scores are converted to similarity: <code>similarity = 1 - distance</code>. Chunks below 0.45 similarity threshold are discarded.",
        "<b>Step 4 — Context Assembly:</b> Chunks are formatted into grounded context blocks with full citations: <i>Source: Document Title &rsaquo; Section Heading</i>.",
        "<b>Step 5 — LLM Answer Generation:</b> Gemini 2.5 Flash receives the grounded context + operational system prompt. The model synthesizes an authoritative answer with strict adherence to provided facts.",
        "<b>Step 6 — Structured Response:</b> The API returns <code>AskResponse</code> containing the AI answer, query echo, and full <code>sources</code> list for transparency and auditability."
    ]
    for step in flow_steps:
        story.append(Paragraph(f"• {step}", bullet_style))

    story.append(Spacer(1, 8))

    # ── 4. Technical Deep Dive: The Vector Retrieval SQL ────────────────────────
    story.append(Paragraph("4. Technical Deep-Dive: Vector Similarity Query", h1_style))
    story.append(Paragraph(
        "The core retrieval query in <code>app/rag.py</code> leverages Neon PostgreSQL's pgvector extension:",
        body_style
    ))

    sql_code = (
        "SELECT c.id AS chunk_id, d.title AS document_title, d.source AS document_source,\n"
        "       COALESCE(c.heading, '') AS heading, c.content AS content,\n"
        "       ROUND((1 - (c.embedding &lt;=&gt; %s::vector))::numeric, 6) AS similarity\n"
        "FROM   chunks c\n"
        "JOIN   documents d ON d.id = c.document_id\n"
        "WHERE  (1 - (c.embedding &lt;=&gt; %s::vector)) &gt;= %s\n"
        "ORDER  BY c.embedding &lt;=&gt; %s::vector\n"
        "LIMIT  %s;"
    )
    cb = Table([[Paragraph(sql_code.replace("\n", "<br/>").replace(" ", "&nbsp;"), code_style)]], colWidths=[504])
    cb.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), code_bg),
        ('BOX', (0,0), (-1,-1), 0.5, border_color),
        ('TOPPADDING', (0,0), (-1,-1), 6), ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 10), ('RIGHTPADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(cb)
    story.append(Spacer(1, 10))

    # ── 5. Verification & Test Results ──────────────────────────────────────────
    story.append(Paragraph("5. Live Verification & Semantic Test Results", h1_style))
    story.append(Paragraph(
        "All components were tested against the live Neon database containing 61 knowledge base chunks. "
        "The test suite evaluated semantic retrieval across 4 distinct operational domains:",
        body_style
    ))

    test_data = [
        [
            Paragraph("Test Query", th_style),
            Paragraph("Similarity", th_style),
            Paragraph("Retrieved Source Document", th_style),
            Paragraph("Matched Section Heading", th_style)
        ],
        [
            Paragraph("<i>'How do I perform a database failover?'</i>", td_style),
            Paragraph("<b>0.7147</b><br/>0.6967", td_style),
            Paragraph("Disaster Recovery Runbook", td_style),
            Paragraph("4.3 Verification<br/>4.1 Detecting Primary DB Failure", td_style)
        ],
        [
            Paragraph("<i>'What is the procedure for rolling back a Kubernetes deployment?'</i>", td_style),
            Paragraph("<b>0.7478</b><br/>0.7440", td_style),
            Paragraph("Kubernetes Cluster Operations Guide<br/>Disaster Recovery Runbook", td_style),
            Paragraph("Rollback to specific revision<br/>Or rollback to a specific revision", td_style)
        ],
        [
            Paragraph("<i>'What do I do if API returns 502 Bad Gateway?'</i>", td_style),
            Paragraph("<b>0.7040</b><br/>0.7014", td_style),
            Paragraph("API Troubleshooting Guide", td_style),
            Paragraph("2. Common HTTP Error Codes<br/>4.1 POST /ask — 500 Error", td_style)
        ],
        [
            Paragraph("<i>'Who is on-call escalation primary for P1 incidents?'</i>", td_style),
            Paragraph("<b>0.7799</b><br/>0.7753", td_style),
            Paragraph("Disaster Recovery Runbook<br/>On-Call Guide &amp; Incident Playbook", td_style),
            Paragraph("8. Contact Escalation Matrix<br/>How to Escalate", td_style)
        ],
    ]
    tt = Table(test_data, colWidths=[150, 60, 150, 144])
    tt.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), brand_blue),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, code_bg]),
        ('GRID', (0,0), (-1,-1), 0.5, border_color),
        ('TOPPADDING', (0,0), (-1,-1), 4), ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 5), ('RIGHTPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(tt)
    story.append(Spacer(1, 10))

    # Health check status box
    health_p = Paragraph(
        "<b>Automated Health &amp; Endpoint Test Results:</b><br/>"
        "• <code>GET /health</code> &rarr; <b>Status 200 OK</b>: "
        "<code>{'status': 'ok', 'database': 'connected', 'knowledge_base': {'documents': 4, 'chunks': 61}}</code><br/>"
        "• <code>POST /ask</code> &rarr; <b>Status 200 OK</b>: "
        "Successfully returned full AI answer grounded in Disaster Recovery Runbook with complete citations.",
        callout_green
    )
    ht = Table([[health_p]], colWidths=[504])
    ht.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), green_light),
        ('BOX', (0,0), (-1,-1), 1, green_border),
        ('TOPPADDING', (0,0), (-1,-1), 6), ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 10), ('RIGHTPADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(ht)
    story.append(Spacer(1, 10))

    # ── 6. Where and How Phase 2.3 is Used ──────────────────────────────────────
    story.append(Paragraph("6. Where and How Phase 2.3 is Used in Practice", h1_style))

    usage_data = [
        [
            Paragraph("Role / System", th_style),
            Paragraph("Use Case", th_style),
            Paragraph("Impact &amp; Operational Value", th_style)
        ],
        [
            Paragraph("<b>On-Call DevOps &amp; SREs</b>", td_style),
            Paragraph("Emergency troubleshooting &amp; runbook lookup during active incidents", td_style),
            Paragraph("Reduces MTTR (Mean Time to Resolution) from 15-30 minutes of manual searching down to 2 seconds of AI-cited diagnosis.", td_style)
        ],
        [
            Paragraph("<b>API Consumers &amp; Frontend</b>", td_style),
            Paragraph("KnowOps Web Portal UI (Phase 2.5), CLI tools, and chat interfaces", td_style),
            Paragraph("Provides a clean REST interface (<code>/ask</code>) with OpenAPI/Swagger docs and strict Pydantic schemas.", td_style)
        ],
        [
            Paragraph("<b>Automated Evaluation (Phase 2.4)</b>", td_style),
            Paragraph("Benchmarking retrieval quality, top-k precision, and semantic relevance", td_style),
            Paragraph("Phase 2.4 directly imports <code>retrieve()</code> from <code>app/rag.py</code> to run automated ground-truth evaluation tests.", td_style)
        ],
        [
            Paragraph("<b>Autonomous Agents (Phase 3)</b>", td_style),
            Paragraph("Context injection for AI agent tool execution and ticket triage", td_style),
            Paragraph("Enables autonomous agents to retrieve organizational policies and step-by-step resolution scripts before taking action.", td_style)
        ],
    ]
    ut = Table(usage_data, colWidths=[110, 150, 244])
    ut.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), brand_dark),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, code_bg]),
        ('GRID', (0,0), (-1,-1), 0.5, border_color),
        ('TOPPADDING', (0,0), (-1,-1), 5), ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 6), ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(ut)
    story.append(Spacer(1, 10))

    # ── 7. Next Steps: Roadmap to Phase 2.4 ──────────────────────────────────────
    story.append(Paragraph("7. Next Steps: Roadmap to Phase 2.4", h1_style))
    story.append(Paragraph(
        "With RAG retrieval and the <code>/ask</code> API fully operational, the logical next step is "
        "<b>Phase 2.4 — RAG Evaluation &amp; Benchmarking</b>.",
        body_style
    ))
    for item in [
        "<b>Test Suite Implementation (<code>tests/eval_rag.py</code>):</b> Construct ground-truth test query-document pairs.",
        "<b>Retrieval Metrics:</b> Measure Hit Rate@k, Mean Reciprocal Rank (MRR), and Precision@k across the knowledge base.",
        "<b>Response Latency Benchmarking:</b> Measure end-to-end latency: embedding generation (~200ms) + pgvector search (~15ms) + LLM completion (~1.2s).",
        "<b>Quality Threshold Validation:</b> Validate that all operational queries score &gt; 0.70 cosine similarity to relevant runbook chunks.",
    ]:
        story.append(Paragraph(f"• {item}", bullet_style))

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"PDF generated: {os.path.abspath(filename)}")


if __name__ == "__main__":
    build_pdf()
