"""
DIS Full Pipeline Orchestrator — Stages 1–9.

Runs all 9 stages in sequence, persists every entity to the database,
and logs progress. Designed to be idempotent: if a document_id already
exists in the DB, it returns the existing record without reprocessing.

All decisions in this pipeline are deterministic:
- Same PDF + same config_id → identical DB records every run.
- IDs are content-derived (no random UUIDs).
- No LLM or ML model inference occurs here.
"""
from __future__ import annotations
import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

import config
from database import SessionLocal
from models.entities import (
    Document, Page, Block, Section, DISTable,
    CrossReference, EvidenceAnchor,
)
from pipeline_stages.ingestion   import ingest_pdf
from pipeline_stages.extraction  import extract_all_pages
from pipeline_stages.segmentation import (
    segment_page, classify_blocks, detect_running_headers,
    ClassifiedBlock,
)
from pipeline_stages.assembly    import assemble_sections, assign_block_to_section
from pipeline_stages.table_parser import parse_all_tables
from pipeline_stages.references  import detect_references_in_block, resolve_references


# ─────────────────────────────────────────────────────────────────────────────
# Progress store (in-memory; production would use Redis or DB)
# ─────────────────────────────────────────────────────────────────────────────
_progress: dict[str, dict] = {}


def get_progress(document_id: str) -> dict:
    return _progress.get(document_id, {"status": "unknown", "stage": ""})


def _set_progress(document_id: str, status: str, stage: str, detail: str = ""):
    _progress[document_id] = {"status": status, "stage": stage, "detail": detail}


# ─────────────────────────────────────────────────────────────────────────────
# Helper: stable block ID
# ─────────────────────────────────────────────────────────────────────────────

def _block_id(document_id: str, page_number: int, order: int) -> str:
    raw = f"{document_id}:p{page_number}:b{order:04d}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _anchor_id(document_id: str, page_number: int, entity_id: str) -> str:
    raw = f"{document_id}:p{page_number}:anc:{entity_id}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────────────────────

async def process_document(
    pdf_path: str,
    original_filename: str,
    config_id: str = "default",
) -> str:
    """
    Full DIS pipeline. Returns document_id.
    Call get_progress(document_id) to poll status.
    """
    # ── Quick check: already processed? ─────────────────────────────────────
    import hashlib as _hl
    sha = _hl.sha256()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    document_id = sha.hexdigest()

    db: Session = SessionLocal()
    try:
        existing = db.get(Document, document_id)
        if existing and existing.status == "complete":
            _set_progress(document_id, "complete", "done", "Already processed.")
            return document_id
    finally:
        db.close()

    _set_progress(document_id, "running", "ingestion", "Ingesting PDF…")

    db = SessionLocal()
    try:
        # ── Stage 1+2: Ingestion & Page Normalization ────────────────────────
        document, page_records = ingest_pdf(
            pdf_path, original_filename,
            parser_version=config.DIS_VERSION,
            config_id=config_id,
        )
        db.merge(document)
        for pr in page_records:
            db.merge(pr)
        db.commit()

        _set_progress(document_id, "running", "extraction", f"Extracting text from {len(page_records)} pages…")

        # ── Stage 3: Text Extraction ─────────────────────────────────────────
        raw_pages = extract_all_pages(pdf_path, page_records)

        # ── Stage 4+5: Segmentation + Classification ─────────────────────────
        _set_progress(document_id, "running", "segmentation", "Segmenting blocks…")

        all_page_raw_blocks = []
        for rp, pr in zip(raw_pages, page_records):
            raw_blocks = segment_page(rp, pr.width, pr.height)
            all_page_raw_blocks.append(raw_blocks)

        # Detect running headers across all pages (needs full page view)
        running_header_texts = detect_running_headers(
            all_page_raw_blocks,
            [pr.height for pr in page_records],
        )

        # Classify blocks on each page
        pages_classified: list[tuple[int, list[ClassifiedBlock]]] = []
        all_classified_blocks: list[tuple[int, ClassifiedBlock, str]] = []
        # (page_number, classified_block, block_id)

        for pg_idx, (raw_blocks, pr) in enumerate(zip(all_page_raw_blocks, page_records)):
            classified = classify_blocks(raw_blocks, pr.height, running_header_texts)
            pages_classified.append((pr.page_number, classified))
            for order, cb in enumerate(classified):
                bid = _block_id(document_id, pr.page_number, order)
                all_classified_blocks.append((pr.page_number, cb, bid))

        # ── Stage 6: Section Assembly ─────────────────────────────────────────
        _set_progress(document_id, "running", "assembly", "Assembling sections…")
        section_drafts = assemble_sections(document_id, pages_classified)

        # Build section_id lookup (heading_number → section_id)
        section_index: dict[str, str] = {}
        for sd in section_drafts:
            if sd.heading_number:
                section_index[sd.heading_number] = sd.section_id
            section_index[sd.title] = sd.section_id

        # Persist sections
        for order, sd in enumerate(section_drafts):
            sec = Section(
                section_id=sd.section_id,
                document_id=document_id,
                title=sd.title,
                level=sd.level,
                section_order=sd.section_order,
                parent_section_id=sd.parent_section_id,
                header_block_id=None,  # updated below after block persist
                start_page=sd.start_page,
                end_page=sd.end_page,
                continues_on_next_page=sd.continues_on_next_page,
                heading_number=sd.heading_number,
                confidence_score=sd.confidence,
                is_uncertain=sd.is_uncertain,
                uncertainty_reason=sd.uncertainty_reason,
            )
            db.merge(sec)
        db.commit()

        # ── Persist Blocks + Evidence Anchors ────────────────────────────────
        _set_progress(document_id, "running", "blocks", "Persisting blocks and anchors…")

        page_id_map = {pr.page_number: pr.page_id for pr in page_records}
        page_captions: dict[int, list[str]] = {}

        for page_number, cb, bid in all_classified_blocks:
            page_id = page_id_map.get(page_number, "")
            section_id = assign_block_to_section(
                bid, cb.block_type, page_number, section_drafts
            )

            block = Block(
                block_id=bid,
                document_id=document_id,
                page_id=page_id,
                section_id=section_id,
                reading_order=all_classified_blocks.index((page_number, cb, bid)),
                x0=cb.raw.x0, y0=cb.raw.y0,
                x1=cb.raw.x1, y1=cb.raw.y1,
                text_content=cb.raw.text,
                block_type=cb.block_type,
                font_name=cb.raw.font_name,
                font_size=cb.raw.font_size,
                is_bold=cb.raw.is_bold,
                is_italic=cb.raw.is_italic,
                heading_level=cb.heading_level,
                heading_number=cb.heading_number,
                confidence_score=cb.confidence,
                is_uncertain=cb.is_uncertain,
                uncertainty_reason=cb.uncertainty_reason,
            )
            db.merge(block)

            # Evidence anchor for this block
            anchor = EvidenceAnchor(
                anchor_id=_anchor_id(document_id, page_number, bid),
                document_id=document_id,
                page_id=page_id,
                page_number=page_number,
                x0=cb.raw.x0, y0=cb.raw.y0,
                x1=cb.raw.x1, y1=cb.raw.y1,
                linked_entity_id=bid,
                linked_entity_type="block",
                text_snippet=cb.raw.text[:200] if cb.raw.text else None,
            )
            db.merge(anchor)

            # Collect captions for table matching
            if cb.block_type in ("TableCaption", "FigureCaption"):
                page_captions.setdefault(page_number, []).append(cb.raw.text)

        db.commit()

        # ── Stage 7: Table Parsing ────────────────────────────────────────────
        _set_progress(document_id, "running", "tables", "Parsing tables…")
        parsed_tables = parse_all_tables(pdf_path, document_id, page_captions)

        table_index: dict[str, str] = {}
        for pt in parsed_tables:
            # Associate table with nearest section
            candidates = [
                sd for sd in section_drafts
                if sd.start_page <= pt.start_page <= sd.end_page
            ]
            section_id = (
                max(candidates, key=lambda s: s.section_order).section_id
                if candidates else None
            )

            cells_json = [
                {
                    "row": c.row, "col": c.col, "text": c.text,
                    "is_header": c.is_header,
                    "x0": c.x0, "y0": c.y0, "x1": c.x1, "y1": c.y1,
                    "page": c.page_number,
                }
                for c in pt.cells
            ]

            tbl = DISTable(
                table_id=pt.table_id,
                document_id=document_id,
                section_id=section_id,
                caption=pt.caption,
                table_number=pt.table_number,
                row_count=pt.row_count,
                column_count=pt.column_count,
                start_page=pt.start_page,
                end_page=pt.end_page,
                x0=pt.x0, y0=pt.y0, x1=pt.x1, y1=pt.y1,
                cells_json=cells_json,
                confidence_score=pt.confidence,
                is_uncertain=pt.is_uncertain,
                uncertainty_reason=pt.uncertainty_reason,
            )
            db.merge(tbl)

            # Evidence anchor for the table bounding box
            anchor = EvidenceAnchor(
                anchor_id=_anchor_id(document_id, pt.start_page, pt.table_id),
                document_id=document_id,
                page_id=page_id_map.get(pt.start_page, ""),
                page_number=pt.start_page,
                x0=pt.x0, y0=pt.y0, x1=pt.x1, y1=pt.y1,
                linked_entity_id=pt.table_id,
                linked_entity_type="table",
                text_snippet=pt.caption,
            )
            db.merge(anchor)

            if pt.table_number:
                table_index[pt.table_number] = pt.table_id

        db.commit()

        # ── Stage 8: Cross-Reference Detection ───────────────────────────────
        _set_progress(document_id, "running", "references", "Detecting cross-references…")

        page_index = {pr.page_number: pr.page_id for pr in page_records}
        all_refs = []
        all_blocks_db = db.query(Block).filter(Block.document_id == document_id).all()

        for blk in all_blocks_db:
            if not blk.text_content:
                continue
            raw_refs = detect_references_in_block(document_id, blk.block_id, blk.text_content)
            all_refs.extend(raw_refs)

        resolved_refs = resolve_references(all_refs, table_index, section_index, page_index)
        for ref in resolved_refs:
            db.merge(CrossReference(
                ref_id=ref.ref_id,
                document_id=ref.document_id,
                source_block_id=ref.source_block_id,
                source_offset=ref.source_offset,
                ref_text=ref.ref_text,
                ref_type=ref.ref_type,
                target_id=ref.target_id,
                target_type=ref.target_type,
                is_resolved=ref.is_resolved,
            ))
        db.commit()

        # ── Stage 9: Finalization ─────────────────────────────────────────────
        _set_progress(document_id, "running", "finalizing", "Finalizing document record…")
        doc_db = db.get(Document, document_id)
        if doc_db:
            doc_db.status = "complete"
            doc_db.page_count = len(page_records)
        db.commit()

        _set_progress(document_id, "complete", "done",
                      f"Processed {len(page_records)} pages, "
                      f"{len(all_blocks_db)} blocks, "
                      f"{len(parsed_tables)} tables, "
                      f"{len(resolved_refs)} references")

    except Exception as e:
        _set_progress(document_id, "failed", "error", str(e))
        doc_db = db.get(Document, document_id)
        if doc_db:
            doc_db.status = "failed"
            doc_db.error_message = str(e)
        db.commit()
        raise
    finally:
        db.close()

    return document_id
