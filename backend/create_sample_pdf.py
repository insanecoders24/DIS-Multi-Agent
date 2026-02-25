"""
Generate a realistic multi-page curriculum PDF that mimics the structure
shown in the user's image — a table-heavy document with:
  - Title headings
  - Numbered sections
  - Multi-column tables (Topic | Content | Speaker)
  - Bold sub-headings inside table cells
  - Paragraph text
  - Footnotes and running headers

This PDF is the showcase input for the DIS demo.
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether,
)
from reportlab.platypus.flowables import HRFlowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

OUT = "data/agentic_ai_curriculum.pdf"
os.makedirs("data", exist_ok=True)

# ── Styles ────────────────────────────────────────────────────────────────────
styles = getSampleStyleSheet()

title_style = ParagraphStyle(
    "Title", parent=styles["Title"],
    fontSize=22, spaceAfter=6, leading=26, alignment=TA_CENTER,
    textColor=colors.HexColor("#1a1a2e"),
)
subtitle_style = ParagraphStyle(
    "Subtitle", parent=styles["Normal"],
    fontSize=11, spaceAfter=14, alignment=TA_CENTER,
    textColor=colors.HexColor("#4a4a6a"),
)
h1_style = ParagraphStyle(
    "H1", parent=styles["Heading1"],
    fontSize=15, spaceBefore=14, spaceAfter=6,
    textColor=colors.HexColor("#1a1a2e"),
    borderPad=4, leading=18,
)
h2_style = ParagraphStyle(
    "H2", parent=styles["Heading2"],
    fontSize=12, spaceBefore=10, spaceAfter=4,
    textColor=colors.HexColor("#2a2a5e"),
)
body_style = ParagraphStyle(
    "Body", parent=styles["Normal"],
    fontSize=9.5, leading=14, alignment=TA_JUSTIFY,
    textColor=colors.HexColor("#2a2a2a"),
)
cell_style = ParagraphStyle(
    "Cell", parent=styles["Normal"],
    fontSize=8.5, leading=13, alignment=TA_LEFT,
    textColor=colors.HexColor("#1a1a1a"),
)
cell_bold_style = ParagraphStyle(
    "CellBold", parent=cell_style,
    fontName="Helvetica-Bold", fontSize=8.5,
)
footnote_style = ParagraphStyle(
    "Footnote", parent=styles["Normal"],
    fontSize=7.5, leading=11, textColor=colors.HexColor("#666666"),
)

def p(text, style=None): return Paragraph(text, style or body_style)
def b(text): return f"<b>{text}</b>"
def i(text): return f"<i>{text}</i>"

# ── Table helper ──────────────────────────────────────────────────────────────
TABLE_STYLE = TableStyle([
    ("BACKGROUND",  (0, 0), (-1, 0), colors.HexColor("#2a2a5e")),
    ("TEXTCOLOR",   (0, 0), (-1, 0), colors.white),
    ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE",    (0, 0), (-1, 0), 9),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5fa")]),
    ("GRID",        (0, 0), (-1, -1), 0.5, colors.HexColor("#c0c0d0")),
    ("VALIGN",      (0, 0), (-1, -1), "TOP"),
    ("LEFTPADDING", (0, 0), (-1, -1), 7),
    ("RIGHTPADDING",(0, 0), (-1, -1), 7),
    ("TOPPADDING",  (0, 0), (-1, -1), 6),
    ("BOTTOMPADDING",(0,0), (-1, -1), 6),
    ("ALIGN",       (0, 0), (-1, 0), "CENTER"),
])

# ── Running header / footer ───────────────────────────────────────────────────
def on_page(canvas, doc):
    canvas.saveState()
    # Header
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#666688"))
    canvas.drawString(2*cm, A4[1] - 1.2*cm, "Agentic AI Programme — Curriculum Outline v2026")
    canvas.drawRightString(A4[0] - 2*cm, A4[1] - 1.2*cm, f"Page {doc.page}")
    canvas.setStrokeColor(colors.HexColor("#c0c0d0"))
    canvas.setLineWidth(0.5)
    canvas.line(2*cm, A4[1] - 1.4*cm, A4[0] - 2*cm, A4[1] - 1.4*cm)
    # Footer
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#888888"))
    canvas.drawCentredString(A4[0]/2, 1.2*cm,
        "Confidential — For internal use only · Birchlogic AI Labs 2026")
    canvas.line(2*cm, 1.8*cm, A4[0] - 2*cm, 1.8*cm)
    canvas.restoreState()

# ── Document content ──────────────────────────────────────────────────────────
doc = SimpleDocTemplate(
    OUT,
    pagesize=A4,
    rightMargin=2*cm, leftMargin=2*cm,
    topMargin=2.5*cm, bottomMargin=2.5*cm,
    title="Agentic AI Programme — Curriculum Outline",
    author="Birchlogic AI Labs",
)

story = []

# ── Cover / Title ─────────────────────────────────────────────────────────────
story.append(Spacer(1, 1*cm))
story.append(p("Agentic AI Programme", title_style))
story.append(p("Curriculum Outline &amp; Speaker Matrix — 2026 Edition", subtitle_style))
story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#2a2a5e"), spaceAfter=10))
story.append(Spacer(1, 0.4*cm))

story.append(p(
    "This document provides the full session-by-session curriculum for the <b>Agentic AI Programme</b>, "
    "including content summaries, learning objectives, and speaker classifications. "
    "Each module is mapped to a delivery format and an expert domain. "
    "The programme is structured across four thematic pillars: Foundations, Architecture, "
    "Regulatory Considerations, and Applied Practice.",
))
story.append(Spacer(1, 0.3*cm))

# ── Section 1 ─────────────────────────────────────────────────────────────────
story.append(p("1. Programme Overview", h1_style))
story.append(p(
    "The programme spans 12 weeks and covers both theoretical foundations and practical "
    "applications of agentic AI systems. Sessions alternate between industry expert guest lectures "
    "and hands-on workshops. Assessment is continuous, with a capstone project in Week 11–12.",
))
story.append(Spacer(1, 0.2*cm))

# Overview table
story.append(p("1.1 Programme Structure", h2_style))
overview_data = [
    [p(b("Module"), cell_style), p(b("Weeks"), cell_style),
     p(b("Format"), cell_style), p(b("Delivery"), cell_style)],
    [p("AI Foundations", cell_style), p("1–2", cell_style),
     p("Lecture + Workshop", cell_style), p("Hybrid", cell_style)],
    [p("Agentic AI Architecture", cell_style), p("3–5", cell_style),
     p("Lecture + Lab", cell_style), p("In-Person", cell_style)],
    [p("Regulatory &amp; Ethics", cell_style), p("6–7", cell_style),
     p("Seminar", cell_style), p("Virtual", cell_style)],
    [p("Frameworks &amp; Tooling", cell_style), p("8–9", cell_style),
     p("Workshop", cell_style), p("In-Person", cell_style)],
    [p("Applied Projects", cell_style), p("10–12", cell_style),
     p("Project-Based", cell_style), p("Hybrid", cell_style)],
]
ov_table = Table(overview_data, colWidths=[6*cm, 2*cm, 4*cm, 3*cm])
ov_table.setStyle(TABLE_STYLE)
story.append(ov_table)
story.append(Spacer(1, 0.4*cm))

# ── Section 2 ─────────────────────────────────────────────────────────────────
story.append(p("2. Session-by-Session Curriculum", h1_style))
story.append(p(
    "The table below describes the content of each session, the topics covered, "
    "key learning outcomes, and the category of speaker. "
    "Speaker categories are: <i>Academic Expert</i>, <i>Industry/Startup Expert</i>, "
    "and <i>Regulatory/Policy Expert</i>.",
))
story.append(Spacer(1, 0.3*cm))

# Main curriculum table — mirrors the image structure closely
story.append(p("2.1 Module 1: AI Foundations (Weeks 1–2)", h2_style))

def content_cell(lines):
    """Build a multi-paragraph cell from a list of (text, bold) tuples."""
    parts = []
    for text, bold in lines:
        if bold:
            parts.append(p(f"<b>{text}</b>", cell_bold_style))
        else:
            parts.append(p(text, cell_style))
        parts.append(Spacer(1, 2))
    return parts

# Curriculum table (matches the image format exactly)
COL_W = [3.8*cm, 10*cm, 3.2*cm]

curr_data_1 = [
    # Header row
    [p(b("Topic"), cell_style), p(b("Content"), cell_style), p(b("Speaker"), cell_style)],

    # Row 1
    [
        p(i("Introduction to LLMs and Foundation Models"), cell_style),
        [
            p("- History and evolution of language models: from n-grams to transformers.", cell_style),
            Spacer(1,3),
            p("- Attention mechanisms, RLHF, and instruction tuning.", cell_style),
            Spacer(1,3),
            p(b("Key architectures:"), cell_bold_style),
            Spacer(1,2),
            p("1. GPT series, Claude, Gemini, Llama 2/3, Mistral.", cell_style),
            Spacer(1,3),
            p("- Prompt engineering: zero-shot, few-shot, chain-of-thought.", cell_style),
            Spacer(1,3),
            p("- Evaluation benchmarks (MMLU, HellaSwag, HumanEval).", cell_style),
        ],
        p("Academic Expert", cell_style),
    ],

    # Row 2 — matches the image
    [
        p(i("Agentic AI – From LLMs to Autonomous Agents"), cell_style),
        [
            p("- From passive LLMs to agentic behavior: memory, planning, and tool use.", cell_style),
            Spacer(1,3),
            p("- Prompt chaining and self-reflection mechanisms.", cell_style),
            Spacer(1,3),
            p(b("Frameworks for agentic AI:"), cell_bold_style),
            Spacer(1,2),
            p("1. LangChain, AutoGen, CrewAI, OpenDevin, and Semantic Kernel.", cell_style),
            Spacer(1,3),
            p("Multi-agent coordination and emergent behavior.", cell_style),
            Spacer(1,3),
            p(b("Agent memory architectures:"), cell_bold_style),
            Spacer(1,2),
            p("1. Episodic, semantic, and vector-based retrieval.", cell_style),
            Spacer(1,3),
            p("Safety, alignment, and interpretability challenges in agentic AI.", cell_style),
        ],
        p("Industry/Startup\nExpert", cell_style),
    ],

    # Row 3
    [
        p(i("Retrieval-Augmented Generation (RAG)"), cell_style),
        [
            p("- Dense vs sparse retrieval: BM25, ColBERT, DPR.", cell_style),
            Spacer(1,3),
            p("- Vector databases: Pinecone, Weaviate, Chroma, Qdrant.", cell_style),
            Spacer(1,3),
            p(b("Advanced RAG patterns:"), cell_bold_style),
            Spacer(1,2),
            p("1. HyDE, self-query, multi-hop reasoning.", cell_style),
            Spacer(1,3),
            p("- Chunking strategies and embedding model selection.", cell_style),
            Spacer(1,3),
            p("- Evaluation: RAGAS, TruLens.", cell_style),
        ],
        p("Academic Expert", cell_style),
    ],
]

curr_table_1 = Table(curr_data_1, colWidths=COL_W, repeatRows=1)
curr_table_1.setStyle(TABLE_STYLE)
story.append(curr_table_1)
story.append(Spacer(1, 0.5*cm))

# ── Section 2.2 ───────────────────────────────────────────────────────────────
story.append(p("2.2 Module 2: Agentic AI Architecture (Weeks 3–5)", h2_style))

curr_data_2 = [
    [p(b("Topic"), cell_style), p(b("Content"), cell_style), p(b("Speaker"), cell_style)],

    [
        p(i("Tool Use and Function Calling"), cell_style),
        [
            p("- OpenAI function calling, Anthropic tool use, Gemini tool integration.", cell_style),
            Spacer(1,3),
            p(b("Tool categories:"), cell_bold_style),
            Spacer(1,2),
            p("1. Code execution, web search, database queries, API calls.", cell_style),
            Spacer(1,2),
            p("2. File I/O, browser automation, calendar and email.", cell_style),
            Spacer(1,3),
            p("- Tool selection and routing strategies.", cell_style),
            Spacer(1,3),
            p("- Error handling and retry logic in agentic loops.", cell_style),
        ],
        p("Industry/Startup\nExpert", cell_style),
    ],

    [
        p(i("Multi-Agent System Design"), cell_style),
        [
            p("- Orchestrator-agent and peer-to-peer architectures.", cell_style),
            Spacer(1,3),
            p(b("Coordination patterns:"), cell_bold_style),
            Spacer(1,2),
            p("1. Sequential, parallel, hierarchical.", cell_style),
            Spacer(1,2),
            p("2. Reflection and critic patterns.", cell_style),
            Spacer(1,3),
            p("- Message passing protocols and shared memory.", cell_style),
            Spacer(1,3),
            p("- Failure modes: hallucination cascades, infinite loops.", cell_style),
            Spacer(1,3),
            p(b("Frameworks:"), cell_bold_style),
            Spacer(1,2),
            p("1. AutoGen Studio, CrewAI, LangGraph.", cell_style),
        ],
        p("Industry/Startup\nExpert", cell_style),
    ],

    [
        p(i("Planning and Reasoning in Agents"), cell_style),
        [
            p("- ReAct (Reason + Act) paradigm and chain-of-thought prompting.", cell_style),
            Spacer(1,3),
            p(b("Planning algorithms:"), cell_bold_style),
            Spacer(1,2),
            p("1. Tree-of-Thoughts (ToT), Graph-of-Thoughts (GoT).", cell_style),
            Spacer(1,2),
            p("2. MCTS-based planning for complex tasks.", cell_style),
            Spacer(1,3),
            p("- Task decomposition and sub-goal generation.", cell_style),
            Spacer(1,3),
            p("- Self-correction loops and reflective agents.", cell_style),
        ],
        p("Academic Expert", cell_style),
    ],

    [
        p(i("Observability and Evaluation"), cell_style),
        [
            p("- Tracing agent execution with LangSmith, Arize, W&amp;B Weave.", cell_style),
            Spacer(1,3),
            p(b("Evaluation metrics:"), cell_bold_style),
            Spacer(1,2),
            p("1. Task completion rate, step efficiency, tool accuracy.", cell_style),
            Spacer(1,2),
            p("2. Hallucination rate, context faithfulness.", cell_style),
            Spacer(1,3),
            p("- Human-in-the-loop evaluation pipelines.", cell_style),
        ],
        p("Industry/Startup\nExpert", cell_style),
    ],
]

curr_table_2 = Table(curr_data_2, colWidths=COL_W, repeatRows=1)
curr_table_2.setStyle(TABLE_STYLE)
story.append(curr_table_2)
story.append(PageBreak())

# ── Section 3 — Regulatory ─────────────────────────────────────────────────
story.append(p("3. Regulatory and Ethics Module (Weeks 6–7)", h1_style))
story.append(p(
    "This module provides an overview of the global AI regulatory landscape and its implications "
    "for organisations deploying agentic systems. Guest speakers include policy advisors, legal "
    "experts, and compliance practitioners.",
))
story.append(Spacer(1, 0.3*cm))

curr_data_3 = [
    [p(b("Topic"), cell_style), p(b("Content"), cell_style), p(b("Speaker"), cell_style)],

    [
        p(i("EU AI Act and Global Regulatory Landscape"), cell_style),
        [
            p("- EU AI Act: risk categories, prohibited practices, and high-risk systems.", cell_style),
            Spacer(1,3),
            p("- GDPR interaction with generative AI systems.", cell_style),
            Spacer(1,3),
            p(b("Comparative regulatory review:"), cell_bold_style),
            Spacer(1,2),
            p("1. US Executive Order on AI Safety.", cell_style),
            Spacer(1,2),
            p("2. UK Pro-Innovation Regulatory Approach.", cell_style),
            Spacer(1,2),
            p("3. India DPDPA 2023 and proposed AI Act.", cell_style),
            Spacer(1,3),
            p("- Conformity assessments and CE marking for AI.", cell_style),
        ],
        p("Regulatory/Policy\nExpert", cell_style),
    ],

    [
        p(i("AI Safety, Alignment, and Responsible Deployment"), cell_style),
        [
            p("- Constitutional AI and RLHF-based alignment techniques.", cell_style),
            Spacer(1,3),
            p(b("Safety properties for agentic systems:"), cell_bold_style),
            Spacer(1,2),
            p("1. Corrigibility, value alignment, and human oversight.", cell_style),
            Spacer(1,2),
            p("2. Minimal footprint and reversibility principles.", cell_style),
            Spacer(1,3),
            p("- Red-teaming, adversarial testing, and jailbreak resistance.", cell_style),
            Spacer(1,3),
            p("- Bias, fairness, and model transparency auditing.", cell_style),
        ],
        p("Academic Expert", cell_style),
    ],

    [
        p(i("Data Privacy and Intellectual Property"), cell_style),
        [
            p("- Training data provenance and copyright implications.", cell_style),
            Spacer(1,3),
            p(b("Data minimisation principles for AI:"), cell_bold_style),
            Spacer(1,2),
            p("1. Purpose limitation and storage constraints.", cell_style),
            Spacer(1,2),
            p("2. Subject access rights in AI-generated outputs.", cell_style),
            Spacer(1,3),
            p("- Watermarking, provenance tracking, and content authentication.", cell_style),
            Spacer(1,3),
            p("- Liability frameworks for autonomous AI decisions.", cell_style),
        ],
        p("Regulatory/Policy\nExpert", cell_style),
    ],
]

curr_table_3 = Table(curr_data_3, colWidths=COL_W, repeatRows=1)
curr_table_3.setStyle(TABLE_STYLE)
story.append(curr_table_3)
story.append(Spacer(1, 0.5*cm))

# ── Section 4 — Assessment ─────────────────────────────────────────────────
story.append(p("4. Assessment and Evaluation Framework", h1_style))
story.append(p(
    "Participants are evaluated on three dimensions: conceptual understanding, "
    "practical implementation, and critical reflection on regulatory implications.",
))
story.append(Spacer(1, 0.2*cm))

assess_data = [
    [p(b("Component"), cell_style), p(b("Weight"), cell_style),
     p(b("Week Due"), cell_style), p(b("Description"), cell_style)],
    [p("Quiz — Foundations", cell_style), p("10%", cell_style),
     p("Week 2", cell_style), p("Multiple choice, open-book, 45 minutes.", cell_style)],
    [p("Architecture Design Report", cell_style), p("20%", cell_style),
     p("Week 5", cell_style),
     p("Design a multi-agent system for a given use-case (1500 words).", cell_style)],
    [p("Regulatory Impact Assessment", cell_style), p("20%", cell_style),
     p("Week 7", cell_style),
     p("Analyse EU AI Act applicability to a provided system specification.", cell_style)],
    [p("Framework Implementation", cell_style), p("20%", cell_style),
     p("Week 9", cell_style),
     p("Build a working agentic pipeline using LangGraph or AutoGen.", cell_style)],
    [p("Capstone Project", cell_style), p("30%", cell_style),
     p("Week 12", cell_style),
     p("End-to-end agentic system with documentation, evaluation, and demo.", cell_style)],
]
assess_table = Table(assess_data, colWidths=[4.5*cm, 1.5*cm, 2.5*cm, 8.5*cm])
assess_table.setStyle(TABLE_STYLE)
story.append(assess_table)
story.append(Spacer(1, 0.5*cm))

# ── Section 5 — Footnotes and Terms ───────────────────────────────────────
story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#aaaaaa"), spaceBefore=4))
story.append(Spacer(1, 0.1*cm))
story.append(p(
    "<sup>1</sup> All sessions are recorded. Participants must comply with the recording consent "
    "notice issued at programme start. Recordings are stored for 12 months post-programme "
    "and accessible only to enrolled participants.",
    footnote_style,
))
story.append(p(
    "<sup>2</sup> Speaker engagements are subject to availability. Birchlogic AI Labs reserves "
    "the right to substitute with an equivalent expert without prior notice.",
    footnote_style,
))
story.append(p(
    "<sup>3</sup> Content in this curriculum is updated annually. Refer to Table 1 (Programme Structure) "
    "for the official module sequence. See Table 3 (Regulatory Module) for data privacy obligations.",
    footnote_style,
))

# ── Build PDF ─────────────────────────────────────────────────────────────────
doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
print(f"PDF generated: {OUT}")
