"""
DIS Document Q&A — RAG-powered chat over processed document data.

Retrieval strategy:
  1. Keyword search across blocks (LIKE-based, fast, no vector DB needed)
  2. Sort retrieved blocks by relevance score (keyword match count)
  3. Also pull document sections and tables as structured context
  4. Send context window to the configured LLM with citation instructions
  5. Return answer + cited block/section sources
"""
from __future__ import annotations
import re
from typing import Optional

from pydantic import BaseModel
from sqlalchemy.orm import Session

from agents.gemini_client import query as llm_query
from database import SessionLocal
from models.entities import Block, Section, DISTable, Document


# ── Request / Response models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question: str
    max_context_blocks: int = 20


class CitedSource(BaseModel):
    block_id: Optional[str] = None
    section_title: Optional[str] = None
    page_number: Optional[int] = None
    text_snippet: str
    source_type: str   # "block" | "section" | "table"


class ChatResponse(BaseModel):
    answer: str
    sources: list[CitedSource]
    token_count_estimate: int


# ── Core retrieval + generation ───────────────────────────────────────────────

def _score_block(text: str, keywords: list[str]) -> int:
    """Count how many keywords appear in the block text (case-insensitive)."""
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw in text_lower)


def retrieve_context(
    document_id: str,
    question: str,
    max_blocks: int,
    db: Session,
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Retrieve relevant blocks, sections, and tables for the question.
    Returns (blocks, sections, tables) each as plain dicts.
    """
    # ── Extract keywords from the question ───────────────────────────────────
    question_lower = question.lower()
    # Split into meaningful tokens (≥3 chars, ignore stopwords)
    stopwords = {"the","a","an","is","in","of","for","and","or","to","what","when",
                 "why","how","who","which","are","was","were","do","does","did",
                 "this","that","these","those","with","from","about","can","will",
                 "has","have","had","be","been","being","at","by","as","on","into"}
    keywords = [w for w in re.findall(r'\b\w{3,}\b', question_lower) if w not in stopwords]

    # ── Block search using simple LIKE matching ───────────────────────────────
    if keywords:
        # Build a broad OR query to get candidate blocks
        from sqlalchemy import or_
        conditions = [Block.text_content.ilike(f"%{kw}%") for kw in keywords[:6]]
        candidate_blocks = (
            db.query(Block)
            .filter(Block.document_id == document_id)
            .filter(or_(*conditions))
            .filter(Block.text_content != "")
            .limit(max_blocks * 3)   # over-fetch, then re-rank
            .all()
        )
    else:
        # No keywords — just get all blocks
        candidate_blocks = (
            db.query(Block)
            .filter(Block.document_id == document_id)
            .filter(Block.text_content != "")
            .order_by(Block.reading_order)
            .limit(max_blocks)
            .all()
        )

    # ── Re-rank by keyword score ──────────────────────────────────────────────
    scored = [
        (b, _score_block(b.text_content or "", keywords))
        for b in candidate_blocks
    ]
    scored.sort(key=lambda x: (-x[1], x[0].reading_order))
    top_blocks = [b for b, _ in scored[:max_blocks]]

    block_dicts = [
        {
            "block_id": b.block_id,
            "block_type": b.block_type,
            "page_number": int(b.page_id.split(":p")[-1]) if ":p" in (b.page_id or "") else None,
            "section_id": b.section_id,
            "text": b.text_content or "",
            "is_heading": b.block_type in ("Heading", "Title"),
        }
        for b in top_blocks
    ]

    # ── Pull all sections as structured context ───────────────────────────────
    sections = (
        db.query(Section)
        .filter(Section.document_id == document_id)
        .order_by(Section.section_order)
        .all()
    )
    section_dicts = [
        {
            "section_id": s.section_id,
            "title": s.title or "",
            "level": s.level,
            "heading_number": s.heading_number or "",
            "start_page": s.start_page,
            "end_page": s.end_page,
        }
        for s in sections
    ]

    # ── Pull tables ───────────────────────────────────────────────────────────
    tables = (
        db.query(DISTable)
        .filter(DISTable.document_id == document_id)
        .all()
    )
    table_dicts = [
        {
            "table_id": t.table_id,
            "caption": t.caption or "",
            "table_number": t.table_number or "",
            "rows": t.row_count,
            "cols": t.column_count,
            "page": t.start_page,
            "cells": t.cells_json or [],
        }
        for t in tables
    ]

    return block_dicts, section_dicts, table_dicts


def build_context_prompt(
    question: str,
    blocks: list[dict],
    sections: list[dict],
    tables: list[dict],
    doc_title: str,
) -> str:
    """Assemble the full RAG prompt sent to the LLM."""

    # Sections outline (always included for navigation context)
    section_outline = "\n".join(
        f"  {'  ' * (s['level']-1)}{s['heading_number'] + ' ' if s['heading_number'] else ''}{s['title']} (pages {s['start_page']}–{s['end_page']})"
        for s in sections[:30]
    ) or "  (no sections extracted)"

    # Table summaries
    table_summary = "\n".join(
        f"  Table {t['table_number'] or t['table_id'][:8]}: {t['caption'] or 'untitled'} — {t['rows']}×{t['cols']} cells on page {t['page']}"
        for t in tables
    ) or "  (no tables)"

    # Most relevant passages
    passages = ""
    for i, b in enumerate(blocks[:18], 1):
        pg = f"[p{b['page_number']}]" if b["page_number"] else ""
        ty = f"[{b['block_type']}]" if b["block_type"] else ""
        passages += f"\n--- Passage {i} {ty} {pg} block_id={b['block_id']} ---\n{b['text']}\n"

    if not passages:
        passages = "\n(No matching passages retrieved.)\n"

    prompt = f"""You are an intelligent research assistant with full access to a processed document.

DOCUMENT TITLE: "{doc_title}"

DOCUMENT STRUCTURE (sections):
{section_outline}

AVAILABLE TABLES:
{table_summary}

MOST RELEVANT PASSAGES FROM THE DOCUMENT:
{passages}

---
USER QUESTION: {question}

INSTRUCTIONS:
- Answer the question accurately and completely based ONLY on the document content above.
- If the answer spans multiple sections, synthesize them clearly.
- Reference specific passages by citing them as [Passage N] or mentioning the page number.
- If the document contains tables relevant to the question, describe their content.
- If the answer is not found in the document, say so clearly — do not hallucinate.
- Format your response with clear paragraphs. Use bullet points for lists.
- At the end, list the key sources you used as: SOURCES: [Passage 1] (page X), [Passage 3] (page Y), ...

Answer:"""

    return prompt


def answer_question(document_id: str, question: str, max_blocks: int = 20) -> ChatResponse:
    """Full RAG pipeline: retrieve + generate + format sources."""
    db = SessionLocal()
    try:
        # Get document title
        doc = db.get(Document, document_id)
        doc_title = (doc.title or doc.source_path or "Unknown Document") if doc else "Unknown Document"

        # Retrieve context
        blocks, sections, tables = retrieve_context(document_id, question, max_blocks, db)

        # Guard: if no blocks were extracted, document needs re-processing
        if not blocks:
            return ChatResponse(
                answer=(
                    "⚠️ This document has no extracted text blocks yet.\n\n"
                    "This happens when the document was processed before the extraction engine was updated. "
                    "Please **re-upload the PDF** to trigger a fresh pipeline run — after that, all text, "
                    "sections, and tables will be available for Q&A.\n\n"
                    f"Document: *{doc_title}*\n"
                    f"Sections in DB: {len(sections)} · Tables in DB: {len(tables)}"
                ),
                sources=[],
                token_count_estimate=0,
            )

        # Build prompt
        prompt = build_context_prompt(question, blocks, sections, tables, doc_title)

        # Call LLM
        raw_answer = llm_query(
            prompt=prompt,
            system_extra=(
                "You are a precise document research assistant. "
                "Ground every statement in the provided document passages. "
                "Always cite passage numbers and page references."
            ),
            temperature=0.1,
            max_tokens=1024,
        )

        # Extract cited sources from the used blocks
        sources: list[CitedSource] = []
        answer_lower = raw_answer.lower()

        # Add blocks that were mentioned or clearly relevant
        for i, b in enumerate(blocks[:18], 1):
            if (
                f"passage {i}" in answer_lower
                or (b["text"] and any(
                    kw in answer_lower for kw in b["text"].lower().split()[:5] if len(kw) > 4
                ))
            ):
                sources.append(CitedSource(
                    block_id=b["block_id"],
                    page_number=b["page_number"],
                    text_snippet=(b["text"] or "")[:160].strip(),
                    source_type="block",
                ))

        # Always include top 3 sections for navigation
        for s in sections[:3]:
            sources.append(CitedSource(
                section_title=s["title"],
                page_number=s["start_page"],
                text_snippet=f"Section: {s['heading_number']} {s['title']} (pp. {s['start_page']}–{s['end_page']})",
                source_type="section",
            ))

        # Deduplicate and limit
        seen = set()
        deduped_sources = []
        for s in sources:
            key = s.block_id or s.section_title
            if key not in seen:
                seen.add(key)
                deduped_sources.append(s)

        return ChatResponse(
            answer=raw_answer,
            sources=deduped_sources[:10],
            token_count_estimate=len(prompt.split()) + len(raw_answer.split()),
        )

    finally:
        db.close()
