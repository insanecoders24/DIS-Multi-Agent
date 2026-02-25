"""
DIS Stage 1 & 2 — PDF Ingestion and Page Normalization.

Responsibilities:
- Compute SHA-256 checksum (chain-of-custody)
- Extract PDF metadata (title, author, creation date)
- Decompose PDF into pages
- Record page geometry (width, height, rotation)
- Render page thumbnails for the UI
- NO semantic inference happens here
"""
from __future__ import annotations
import hashlib
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

import config
from models.entities import Document, Page
from supabase_client import get_supabase


def compute_sha256(path: str) -> str:
    """Deterministic file checksum — the document's immutable identity."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_pdf_metadata(doc: fitz.Document) -> dict:
    """Extract metadata embedded in the PDF (no OCR, no inference)."""
    meta = doc.metadata or {}
    return {
        "title": meta.get("title") or None,
        "author": meta.get("author") or None,
        "creation_date": meta.get("creationDate") or None,
    }


def ingest_pdf(
    source_path: str,
    original_filename: str,
    parser_version: str = config.DIS_VERSION,
    config_id: str = "default",
) -> tuple[Document, list[Page]]:
    """
    Stage 1 + 2: Ingest a PDF file and extract page metadata.

    Returns (document_record, page_records).
    Does NOT persist — caller is responsible for DB commits.
    """
    # ── Stage 1: Ingest ──────────────────────────────────────────────────────
    sha256 = compute_sha256(source_path)
    document_id = sha256  # Stable identity = content hash

    # Archive the PDF (immutable copy)
    storage_dir = Path(config.PDF_STORAGE_DIR)
    storage_dir.mkdir(parents=True, exist_ok=True)
    stored_path = str(storage_dir / f"{document_id}.pdf")
    if not os.path.exists(stored_path):
        shutil.copy2(source_path, stored_path)

    supabase = get_supabase()
    if supabase:
        try:
            with open(stored_path, "rb") as f:
                supabase.storage.from_("documents").upload(
                    path=f"{document_id}.pdf",
                    file=f,
                    file_options={"content-type": "application/pdf"}
                )
        except Exception:
            pass  # Likely already exists or bucket missing

    file_size = os.path.getsize(source_path)

    # Open PDF
    pdf_doc = fitz.open(source_path)
    meta = _extract_pdf_metadata(pdf_doc)

    document = Document(
        document_id=document_id,
        source_path=original_filename,
        stored_path=stored_path,
        ingest_time=datetime.utcnow(),
        sha256_hash=sha256,
        file_size_bytes=file_size,
        title=meta["title"],
        author=meta["author"],
        creation_date=meta["creation_date"],
        page_count=len(pdf_doc),
        status="processing",
        parser_version=parser_version,
        config_id=config_id,
    )

    # ── Stage 2: Page Normalization ───────────────────────────────────────────
    pages: list[Page] = []
    image_dir = Path(config.PAGE_IMAGE_DIR) / document_id
    image_dir.mkdir(parents=True, exist_ok=True)

    for page_num in range(len(pdf_doc)):
        pg = pdf_doc[page_num]
        page_number = page_num + 1  # 1-based
        rotation = pg.rotation        # degrees, normalised by PyMuPDF
        rect = pg.rect

        # Render page thumbnail (stored for UI overlay)
        mat = fitz.Matrix(config.PAGE_IMAGE_DPI / 72, config.PAGE_IMAGE_DPI / 72)
        pix = pg.get_pixmap(matrix=mat, alpha=False)
        image_path = str(image_dir / f"p{page_number:04d}.png")
        pix.save(image_path)

        if supabase:
            try:
                with open(image_path, "rb") as f:
                    supabase.storage.from_("page-images").upload(
                        path=f"{document_id}/p{page_number:04d}.png",
                        file=f,
                        file_options={"content-type": "image/png"}
                    )
            except Exception:
                pass

        # Detect whether the page has embedded text
        text_sample = pg.get_text("text", clip=None).strip()
        has_text = len(text_sample) > 1  # lowered: even a single word means embedded text

        page_id = f"{document_id}:p{page_number}"
        pages.append(
            Page(
                page_id=page_id,
                document_id=document_id,
                page_number=page_number,
                width=rect.width,
                height=rect.height,
                rotation=rotation,
                normalized=True,
                image_path=image_path,
                has_text=has_text,
                ocr_applied=False,
            )
        )

    pdf_doc.close()
    return document, pages
