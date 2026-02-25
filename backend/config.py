"""
DIS Configuration — All thresholds and rules are explicit constants.
Changing behavior requires an intentional edit here (no hidden model states).
This file is version-controlled; each run references the config version.
"""

import os

DIS_VERSION = "1.0.0"

_BASE_DIR = "/tmp/storage" if os.getenv("VERCEL") or os.getenv("AWS_EXECUTION_ENV") else "storage"

# ── Storage ──────────────────────────────────────────────────────────────────
PDF_STORAGE_DIR = f"{_BASE_DIR}/pdfs"
DB_PATH = f"{_BASE_DIR}/dis.db"
PAGE_IMAGE_DIR = f"{_BASE_DIR}/page_images"

# ── Page Normalization ────────────────────────────────────────────────────────
PAGE_IMAGE_DPI = 150            # Render resolution for page thumbnails/overlays
PAGE_IMAGE_FORMAT = "PNG"

# ── Block Segmentation (XY-Cut) ───────────────────────────────────────────────
MIN_HORIZONTAL_GAP_PT = 8.0    # Minimum vertical whitespace (pts) to split blocks
MIN_VERTICAL_GAP_PT   = 6.0    # Minimum horizontal whitespace (pts) to split columns
WORD_MERGE_GAP_PT     = 3.0    # Words within this gap are merged into one span

# ── Block Classification ──────────────────────────────────────────────────────
HEADING_FONT_SIZE_RATIO   = 1.15   # Block font_size > median * ratio → heading candidate
HEADING_BOLD_SIZE_RATIO   = 1.05   # Bold + font_size > median * ratio → heading candidate
FOOTER_ZONE_RATIO         = 0.92   # y0/page_height > ratio → footer candidate
HEADER_ZONE_RATIO         = 0.08   # y1/page_height < ratio → running-header candidate
RUNNING_HEADER_MIN_PAGES  = 3      # Text must repeat on ≥ N pages to be deemed running header
FOOTNOTE_FONT_SIZE_RATIO  = 0.80   # font_size < median * ratio AND near bottom → footnote
LIST_BULLET_PATTERNS = [r"^\s*[•\-–—\*]\s+", r"^\s*\d+[.)]\s+", r"^\s*[a-z][.)]\s+"]
FIGURE_CAPTION_PREFIXES  = ["Figure", "Fig.", "Chart", "Graph", "Diagram", "Exhibit"]
TABLE_CAPTION_PREFIXES   = ["Table", "Tbl."]

# ── Heading Hierarchy ─────────────────────────────────────────────────────────
# Regex for numbered headings — group(1) counts dots → level
NUMBERED_HEADING_RE  = r"^(\d+(?:\.\d+)*)\s+\S"
ROMAN_HEADING_RE     = r"^(I{1,3}|IV|V|VI{0,3}|IX|X{1,3})[.\s]\s*\S"
MAX_HEADING_LEVEL    = 4

# ── Table Detection (pdfplumber) ──────────────────────────────────────────────
TABLE_SNAP_TOLERANCE        = 3    # pixel snap for grid-line detection
TABLE_JOIN_TOLERANCE        = 3
TABLE_EDGE_MIN_LENGTH       = 0.2  # minimum line length as fraction of page width/height
TABLE_CONTINUATION_HEADER   = True # detect repeated column headers on next page

# ── Cross-Reference Patterns ──────────────────────────────────────────────────
XREF_PATTERNS = [
    # (regex, ref_type, capture_group_for_target)
    (r"[Tt]able[s]?\s+(\d+[a-zA-Z]?)", "table", 1),
    (r"[Ff]igure[s]?\s+(\d+[a-zA-Z]?)", "figure", 1),
    (r"[Ff]ig\.\s+(\d+[a-zA-Z]?)", "figure", 1),
    (r"[Ss]ection[s]?\s+([\d.]+|[IVX]+)", "section", 1),
    (r"[Cc]hapter[s]?\s+(\d+|[IVX]+)", "section", 1),
    (r"\(see\s+([Tt]able|[Ff]igure|[Ss]ection)\s+([\d.IVX]+)\)", "see_ref", 2),
    (r"\[(\d+)\]", "citation", 1),
    (r"[Pp]age\s+(\d+)", "page", 1),
    (r"Appendix\s+([A-Z])", "appendix", 1),
]

# ── Uncertainty Thresholds ────────────────────────────────────────────────────
OCR_CONFIDENCE_THRESHOLD     = 0.85   # below → flag block as uncertain
HEADING_CONFIDENCE_THRESHOLD = 0.70   # below → flag heading as review_required
TABLE_CONFIDENCE_THRESHOLD   = 0.75   # below → flag table as review_required

# ── Idempotence ───────────────────────────────────────────────────────────────
# Blocks are sorted deterministically: top→bottom, then left→right
# IDs are derived from content position, NOT random UUIDs
BLOCK_SORT_PRIMARY   = "y0"    # Sort blocks by y0 (ascending)
BLOCK_SORT_SECONDARY = "x0"    # Then by x0 (ascending)
