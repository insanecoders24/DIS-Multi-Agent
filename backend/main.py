"""
DIS FastAPI Application — with SSE streaming for live agent activity.
"""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from dotenv import load_dotenv
load_dotenv()

from database import SessionLocal, init_db
from models.entities import Document, Page, Block, Section, DISTable, CrossReference, EvidenceAnchor
from agents.orchestrator import OrchestratorAgent, new_job, get_job
import config

app = FastAPI(
    title="Document Intelligence System (DIS) — Multi-Agent",
    description="Regulatory-grade deterministic PDF pipeline with live agent streaming",
    version=config.DIS_VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


_UPLOAD_DIR = "/tmp/storage/uploads" if os.getenv("VERCEL") else "storage/uploads"

@app.on_event("startup")
def startup():
    init_db()
    os.makedirs(config.PDF_STORAGE_DIR, exist_ok=True)
    os.makedirs(config.PAGE_IMAGE_DIR, exist_ok=True)
    os.makedirs(_UPLOAD_DIR, exist_ok=True)


# ── Health ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "version": config.DIS_VERSION}


# ═══════════════════════════════════════════════════════════════
# Agent pipeline — trigger + SSE stream
# ═══════════════════════════════════════════════════════════════

@app.post("/api/agent/process-path")
def agent_process_path(body: dict, background_tasks: BackgroundTasks):
    """Trigger the multi-agent pipeline; returns job_id for SSE polling."""
    path = body.get("path", "")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=400, detail=f"File not found: {path}")
    name = os.path.basename(path)
    job_id, bus = new_job()
    background_tasks.add_task(_run_agent_pipeline, job_id, bus, path, name)
    return {"job_id": job_id, "message": "Agent pipeline started", "path": path}


@app.post("/api/agent/upload")
async def agent_upload(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Upload PDF and trigger multi-agent pipeline; returns job_id."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    upload_dir = Path(_UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = str(upload_dir / file.filename)
    content = await file.read()
    with open(path, "wb") as f:
        f.write(content)
    job_id, bus = new_job()
    background_tasks.add_task(_run_agent_pipeline, job_id, bus, path, file.filename)
    return {"job_id": job_id, "message": "Agent pipeline started", "filename": file.filename}


def _run_agent_pipeline(job_id: str, bus: asyncio.Queue, path: str, name: str):
    """Sync wrapper — runs in BackgroundTasks thread."""
    async def _inner():
        job = get_job(job_id)
        try:
            orchestrator = OrchestratorAgent(bus)
            await orchestrator.run(path, name)
            if job:
                job["status"] = "complete"
        except Exception as e:
            await bus.put({"type": "pipeline_error", "agent": "orchestrator",
                           "message": str(e), "timestamp": ""})
            if job:
                job["status"] = "error"
        finally:
            # Sentinel to close SSE stream
            await bus.put({"type": "stream_end", "agent": "system", "timestamp": ""})

    asyncio.run(_inner())


@app.get("/api/agent/stream/{job_id}")
async def agent_stream(job_id: str, request: Request):
    """SSE endpoint — streams all agent events for a job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    bus: asyncio.Queue = job["bus"]

    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(bus.get(), timeout=30.0)
                job.setdefault("events", []).append(event)
                data = json.dumps(event)
                yield f"data: {data}\n\n"
                if event.get("type") == "stream_end":
                    break
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/agent/jobs/{job_id}")
def get_job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job_id,
        "status": job.get("status", "running"),
        "event_count": len(job.get("events", [])),
    }


# ═══════════════════════════════════════════════════════════════
# Legacy pipeline endpoint (kept for compatibility)
# ═══════════════════════════════════════════════════════════════

@app.post("/api/documents/process-path")
def process_path(body: dict, background_tasks: BackgroundTasks):
    job_id, bus = new_job()
    path = body.get("path", "")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=400, detail=f"File not found: {path}")
    name = os.path.basename(path)
    background_tasks.add_task(_run_agent_pipeline, job_id, bus, path, name)
    return {"message": "Processing started.", "path": path, "job_id": job_id}


# ═══════════════════════════════════════════════════════════════
# RAG Chat — NotebookLM-style Q&A over processed documents
# ═══════════════════════════════════════════════════════════════

from rag_chat import ChatRequest, ChatResponse, answer_question

# In-memory chat history per document (cleared on restart; fine for demo)
_chat_histories: dict[str, list[dict]] = {}

@app.post("/api/documents/{document_id}/chat", response_model=ChatResponse)
def chat_with_document(document_id: str, req: ChatRequest):
    """Ask a question grounded in the document's extracted text, sections, and tables."""
    db: Session = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        # Allow chat on any document that exists — complete, processing, or human_review
    finally:
        db.close()

    response = answer_question(document_id, req.question, req.max_context_blocks)

    # Store in history
    history = _chat_histories.setdefault(document_id, [])
    history.append({"question": req.question, "answer": response.answer, "sources": [s.dict() for s in response.sources]})

    return response


@app.get("/api/documents/{document_id}/chat/history")
def get_chat_history(document_id: str):
    """Return the in-memory chat history for a document."""
    return _chat_histories.get(document_id, [])


@app.delete("/api/documents/{document_id}/chat/history")
def clear_chat_history(document_id: str):
    """Clear chat history for a document."""
    _chat_histories.pop(document_id, None)
    return {"cleared": True}




# ═══════════════════════════════════════════════════════════════
# Document REST APIs (unchanged)
# ═══════════════════════════════════════════════════════════════

@app.get("/api/documents")
def list_documents():
    db: Session = SessionLocal()
    try:
        docs = db.query(Document).order_by(Document.ingest_time.desc()).all()
        return [
            {
                "document_id": d.document_id,
                "title": d.title or d.source_path,
                "source_path": d.source_path,
                "ingest_time": d.ingest_time.isoformat() if d.ingest_time else None,
                "page_count": d.page_count,
                "status": d.status,
                "sha256_hash": d.sha256_hash[:16] + "…",
                "parser_version": d.parser_version,
            }
            for d in docs
        ]
    finally:
        db.close()


@app.get("/api/documents/{document_id}")
def get_document(document_id: str):
    db: Session = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if not doc:
            raise HTTPException(status_code=404)
        return {
            "document_id": doc.document_id,
            "title": doc.title,
            "author": doc.author,
            "creation_date": doc.creation_date,
            "source_path": doc.source_path,
            "sha256_hash": doc.sha256_hash,
            "ingest_time": doc.ingest_time.isoformat() if doc.ingest_time else None,
            "page_count": doc.page_count,
            "status": doc.status,
            "parser_version": doc.parser_version,
            "config_id": doc.config_id,
            "file_size_bytes": doc.file_size_bytes,
        }
    finally:
        db.close()


@app.get("/api/documents/{document_id}/sections")
def get_sections(document_id: str):
    db: Session = SessionLocal()
    try:
        sections = db.query(Section).filter(Section.document_id == document_id).order_by(Section.section_order).all()
        return [
            {"section_id": s.section_id, "title": s.title, "level": s.level,
             "section_order": s.section_order, "parent_section_id": s.parent_section_id,
             "heading_number": s.heading_number, "start_page": s.start_page,
             "end_page": s.end_page, "continues_on_next_page": s.continues_on_next_page,
             "confidence_score": s.confidence_score, "is_uncertain": s.is_uncertain,
             "uncertainty_reason": s.uncertainty_reason}
            for s in sections
        ]
    finally:
        db.close()


@app.get("/api/documents/{document_id}/pages/{page_number}/blocks")
def get_blocks_on_page(document_id: str, page_number: int):
    db: Session = SessionLocal()
    try:
        page_id = f"{document_id}:p{page_number}"
        blocks = db.query(Block).filter(Block.page_id == page_id).order_by(Block.reading_order).all()
        return [
            {"block_id": b.block_id, "block_type": b.block_type,
             "text_content": b.text_content, "page_id": b.page_id,
             "x0": b.x0, "y0": b.y0, "x1": b.x1, "y1": b.y1,
             "font_size": b.font_size, "is_bold": b.is_bold,
             "heading_level": b.heading_level, "heading_number": b.heading_number,
             "section_id": b.section_id, "reading_order": b.reading_order,
             "confidence_score": b.confidence_score, "is_uncertain": b.is_uncertain,
             "uncertainty_reason": b.uncertainty_reason}
            for b in blocks
        ]
    finally:
        db.close()


@app.get("/api/documents/{document_id}/tables")
def get_tables(document_id: str):
    db: Session = SessionLocal()
    try:
        tables = db.query(DISTable).filter(DISTable.document_id == document_id).all()
        return [
            {"table_id": t.table_id, "caption": t.caption, "table_number": t.table_number,
             "row_count": t.row_count, "column_count": t.column_count,
             "start_page": t.start_page, "section_id": t.section_id,
             "confidence_score": t.confidence_score, "is_uncertain": t.is_uncertain}
            for t in tables
        ]
    finally:
        db.close()


@app.get("/api/documents/{document_id}/tables/{table_id}")
def get_table_detail(document_id: str, table_id: str):
    db: Session = SessionLocal()
    try:
        t = db.get(DISTable, table_id)
        if not t or t.document_id != document_id:
            raise HTTPException(status_code=404)
        return {"table_id": t.table_id, "caption": t.caption, "table_number": t.table_number,
                "row_count": t.row_count, "column_count": t.column_count,
                "start_page": t.start_page, "end_page": t.end_page,
                "section_id": t.section_id, "x0": t.x0, "y0": t.y0, "x1": t.x1, "y1": t.y1,
                "cells": t.cells_json, "confidence_score": t.confidence_score,
                "is_uncertain": t.is_uncertain, "uncertainty_reason": t.uncertainty_reason}
    finally:
        db.close()


@app.get("/api/documents/{document_id}/references")
def get_references(document_id: str):
    db: Session = SessionLocal()
    try:
        refs = db.query(CrossReference).filter(CrossReference.document_id == document_id).all()
        return [
            {"ref_id": r.ref_id, "source_block_id": r.source_block_id,
             "ref_text": r.ref_text, "ref_type": r.ref_type,
             "target_id": r.target_id, "target_type": r.target_type,
             "is_resolved": r.is_resolved}
            for r in refs
        ]
    finally:
        db.close()


@app.get("/api/documents/{document_id}/uncertainty")
def get_uncertainty_report(document_id: str):
    db: Session = SessionLocal()
    try:
        ub = db.query(Block).filter(Block.document_id == document_id, Block.is_uncertain == True).all()
        ut = db.query(DISTable).filter(DISTable.document_id == document_id, DISTable.is_uncertain == True).all()
        ur = db.query(CrossReference).filter(CrossReference.document_id == document_id, CrossReference.is_resolved == False).all()
        return {
            "uncertain_blocks": [{"block_id": b.block_id, "block_type": b.block_type,
                "text_snippet": (b.text_content or "")[:100], "confidence_score": b.confidence_score,
                "reason": b.uncertainty_reason, "page_id": b.page_id} for b in ub],
            "uncertain_tables": [{"table_id": t.table_id, "caption": t.caption,
                "confidence_score": t.confidence_score, "reason": t.uncertainty_reason} for t in ut],
            "unresolved_references": [{"ref_id": r.ref_id, "ref_text": r.ref_text,
                "ref_type": r.ref_type, "source_block_id": r.source_block_id} for r in ur],
        }
    finally:
        db.close()


@app.get("/api/documents/{document_id}/pages/{page_number}/image")
def get_page_image(document_id: str, page_number: int):
    img_path = Path(config.PAGE_IMAGE_DIR) / document_id / f"p{page_number:04d}.png"
    if not img_path.exists():
        raise HTTPException(status_code=404, detail="Page image not found.")
    return FileResponse(str(img_path), media_type="image/png")


@app.get("/api/documents/{document_id}/search")
def search_document(document_id: str, q: str):
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query is empty.")
    db: Session = SessionLocal()
    try:
        blocks = db.query(Block).filter(
            Block.document_id == document_id,
            Block.text_content.ilike(f"%{q}%"),
        ).order_by(Block.reading_order).limit(100).all()
        return {"query": q, "result_count": len(blocks), "results": [
            {"block_id": b.block_id, "block_type": b.block_type,
             "text_content": b.text_content, "page_id": b.page_id,
             "section_id": b.section_id, "x0": b.x0, "y0": b.y0, "x1": b.x1, "y1": b.y1}
            for b in blocks
        ]}
    finally:
        db.close()
