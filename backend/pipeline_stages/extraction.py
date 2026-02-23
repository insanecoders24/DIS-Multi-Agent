"""
DIS Stage 3 — Text Extraction.

Extracts words/spans from each page as the raw text layer.
For text-based PDFs: PyMuPDF direct extraction (precise, coordinates included).
For image-only pages: flag for OCR (pytesseract if available, else mark as needs_ocr).

This stage adds NO structural interpretaton — it only surfaces text + coordinates.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import fitz
import config


@dataclass
class RawSpan:
    """One atomic span of text from a page (word or logical run)."""
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    font_name: str = ""
    font_size: float = 10.0
    is_bold: bool = False
    is_italic: bool = False
    flags: int = 0           # raw PyMuPDF flags field
    confidence: float = 1.0  # 1.0 for native text; OCR-derived otherwise
    origin: str = "native"   # "native" | "ocr"


@dataclass
class RawPageText:
    """All raw text spans for a single page."""
    page_id: str
    page_number: int
    spans: list[RawSpan] = field(default_factory=list)
    has_text: bool = True
    ocr_applied: bool = False
    warnings: list[str] = field(default_factory=list)


def _pymupdf_flags(flags: int) -> tuple[bool, bool]:
    """Decode PyMuPDF font flags → (is_bold, is_italic)."""
    is_bold   = bool(flags & (1 << 4))  # bit 4 = bold
    is_italic = bool(flags & (1 << 1))  # bit 1 = italic
    return is_bold, is_italic


def extract_page_text(pdf_path: str, page_record) -> RawPageText:
    """
    Extract raw text spans from one page using PyMuPDF.

    Returns a RawPageText with all spans sorted deterministically:
    top-to-bottom (y0 ascending), left-to-right (x0 ascending).
    This ordering is the foundation for stable block IDs downstream.
    """
    result = RawPageText(
        page_id=page_record.page_id,
        page_number=page_record.page_number,
        has_text=page_record.has_text,
    )

    pdf_doc = fitz.open(pdf_path)
    pg = pdf_doc[page_record.page_number - 1]

    if page_record.has_text:
        # Native text extraction — returns dict with blocks→lines→spans
        raw = pg.get_text("rawdict", flags=fitz.TEXT_PRESERVE_LIGATURES | fitz.TEXT_PRESERVE_WHITESPACE)
        for blk in raw.get("blocks", []):
            if blk.get("type") != 0:  # skip image blocks at this stage
                continue
            for line in blk.get("lines", []):
                for sp in line.get("spans", []):
                    text = sp.get("text", "").strip()
                    if not text:
                        continue
                    bbox = sp.get("bbox", (0, 0, 0, 0))
                    flags = sp.get("flags", 0)
                    is_bold, is_italic = _pymupdf_flags(flags)
                    font_name = sp.get("font", "")
                    font_size = round(sp.get("size", 10.0), 2)

                    result.spans.append(
                        RawSpan(
                            text=text,
                            x0=bbox[0], y0=bbox[1], x1=bbox[2], y1=bbox[3],
                            font_name=font_name,
                            font_size=font_size,
                            is_bold=is_bold,
                            is_italic=is_italic,
                            flags=flags,
                            confidence=1.0,
                            origin="native",
                        )
                    )
    else:
        # Image-only page: try pytesseract if available
        result.ocr_applied = True
        try:
            import pytesseract
            from PIL import Image
            pix = pg.get_pixmap(matrix=fitz.Matrix(2, 2))
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            ocr_data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, lang="eng")
            # Scale factor: PyMuPDF internal coords → screen coords back to PDF pts
            scale = pg.rect.width / pix.width
            for i, word in enumerate(ocr_data["text"]):
                word = str(word).strip()
                if not word:
                    continue
                conf = float(ocr_data["conf"][i]) / 100.0
                if conf < 0:
                    conf = 0.0
                x0 = ocr_data["left"][i] * scale
                y0 = ocr_data["top"][i] * scale
                x1 = x0 + ocr_data["width"][i] * scale
                y1 = y0 + ocr_data["height"][i] * scale
                result.spans.append(
                    RawSpan(
                        text=word, x0=x0, y0=y0, x1=x1, y1=y1,
                        confidence=conf,
                        origin="ocr",
                    )
                )
        except ImportError:
            result.warnings.append(
                f"Page {page_record.page_number} has no embedded text and pytesseract is not installed. "
                "Mark as needs_ocr."
            )
        except Exception as e:
            result.warnings.append(f"OCR failed on page {page_record.page_number}: {e}")

    pdf_doc.close()

    # ── Deterministic sort: top → bottom, left → right ───────────────────────
    result.spans.sort(key=lambda s: (round(s.y0, 1), round(s.x0, 1)))
    return result


def extract_all_pages(pdf_path: str, page_records: list) -> list[RawPageText]:
    """Extract raw text for every page in reading order."""
    return [extract_page_text(pdf_path, pr) for pr in page_records]
