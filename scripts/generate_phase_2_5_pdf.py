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
            self.drawString(54, 750, "KnowOps AI — Phase 2.5 User API, Authentication & Frontend Console")
            self.setStrokeColor(colors.HexColor("#e2e8f0"))
            self.setLineWidth(0.5)
            self.line(54, 742, 558, 742)

        self.setStrokeColor(colors.HexColor("#e2e8f0"))
        self.setLineWidth(0.5)
        self.line(54, 45, 558, 45)
        self.drawString(54, 32, "Confidential — KnowOps AI Platform Implementation")
        self.drawRightString(558, 32, f"Page {self._pageNumber} of {page_count}")
        self.restoreState()


def build_pdf(filename="Phase_2_5_Technical_Report.pdf"):
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
    blue_light   = colors.HexColor("#eff6ff")
    blue_border  = colors.HexColor("#93c5fd")
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
    story.append(Paragraph("KnowOps AI: Phase 2.5 Technical Report", title_style))
    story.append(Paragraph(
        "<b>Component:</b> User API, JWT Authentication &amp; Web Operations Console<br/>"
        "<b>Sprint:</b> sprint-1-(base) / Phase 2 &nbsp;|&nbsp; <b>Date:</b> October 2026 &nbsp;|&nbsp; <b>Status:</b> Completed &amp; Verified",
        subtitle_style
    ))
    story.append(HRFlowable(width="100%", thickness=2, color=brand_blue, spaceBefore=0, spaceAfter=12))

    # ── 1. Executive Summary ───────────────────────────────────────────────────
    story.append(Paragraph("1. Executive Summary & Purpose", h1_style))
    story.append(Paragraph(
        "Phase 2.5 marks the <b>culmination of Phase 2</b>. It transforms the underlying AI and vector retrieval "
        "engines into a complete, user-facing operations platform. "
        "Phase 2.5 introduces a secure <b>JWT Authentication Layer</b>, a <b>Multi-Turn Conversation Memory System</b> "
        "backed by PostgreSQL, and an interactive <b>Web Operations Console (SPA)</b> with real-time health monitors, "
        "runbook quick links, and citation viewers.",
        body_style
    ))

    # Analogy callout
    analogy_p = Paragraph(
        "<b>The Operational Analogy:</b><br/>"
        "• <b>Phase 2.1:</b> Built the AI reasoning engine (Gemini LLM &amp; vector store).<br/>"
        "• <b>Phase 2.2:</b> Ingested 61 operational runbook chunks.<br/>"
        "• <b>Phase 2.3:</b> Built the pgvector HNSW retrieval engine.<br/>"
        "• <b>Phase 2.4:</b> Verified search precision (91.7% Hit@1, 100% Hit@3, 0.958 MRR).<br/>"
        "• <b>Phase 2.5 (This Phase):</b> The <b>Modern Command Center &amp; Access Gate</b>. "
        "Provides on-call SREs with secure login credentials, full conversation history so the AI remembers context "
        "across follow-up questions, and an operations dashboard for fast incident triage.",
        callout_blue
    )
    t = Table([[analogy_p]], colWidths=[504])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), blue_light),
        ('BOX', (0,0), (-1,-1), 1, blue_border),
        ('TOPPADDING', (0,0), (-1,-1), 8), ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING', (0,0), (-1,-1), 12), ('RIGHTPADDING', (0,0), (-1,-1), 12),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    # ── 2. What Was Built in Phase 2.5 ──────────────────────────────────────────
    story.append(Paragraph("2. Core Deliverables Built in Phase 2.5", h1_style))

    deliv_data = [
        [
            Paragraph("Component", th_style),
            Paragraph("Files / Artifacts", th_style),
            Paragraph("Key Responsibilities &amp; Architecture", th_style)
        ],
        [
            Paragraph("<b>Security &amp; JWT Auth Layer</b>", td_style),
            Paragraph("<code>app/auth.py</code>", td_style),
            Paragraph(
                "• PBKDF2-SHA256 password hashing (100,000 iterations + 16-byte salt)<br/>"
                "• Constant-time credential verification via <code>secrets.compare_digest</code><br/>"
                "• Signed JWT token issuance and decoding using PyJWT and HMAC-SHA256<br/>"
                "• FastAPI security dependencies: <code>get_current_user_optional</code> and <code>get_current_user_required</code>",
                td_style
            )
        ],
        [
            Paragraph("<b>Conversation &amp; Memory API</b>", td_style),
            Paragraph("<code>app/main.py</code><br/><code>app/schemas.py</code>", td_style),
            Paragraph(
                "• <code>POST /conversations</code>: Session thread creation in Neon PostgreSQL<br/>"
                "• <code>GET /conversations</code> &amp; <code>GET /conversations/{id}</code>: History retrieval<br/>"
                "• <code>POST /ask</code>: Automatically loads prior conversation turns into the Gemini LLM context, "
                "enabling multi-turn question answering and follow-ups",
                td_style
            )
        ],
        [
            Paragraph("<b>Web Operations Console (SPA)</b>", td_style),
            Paragraph("<code>static/index.html</code><br/><code>static/css/app.css</code><br/><code>static/js/app.js</code>", td_style),
            Paragraph(
                "• Single-Page Application served at <code>GET /</code><br/>"
                "• Glassmorphism dark mode with live PostgreSQL, chunk count, and Gemini status pills<br/>"
                "• Quick runbook cards (Disaster Recovery, K8s Ops, API Troubleshooting, On-Call)<br/>"
                "• Dynamic prompt chips, copyable code blocks, expandable citation drawers<br/>"
                "• Operator login modal and real-time system diagnostics drawer",
                td_style
            )
        ],
        [
            Paragraph("<b>Automated Test Suites</b>", td_style),
            Paragraph("<code>tests/test_auth.py</code><br/><code>tests/test_api_v2_5.py</code>", td_style),
            Paragraph(
                "• 10 passing automated tests covering password hashing, credential checks, JWT tokens, "
                "expired token rejection, protected routes, and conversation lifecycle",
                td_style
            )
        ],
    ]
    dt = Table(deliv_data, colWidths=[120, 120, 264])
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

    # ── 3. Multi-Turn Conversation Memory Architecture ─────────────────────────
    story.append(Paragraph("3. Multi-Turn Conversation Memory Workflow", h1_style))
    story.append(Paragraph(
        "A critical limitation of basic RAG systems is lack of memory between questions. "
        "In Phase 2.5, KnowOps AI maintains state across turns using PostgreSQL:",
        body_style
    ))

    mem_steps = [
        "<b>Turn 1 (New Incident):</b> Operator asks: <i>'What are the steps to detect primary database failure?'</i>. "
        "The system creates session <code>#id</code> in the <code>conversations</code> table, performs RAG retrieval, "
        "returns the answer with citations, and writes both query and answer into the <code>messages</code> table.",
        "<b>Turn 2 (Follow-up Question):</b> Operator asks: <i>'What command do I run to check if PostgreSQL is accepting connections?'</i>, "
        "passing <code>conversation_id=#id</code>.",
        "<b>History Injection:</b> The backend queries the <code>messages</code> table for the past conversation turns, "
        "constructs a multi-turn history list, and passes it to Gemini <code>chat_completion(..., history=history)</code>.",
        "<b>Contextual Continuity:</b> The LLM accurately resolves pronouns, references previous steps, and continues the conversation naturally.",
    ]
    for step in mem_steps:
        story.append(Paragraph(f"• {step}", bullet_style))

    story.append(Spacer(1, 10))

    # ── 4. Security & JWT Authentication Specifications ────────────────────────
    story.append(Paragraph("4. Security & Authentication Architecture", h1_style))
    story.append(Paragraph(
        "The authentication framework in <code>app/auth.py</code> provides enterprise security best practices:",
        body_style
    ))

    auth_table_data = [
        [Paragraph("Security Aspect", th_style), Paragraph("Implementation Specification", th_style)],
        [Paragraph("<b>Password Hashing</b>", td_style), Paragraph("PBKDF2-HMAC-SHA256 with 100,000 iterations and per-password cryptographic 16-byte salt.", td_style)],
        [Paragraph("<b>Constant-Time Comparison</b>", td_style), Paragraph("<code>secrets.compare_digest</code> prevents timing attacks during authentication.", td_style)],
        [Paragraph("<b>Token Format &amp; Algorithm</b>", td_style), Paragraph("Signed JSON Web Tokens (PyJWT) using HMAC-SHA256 (HS256) with 43-byte key.", td_style)],
        [Paragraph("<b>Standard Claims</b>", td_style), Paragraph("<code>sub</code> (username), <code>role</code> (operator/admin), <code>exp</code> (expiration), <code>iat</code> (issued at), <code>iss</code> (knowops-ai).", td_style)],
        [Paragraph("<b>Token Expiration</b>", td_style), Paragraph("Configurable via <code>JWT_EXPIRE_MINUTES</code> (default 60 minutes). Expired tokens return HTTP 401.", td_style)],
        [Paragraph("<b>FastAPI Protection</b>", td_style), Paragraph("<code>HTTPBearer</code> dependency extraction supports Swagger UI and Bearer header authentication.", td_style)],
    ]
    at = Table(auth_table_data, colWidths=[160, 344])
    at.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), brand_blue),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, code_bg]),
        ('GRID', (0,0), (-1,-1), 0.5, border_color),
        ('TOPPADDING', (0,0), (-1,-1), 4), ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 6), ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(at)
    story.append(Spacer(1, 10))

    # ── 5. Test Suite Verification ─────────────────────────────────────────────
    story.append(Paragraph("5. Verification & Automated Test Results", h1_style))
    story.append(Paragraph(
        "Phase 2.5 was verified with 10 dedicated automated test cases across two test modules:",
        body_style
    ))

    # Callout box with passing tests
    test_p = Paragraph(
        "<b>Phase 2.5 Test Results — 100% Pass Rate:</b><br/>"
        "• <code>tests/test_auth.py::test_password_hashing</code> &rarr; <b>PASSED</b><br/>"
        "• <code>tests/test_auth.py::test_operator_credentials_verification</code> &rarr; <b>PASSED</b><br/>"
        "• <code>tests/test_auth.py::test_jwt_token_creation_and_decoding</code> &rarr; <b>PASSED</b><br/>"
        "• <code>tests/test_auth.py::test_expired_jwt_token_raises_401</code> &rarr; <b>PASSED</b><br/>"
        "• <code>tests/test_auth.py::test_login_endpoint_success</code> &rarr; <b>PASSED</b><br/>"
        "• <code>tests/test_auth.py::test_login_endpoint_invalid_credentials</code> &rarr; <b>PASSED</b><br/>"
        "• <code>tests/test_auth.py::test_auth_me_endpoint_protected</code> &rarr; <b>PASSED</b><br/>"
        "• <code>tests/test_api_v2_5.py::test_serve_frontend_dashboard</code> &rarr; <b>PASSED</b><br/>"
        "• <code>tests/test_api_v2_5.py::test_conversation_lifecycle</code> &rarr; <b>PASSED</b><br/>"
        "• <code>tests/test_api_v2_5.py::test_conversation_not_found</code> &rarr; <b>PASSED</b>",
        callout_green
    )
    tbox = Table([[test_p]], colWidths=[504])
    tbox.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), green_light),
        ('BOX', (0,0), (-1,-1), 1, green_border),
        ('TOPPADDING', (0,0), (-1,-1), 6), ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 10), ('RIGHTPADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(tbox)
    story.append(Spacer(1, 10))

    # ── 6. Phase 2 Complete Recap ──────────────────────────────────────────────
    story.append(Paragraph("6. Phase 2 Complete Architectural Milestone Recap", h1_style))
    story.append(Paragraph(
        "With Phase 2.5 completed, the entire Phase 2 milestone is 100% operational:",
        body_style
    ))

    phase_recap = [
        [Paragraph("Sub-Phase", th_style), Paragraph("Deliverable", th_style), Paragraph("Status", th_style)],
        [Paragraph("<b>Phase 2.1</b>", td_style), Paragraph("Gemini AI Core Integration (<code>app/llm.py</code>) &amp; Neon pgvector Setup", td_style), Paragraph("<font color='#16a34a'><b>COMPLETE</b></font>", td_style)],
        [Paragraph("<b>Phase 2.2</b>", td_style), Paragraph("Knowledge Base Ingestion (61 chunks loaded into HNSW index)", td_style), Paragraph("<font color='#16a34a'><b>COMPLETE</b></font>", td_style)],
        [Paragraph("<b>Phase 2.3</b>", td_style), Paragraph("RAG Semantic Retrieval Engine (<code>app/rag.py</code>, <code>app/main.py</code>)", td_style), Paragraph("<font color='#16a34a'><b>COMPLETE</b></font>", td_style)],
        [Paragraph("<b>Phase 2.4</b>", td_style), Paragraph("RAG Evaluation &amp; Benchmarking (100% Hit@3, 0.958 MRR)", td_style), Paragraph("<font color='#16a34a'><b>COMPLETE</b></font>", td_style)],
        [Paragraph("<b>Phase 2.5</b>", td_style), Paragraph("User API, JWT Authentication &amp; Web Operations Console SPA", td_style), Paragraph("<font color='#16a34a'><b>COMPLETE</b></font>", td_style)],
    ]
    pr = Table(phase_recap, colWidths=[90, 310, 104])
    pr.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), brand_dark),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, code_bg]),
        ('GRID', (0,0), (-1,-1), 0.5, border_color),
        ('TOPPADDING', (0,0), (-1,-1), 4), ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 6), ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(pr)
    story.append(Spacer(1, 10))

    # ── 7. Next Steps: Roadmap to Phase 3 ──────────────────────────────────────
    story.append(Paragraph("7. Next Steps: Roadmap to Phase 3", h1_style))
    story.append(Paragraph(
        "With the core RAG platform, REST API, authentication, and frontend operational, "
        "the project is ready for <b>Phase 3 — Autonomous Support Agents &amp; Workflow Automation</b>:",
        body_style
    ))
    for item in [
        "<b>Phase 3.1 — Support Ticket CRM:</b> Mocked support ticket database and CRM endpoints (<code>/tickets</code>).",
        "<b>Phase 3.2 — Autonomous Agent Orchestrator:</b> Function-calling agent with tool execution for diagnostic lookups and ticket triage.",
        "<b>Phase 3.3 — Automated Runbook Actions:</b> Safe automated execution of verified runbook commands (e.g. pod restarts, scale checks).",
        "<b>Phase 3.4 — Cron &amp; Workflow Automation:</b> Periodic re-indexing and incident webhook integrations.",
    ]:
        story.append(Paragraph(f"• {item}", bullet_style))

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"PDF generated: {os.path.abspath(filename)}")


if __name__ == "__main__":
    build_pdf()
