import os
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, HRFlowable
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
        
        # Header (pages > 1)
        if self._pageNumber > 1:
            self.drawString(54, 750, "KnowOps AI — Phase 2.1 Technical Documentation & Architecture")
            self.setStrokeColor(colors.HexColor("#e2e8f0"))
            self.setLineWidth(0.5)
            self.line(54, 742, 558, 742)
            
        # Footer
        self.setStrokeColor(colors.HexColor("#e2e8f0"))
        self.setLineWidth(0.5)
        self.line(54, 45, 558, 45)
        self.drawString(54, 32, "Confidential — KnowOps AI Platform Implementation")
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(558, 32, page_text)
        self.restoreState()

def build_pdf(filename="Phase_2_1_Technical_Report.pdf"):
    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )

    styles = getSampleStyleSheet()
    
    primary_color = colors.HexColor("#1e293b")
    brand_blue = colors.HexColor("#2563eb")
    brand_dark = colors.HexColor("#0f172a")
    code_bg = colors.HexColor("#f8fafc")
    border_color = colors.HexColor("#cbd5e1")
    text_color = colors.HexColor("#334155")

    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=28,
        textColor=brand_dark,
        spaceAfter=6
    )

    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#475569"),
        spaceAfter=15
    )

    h1_style = ParagraphStyle(
        'H1',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=19,
        textColor=brand_dark,
        spaceBefore=14,
        spaceAfter=6,
        keepWithNext=True
    )

    h2_style = ParagraphStyle(
        'H2',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=15,
        textColor=brand_blue,
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True
    )

    body_style = ParagraphStyle(
        'Body',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=13.5,
        textColor=text_color,
        spaceAfter=6
    )

    code_style = ParagraphStyle(
        'CodeSnippet',
        parent=styles['Normal'],
        fontName='Courier',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#0f172a")
    )

    table_header_style = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=11,
        textColor=colors.white
    )

    table_cell_style = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11.5,
        textColor=text_color
    )

    callout_style = ParagraphStyle(
        'CalloutText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#1e3a8a")
    )

    story = []

    # Title Block
    story.append(Paragraph("KnowOps AI: Phase 2.1 Architecture Report", title_style))
    story.append(Paragraph("<b>Component:</b> Gemini AI Core Integration (<code>app/llm.py</code>) & Vector Database Setup<br/><b>Date:</b> October 2026 | <b>Sprint:</b> sprint-1-(base) & Phase 2", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=brand_blue, spaceBefore=0, spaceAfter=14))

    # Executive Summary
    story.append(Paragraph("1. Executive Summary & Purpose", h1_style))
    story.append(Paragraph(
        "In <b>Phase 2.1</b>, we built and established the central <b>AI Engine</b> of the KnowOps AI platform in "
        "<code>app/llm.py</code>. This module serves as the fundamental layer connecting the application to "
        "Google's Gemini Generative AI infrastructure and Neon PostgreSQL pgvector storage. "
        "Every subsequent feature—including knowledge base indexing, semantic search, grounded Q&A, and autonomous agent loops—directly builds upon the functions created in this step.",
        body_style
    ))

    # Callout Box
    callout_data = [[
        Paragraph(
            "<b>Key Architectural Role:</b> Think of <code>app/llm.py</code> as the central <i>brain connector</i>. "
            "No other module creates direct, unmanaged HTTP requests or SDK bindings to Gemini. "
            "Instead, all embedding generation and generative chat calls pass through unified, tested, and resilient functions defined here.",
            callout_style
        )
    ]]
    callout_table = Table(callout_data, colWidths=[504])
    callout_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#eff6ff")),
        ('BORDER', (0,0), (-1,-1), 1, colors.HexColor("#93c5fd")),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING', (0,0), (-1,-1), 12),
        ('RIGHTPADDING', (0,0), (-1,-1), 12),
    ]))
    story.append(callout_table)
    story.append(Spacer(1, 10))

    # Core Capabilities Built
    story.append(Paragraph("2. Core Functions Implemented in <code>app/llm.py</code>", h1_style))

    # Function 1
    story.append(Paragraph("A. Client Initialization & Management — <code>get_client()</code>", h2_style))
    story.append(Paragraph(
        "Initializes and returns an authenticated instance of the official Google GenAI SDK client (<code>google.genai.Client</code>). "
        "Configured via <code>app/config.py</code> using the secure environment variable <code>GEMINI_API_KEY</code>.",
        body_style
    ))
    code_client = [[Paragraph("def get_client() -&gt; genai.Client:<br/>&nbsp;&nbsp;&nbsp;&nbsp;return genai.Client(api_key=settings.gemini_api_key)", code_style)]]
    t_client = Table(code_client, colWidths=[504])
    t_client.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), code_bg),
        ('BOX', (0,0), (-1,-1), 0.5, border_color),
        ('TOPPADDING', (0,0), (-1,-1), 5), ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 8), ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(t_client)
    story.append(Spacer(1, 8))

    # Function 2
    story.append(Paragraph("B. Asymmetric Document Embedding — <code>embed_document(text)</code>", h2_style))
    story.append(Paragraph(
        "Converts knowledge base documents and text chunks into dense semantic vector representations. "
        "It uses model <code>text-embedding-004</code> with task type <b><code>RETRIEVAL_DOCUMENT</code></b>. "
        "Crucially, it restricts output dimensionality to <b>768 dimensions</b> (via <code>output_dimensionality=768</code>), ensuring 100% compatibility with pgvector's HNSW index limits (which capped at 2,000 dimensions).",
        body_style
    ))

    # Function 3
    story.append(Paragraph("C. Query Embedding — <code>embed_query(query)</code>", h2_style))
    story.append(Paragraph(
        "Converts user questions into 768-dimensional vectors using task type <b><code>RETRIEVAL_QUERY</code></b>. "
        "Because user queries are typically short questions while stored chunks are long answers, Google's asymmetric embedding optimization maximizes cosine similarity accuracy between corresponding question-and-answer pairs.",
        body_style
    ))

    # Function 4
    story.append(Paragraph("D. Robust Chat Completion — <code>chat_completion(...)</code>", h2_style))
    story.append(Paragraph(
        "Interfaces with the Gemini chat models (<code>gemini-flash-latest</code>) to synthesize answers. "
        "Includes temperature control, system instructions (for role prompting and anti-hallucination constraints), and built-in exponential backoff retry mechanisms to handle transient 503 high-load spikes smoothly.",
        body_style
    ))

    story.append(Spacer(1, 8))

    # Database updates
    story.append(Paragraph("3. Vector Database Integration (PostgreSQL + pgvector)", h1_style))
    story.append(Paragraph(
        "Alongside the LLM layer, the Neon PostgreSQL database was aligned to store and index high-dimensional embeddings:",
        body_style
    ))
    
    db_table_data = [
        [Paragraph("Database Component", table_header_style), Paragraph("Specification / Configuration", table_header_style), Paragraph("Purpose", table_header_style)],
        [
            Paragraph("<b>Vector Column</b>", table_cell_style),
            Paragraph("<code>chunks.embedding vector(768)</code>", table_cell_style),
            Paragraph("Stores 768-dimensional embeddings generated by <code>embed_document</code>.", table_cell_style)
        ],
        [
            Paragraph("<b>Vector Index</b>", table_cell_style),
            Paragraph("<code>HNSW index (vector_cosine_ops)</code>", table_cell_style),
            Paragraph("Provides sub-millisecond approximate nearest neighbor (ANN) cosine similarity search.", table_cell_style)
        ],
        [
            Paragraph("<b>Metadata Storage</b>", table_cell_style),
            Paragraph("<code>document_id, chunk_index, text, doc_metadata</code>", table_cell_style),
            Paragraph("Retains provenance, document headers, page numbers, and full text for citation.", table_cell_style)
        ]
    ]
    db_table = Table(db_table_data, colWidths=[120, 160, 224])
    db_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), brand_dark),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-1), 0.5, border_color),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    story.append(db_table)
    story.append(Spacer(1, 12))

    # End-to-End Application Mapping
    story.append(Paragraph("4. Where and How Phase 2.1 is Used Across the Platform", h1_style))
    story.append(Paragraph(
        "Here is the exact lifecycle mapping showing how each function in <code>app/llm.py</code> powers the rest of KnowOps AI:",
        body_style
    ))

    flow_table_data = [
        [Paragraph("Phase / Feature", table_header_style), Paragraph("Target File", table_header_style), Paragraph("Function Used", table_header_style), Paragraph("Operational Purpose", table_header_style)],
        [
            Paragraph("<b>Phase 2.2: Ingestion</b>", table_cell_style),
            Paragraph("<code>scripts/ingest.py</code>", table_cell_style),
            Paragraph("<code>embed_document()</code>", table_cell_style),
            Paragraph("Parses markdown/PDF/docs, splits into chunks, converts to 768d vectors, and writes to database.", table_cell_style)
        ],
        [
            Paragraph("<b>Phase 2.3: RAG Search</b>", table_cell_style),
            Paragraph("<code>app/rag.py</code>", table_cell_style),
            Paragraph("<code>embed_query()</code>", table_cell_style),
            Paragraph("Takes user's question, embeds as vector, runs SQL cosine similarity: <code>1 - (embedding &lt;=&gt; query_vec)</code>.", table_cell_style)
        ],
        [
            Paragraph("<b>Phase 2.4: Evaluation</b>", table_cell_style),
            Paragraph("<code>tests/eval_rag.py</code>", table_cell_style),
            Paragraph("<code>chat_completion()</code>", table_cell_style),
            Paragraph("Acts as LLM-as-a-judge to evaluate retrieval precision and factual accuracy against ground truth.", table_cell_style)
        ],
        [
            Paragraph("<b>Phase 2.5: User API</b>", table_cell_style),
            Paragraph("<code>app/main.py</code> (<code>/ask</code>)", table_cell_style),
            Paragraph("<code>embed_query()<br/>chat_completion()</code>", table_cell_style),
            Paragraph("Public FastAPI endpoint: retrieves relevant chunks and generates a grounded response with source citations.", table_cell_style)
        ],
        [
            Paragraph("<b>Phase 3: Agentic AI</b>", table_cell_style),
            Paragraph("<code>app/agent.py</code>", table_cell_style),
            Paragraph("<code>chat_completion()</code>", table_cell_style),
            Paragraph("Multi-turn reasoning, tool execution, and dynamic task delegation for IT operations incidents.", table_cell_style)
        ]
    ]
    flow_table = Table(flow_table_data, colWidths=[95, 95, 105, 209])
    flow_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), brand_blue),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-1), 0.5, border_color),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    story.append(flow_table)
    story.append(Spacer(1, 12))

    # Verification & Test Results
    story.append(Paragraph("5. Verification and Test Results", h1_style))
    story.append(Paragraph(
        "A comprehensive test suite was executed against the live Gemini API and Neon database to validate implementation:",
        body_style
    ))

    test_bullets = [
        "<b>1. Client Authentication:</b> Successfully authenticated with Gemini API using secure key configuration.",
        "<b>2. Document Embeddings:</b> <code>embed_document()</code> produced exact 768-float vectors with normalized Euclidean norm.",
        "<b>3. Query Embeddings:</b> <code>embed_query()</code> correctly produced 768-float vectors optimized for retrieval tasks.",
        "<b>4. Semantic Cosine Matching:</b> Tested vector search logic. Related query (<i>'database failover'</i>) achieved high cosine similarity (>0.76) against disaster recovery chunks, whereas unrelated query (<i>'baking cake'</i>) yielded low similarity (<0.18).",
        "<b>5. Database Indexing:</b> Neon PostgreSQL verified with pgvector extension enabled and HNSW cosine index created successfully."
    ]
    for bullet in test_bullets:
        story.append(Paragraph(f"• {bullet}", body_style))

    story.append(Spacer(1, 10))

    # Next steps
    story.append(Paragraph("6. Next Steps: Roadmap to Phase 2.2", h1_style))
    story.append(Paragraph(
        "With the foundational AI engine complete and verified in Phase 2.1, the next step is <b>Phase 2.2 (Knowledge Base Ingestion)</b>. "
        "In Phase 2.2, we will implement <code>scripts/ingest.py</code> to load operations runbooks, system documentation, and incident guides, "
        "chunk the text with metadata preservation, call <code>embed_document()</code>, and populate the database for semantic search.",
        body_style
    ))

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"PDF successfully generated at: {os.path.abspath(filename)}")

if __name__ == "__main__":
    build_pdf()
