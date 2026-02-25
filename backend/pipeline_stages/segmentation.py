"""
DIS Stage 4 — Block Segmentation (XY-Cut Algorithm).
DIS Stage 5 — Block Classification (Rule-Based).

Stage 4: Groups raw text spans into spatially coherent blocks using a
         recursive XY-Cut decomposition. Fully deterministic.

Stage 5: Labels each block with a semantic type (Heading, Paragraph, Table,
         Figure, Footer, RunningHeader, Footnote, ListItem, etc.)
         using explicit rule-based heuristics. No ML models.
"""
from __future__ import annotations
import re
import statistics
from dataclasses import dataclass, field
from typing import Optional

import config
from pipeline_stages.extraction import RawSpan, RawPageText


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 4 — Block Segmentation
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RawBlock:
    """A spatially grouped set of spans forming one content region."""
    spans: list[RawSpan]
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    text: str = ""
    # Typography (from dominant span)
    font_name: str = ""
    font_size: float = 10.0
    is_bold: bool = False
    is_italic: bool = False
    avg_confidence: float = 1.0


def _bounding_box(spans: list[RawSpan]) -> tuple[float, float, float, float]:
    x0 = min(s.x0 for s in spans)
    y0 = min(s.y0 for s in spans)
    x1 = max(s.x1 for s in spans)
    y1 = max(s.y1 for s in spans)
    return x0, y0, x1, y1


def _build_block(spans: list[RawSpan]) -> RawBlock:
    """Create a RawBlock from a list of spans, computing aggregate fields."""
    spans_sorted = sorted(spans, key=lambda s: (round(s.y0, 1), round(s.x0, 1)))
    x0, y0, x1, y1 = _bounding_box(spans_sorted)

    # Text: join spans in reading order, inserting spaces where needed
    text_parts: list[str] = []
    prev_x1: Optional[float] = None
    prev_y0: Optional[float] = None
    for sp in spans_sorted:
        if prev_y0 is not None and (sp.y0 - prev_y0) > sp.font_size * 0.8:
            text_parts.append("\n")
        elif prev_x1 is not None and (sp.x0 - prev_x1) > 2.0:
            text_parts.append(" ")
        text_parts.append(sp.text)
        prev_x1 = sp.x1
        prev_y0 = sp.y0
    text = "".join(text_parts).strip()

    # Dominant font (most common font_size)
    if spans_sorted:
        dominant = max(spans_sorted, key=lambda s: (s.x1 - s.x0))
        font_name  = dominant.font_name
        font_size  = dominant.font_size
        is_bold    = dominant.is_bold
        is_italic  = dominant.is_italic
    else:
        font_name, font_size, is_bold, is_italic = "", 10.0, False, False

    avg_conf = statistics.mean(s.confidence for s in spans) if spans else 1.0

    return RawBlock(
        spans=spans_sorted,
        x0=x0, y0=y0, x1=x1, y1=y1,
        text=text,
        font_name=font_name,
        font_size=font_size,
        is_bold=is_bold,
        is_italic=is_italic,
        avg_confidence=avg_conf,
    )


def _xy_cut(spans: list[RawSpan], page_width: float, page_height: float) -> list[list[RawSpan]]:
    """
    Recursive XY-Cut: split spans by largest whitespace gaps.
    Returns a list of span-groups, each representing one block region.
    """
    if not spans:
        return []
    if len(spans) == 1:
        return [spans]

    spans = sorted(spans, key=lambda s: (round(s.y0, 1), round(s.x0, 1)))

    # ── Try horizontal cut (y-axis gap between lines) ──────────────────────
    best_h_gap = 0.0
    best_h_cut = 0.0
    ys = sorted(set(round(s.y0, 1) for s in spans))
    for i in range(len(ys) - 1):
        gap = ys[i + 1] - ys[i]
        # Find max y1 from spans at or above ys[i]
        max_y1 = max(
            (s.y1 for s in spans if round(s.y0, 1) <= ys[i]),
            default=ys[i],
        )
        whitespace = ys[i + 1] - max_y1
        if whitespace > best_h_gap:
            best_h_gap = whitespace
            best_h_cut = (max_y1 + ys[i + 1]) / 2

    # ── Try vertical cut (x-axis gap between columns) ─────────────────────
    best_v_gap = 0.0
    best_v_cut = 0.0
    xs = sorted(set(round(s.x0, 1) for s in spans))
    for i in range(len(xs) - 1):
        max_x1 = max(
            (s.x1 for s in spans if round(s.x0, 1) <= xs[i]),
            default=xs[i],
        )
        whitespace = xs[i + 1] - max_x1
        if whitespace > best_v_gap:
            best_v_gap = whitespace
            best_v_cut = (max_x1 + xs[i + 1]) / 2

    # ── Apply the larger gap cut ───────────────────────────────────────────
    if best_h_gap >= config.MIN_HORIZONTAL_GAP_PT and best_h_gap >= best_v_gap:
        top    = [s for s in spans if s.y1 <= best_h_cut + 1]
        bottom = [s for s in spans if s.y0 >= best_h_cut - 1]
        if not top or not bottom:
            return [spans]
        return _xy_cut(top, page_width, page_height) + _xy_cut(bottom, page_width, page_height)

    if best_v_gap >= config.MIN_VERTICAL_GAP_PT:
        left  = [s for s in spans if s.x1 <= best_v_cut + 1]
        right = [s for s in spans if s.x0 >= best_v_cut - 1]
        if not left or not right:
            return [spans]
        return _xy_cut(left, page_width, page_height) + _xy_cut(right, page_width, page_height)

    return [spans]


def segment_page(raw_page: RawPageText, page_width: float, page_height: float) -> list[RawBlock]:
    """
    Stage 4: Convert raw page spans → RawBlocks using XY-Cut.
    Output is deterministically ordered (top → bottom, left → right).
    """
    if not raw_page.spans:
        return []

    groups = _xy_cut(raw_page.spans, page_width, page_height)
    blocks = [_build_block(grp) for grp in groups if grp]

    # Final deterministic sort of blocks
    blocks.sort(key=lambda b: (round(b.y0, 0), round(b.x0, 0)))
    return blocks


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 5 — Block Classification
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ClassifiedBlock:
    raw: RawBlock
    block_type: str = "Paragraph"
    heading_level: Optional[int] = None
    heading_number: Optional[str] = None
    confidence: float = 1.0
    is_uncertain: bool = False
    uncertainty_reason: Optional[str] = None


def _median_font_size(blocks: list[RawBlock]) -> float:
    sizes = [b.font_size for b in blocks if b.font_size > 0]
    return statistics.median(sizes) if sizes else 10.0


def _heading_level_from_text(text: str) -> tuple[Optional[int], Optional[str]]:
    """Parse heading level from numbering scheme. Returns (level, number_str)."""
    text = text.strip()
    # Numeric: "2.3.1 Title…"
    m = re.match(config.NUMBERED_HEADING_RE, text)
    if m:
        number_str = m.group(1)
        level = number_str.count(".") + 1
        return min(level, config.MAX_HEADING_LEVEL), number_str

    # Roman numeral: "III. Title…"
    m = re.match(config.ROMAN_HEADING_RE, text, re.IGNORECASE)
    if m:
        return 1, m.group(1)

    return None, None


def _is_list_item(text: str) -> bool:
    for pat in config.LIST_BULLET_PATTERNS:
        if re.match(pat, text):
            return True
    return False


def _caption_type(text: str) -> Optional[str]:
    t = text.strip()
    for prefix in config.FIGURE_CAPTION_PREFIXES:
        if t.startswith(prefix):
            return "FigureCaption"
    for prefix in config.TABLE_CAPTION_PREFIXES:
        if t.startswith(prefix):
            return "TableCaption"
    return None


def classify_blocks(
    blocks: list[RawBlock],
    page_height: float,
    running_header_texts: set[str],
) -> list[ClassifiedBlock]:
    """
    Stage 5: Apply deterministic rules to label every block.

    Rules (in priority order):
    1. Running header zone + repeated text → RunningHeader
    2. Footer zone → Footer
    3. Footnote zone + small font → Footnote
    4. Figure/Table caption prefix → FigureCaption / TableCaption
    5. List bullet pattern → ListItem
    6. Font size / bold → Heading (with hierarchy)
    7. Default → Paragraph
    """
    median_fs = _median_font_size(blocks)
    results: list[ClassifiedBlock] = []

    for blk in blocks:
        cb = ClassifiedBlock(raw=blk, confidence=1.0)
        text = blk.text.strip()

        # ── Running header (repeated across pages) ────────────────────────
        if blk.y0 < page_height * config.HEADER_ZONE_RATIO:
            if text in running_header_texts:
                cb.block_type = "RunningHeader"
                cb.confidence = 0.95
                results.append(cb)
                continue

        # ── Footer ────────────────────────────────────────────────────────
        if blk.y0 > page_height * config.FOOTER_ZONE_RATIO:
            cb.block_type = "Footer"
            cb.confidence = 0.90
            results.append(cb)
            continue

        # ── Footnote (small font near bottom) ─────────────────────────────
        if (blk.font_size < median_fs * config.FOOTNOTE_FONT_SIZE_RATIO
                and blk.y0 > page_height * 0.75):
            cb.block_type = "Footnote"
            cb.confidence = 0.80
            cb.is_uncertain = cb.confidence < config.HEADING_CONFIDENCE_THRESHOLD
            results.append(cb)
            continue

        # ── Figure / Table caption ────────────────────────────────────────
        cap_type = _caption_type(text)
        if cap_type:
            cb.block_type = cap_type
            cb.confidence = 0.95
            results.append(cb)
            continue

        # ── List item ─────────────────────────────────────────────────────
        if _is_list_item(text):
            cb.block_type = "ListItem"
            cb.confidence = 0.90
            results.append(cb)
            continue

        # ── Heading detection ─────────────────────────────────────────────
        is_large = blk.font_size >= median_fs * config.HEADING_FONT_SIZE_RATIO
        is_bold_large = blk.is_bold and blk.font_size >= median_fs * config.HEADING_BOLD_SIZE_RATIO
        is_short = len(text) < 200   # headings are typically short

        if (is_large or is_bold_large) and is_short:
            level, number_str = _heading_level_from_text(text)

            if level is None:
                # Font-size-based level (relative ranking)
                if blk.font_size >= median_fs * 1.5:
                    level = 1
                elif blk.font_size >= median_fs * 1.25:
                    level = 2
                else:
                    level = 3

            conf = min(1.0, (blk.font_size / median_fs) * 0.7 + (0.3 if number_str else 0.0))
            cb.block_type = "Heading"
            cb.heading_level = level
            cb.heading_number = number_str
            cb.confidence = round(conf, 2)
            cb.is_uncertain = conf < config.HEADING_CONFIDENCE_THRESHOLD
            if cb.is_uncertain:
                cb.uncertainty_reason = "Heading detected by font size only — confirm manually"
            results.append(cb)
            continue

        # ── Default ───────────────────────────────────────────────────────
        cb.block_type = "Paragraph"

        # Low OCR confidence → flag
        if blk.avg_confidence < config.OCR_CONFIDENCE_THRESHOLD:
            cb.is_uncertain = True
            cb.uncertainty_reason = f"Low OCR confidence: {blk.avg_confidence:.2f}"
            cb.confidence = blk.avg_confidence

        results.append(cb)

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Utility: Detect running headers/footers across pages
# ─────────────────────────────────────────────────────────────────────────────

def detect_running_headers(all_page_blocks: list[list[RawBlock]], page_heights: list[float]) -> set[str]:
    """
    Any text that appears verbatim in the header zone of
    RUNNING_HEADER_MIN_PAGES or more pages is a running header.
    """
    from collections import Counter
    header_texts = Counter()
    for blocks, ph in zip(all_page_blocks, page_heights):
        for blk in blocks:
            if blk.y0 < ph * config.HEADER_ZONE_RATIO and blk.text.strip():
                header_texts[blk.text.strip()] += 1
    return {
        text for text, count in header_texts.items()
        if count >= config.RUNNING_HEADER_MIN_PAGES
    }
