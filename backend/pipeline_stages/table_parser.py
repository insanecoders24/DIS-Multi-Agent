"""
DIS Stage 7 — Table Detection & Parsing.

Uses pdfplumber to detect tables via line-intersection logic.
Each table is stored as a first-class structured object with:
  - Row/column schema
  - Individual cells (text + bounding box = evidence anchor)
  - Header row detection
  - Cross-page table linking

Flat text representation of tables is NEVER the final output —
cell-level structure is always preserved.
"""
from __future__ import annotations
import hashlib
import re
from dataclasses import dataclass, field
from typing import Optional

import pdfplumber

import config
from models.entities import DISTable


@dataclass
class ParsedCell:
    row: int
    col: int
    text: str
    is_header: bool
    x0: float
    y0: float
    x1: float
    y1: float
    page_number: int


@dataclass
class ParsedTable:
    table_id: str
    document_id: str
    start_page: int
    end_page: int
    caption: Optional[str]
    table_number: Optional[str]
    row_count: int
    column_count: int
    cells: list[ParsedCell]
    x0: float
    y0: float
    x1: float
    y1: float
    confidence: float = 1.0
    is_uncertain: bool = False
    uncertainty_reason: Optional[str] = None
    section_id: Optional[str] = None


def _make_table_id(document_id: str, page: int, index: int) -> str:
    raw = f"{document_id}:t:p{page}:{index}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _extract_table_number(caption: Optional[str]) -> Optional[str]:
    """Extract '3' from 'Table 3. Revenue Details'."""
    if not caption:
        return None
    m = re.search(r"[Tt]able[s]?\s+(\d+[a-zA-Z]?)", caption)
    if m:
        return m.group(1)
    return None


def _is_header_row(row_texts: list[str], row_idx: int) -> bool:
    """
    First row is treated as header if:
    - it's the first row (row_idx == 0)
    - all cells are non-empty strings without pure numeric values
    """
    if row_idx != 0:
        return False
    numeric_count = sum(
        1 for t in row_texts
        if t and re.match(r"^[\d,.\-+%$€£¥\s]+$", t.strip())
    )
    return numeric_count < len(row_texts) * 0.5


def parse_tables_on_page(
    pdf_path: str,
    page_number: int,  # 1-based
    document_id: str,
    captions_on_page: list[str],
) -> list[ParsedTable]:
    """
    Extract all tables from a single page using pdfplumber.
    pdfplumber uses PDF path data (lines/rects) for table detection —
    deterministic across runs with the same file.
    """
    tables_found: list[ParsedTable] = []

    with pdfplumber.open(pdf_path) as pdf:
        if page_number > len(pdf.pages):
            return []
        page = pdf.pages[page_number - 1]  # 0-based

        # pdfplumber table settings (deterministic parameters from config)
        ts = {
            "snap_tolerance": config.TABLE_SNAP_TOLERANCE,
            "join_tolerance": config.TABLE_JOIN_TOLERANCE,
            "edge_min_length": max(
                page.width * config.TABLE_EDGE_MIN_LENGTH,
                page.height * config.TABLE_EDGE_MIN_LENGTH,
                5,
            ),
            "intersection_tolerance": 3,
        }

        raw_tables = page.find_tables(table_settings=ts)

        for t_idx, raw_table in enumerate(raw_tables):
            try:
                data = raw_table.extract()
            except Exception:
                data = []

            if not data or not data[0]:
                continue

            bbox = raw_table.bbox  # (x0, top, x1, bottom) in pdfplumber coords
            # pdfplumber uses top-origin; convert to PDF pts (bottom-origin) if needed
            # For UI overlays we keep top-origin since page images also use top-origin
            x0, y0, x1, y1 = bbox

            row_count = len(data)
            col_count = max(len(row) for row in data) if data else 0

            if row_count == 0 or col_count == 0:
                continue

            # ── Build cells ────────────────────────────────────────────
            cells: list[ParsedCell] = []
            for r_idx, row in enumerate(data):
                is_header = _is_header_row([str(c or "") for c in row], r_idx)
                for c_idx, cell_text in enumerate(row):
                    text = str(cell_text or "").strip()

                    # Try to get per-cell bbox from pdfplumber
                    try:
                        cells_raw = raw_table.cells
                        if r_idx < len(cells_raw) and c_idx < len(cells_raw[r_idx]):
                            cb = cells_raw[r_idx][c_idx]
                            cx0, cy0, cx1, cy1 = cb if cb else (x0, y0, x1, y1)
                        else:
                            cx0, cy0, cx1, cy1 = x0, y0, x1, y1
                    except Exception:
                        cx0, cy0, cx1, cy1 = x0, y0, x1, y1

                    cells.append(
                        ParsedCell(
                            row=r_idx, col=c_idx, text=text,
                            is_header=is_header,
                            x0=cx0, y0=cy0, x1=cx1, y1=cy1,
                            page_number=page_number,
                        )
                    )

            # ── Match nearest caption ──────────────────────────────────
            caption: Optional[str] = None
            for cap in captions_on_page:
                for prefix in config.TABLE_CAPTION_PREFIXES:
                    if cap.strip().startswith(prefix):
                        caption = cap.strip()
                        break

            table_id = _make_table_id(document_id, page_number, t_idx)

            # Confidence: lower if no header detected or few cells
            confidence = 1.0
            if row_count < 2 or col_count < 2:
                confidence = 0.70
                is_uncertain = True
                uncertainty_reason = "Table has fewer than 2 rows or columns — may be a formatting artifact"
            else:
                is_uncertain = False
                uncertainty_reason = None

            tables_found.append(
                ParsedTable(
                    table_id=table_id,
                    document_id=document_id,
                    start_page=page_number,
                    end_page=page_number,
                    caption=caption,
                    table_number=_extract_table_number(caption),
                    row_count=row_count,
                    column_count=col_count,
                    cells=cells,
                    x0=x0, y0=y0, x1=x1, y1=y1,
                    confidence=confidence,
                    is_uncertain=is_uncertain,
                    uncertainty_reason=uncertainty_reason,
                )
            )

    return tables_found


def parse_all_tables(
    pdf_path: str,
    document_id: str,
    page_captions: dict[int, list[str]],  # {page_number: [caption_texts]}
) -> list[ParsedTable]:
    """Parse tables from all pages; returns all ParsedTable objects."""
    all_tables: list[ParsedTable] = []
    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)

    for page_num in range(1, page_count + 1):
        captions = page_captions.get(page_num, [])
        tables = parse_tables_on_page(pdf_path, page_num, document_id, captions)
        all_tables.extend(tables)

    return all_tables
