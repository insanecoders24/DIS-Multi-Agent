"""
DIS Stage 8 — Cross-Reference Detection & Resolution.

Scans all block text for internal references (Table X, Section Y, Figure Z etc.)
using deterministic regex patterns from config.
Resolves each reference to the matching entity ID where possible.
Unresolved references are stored with is_resolved=False — never silently dropped.
"""
from __future__ import annotations
import hashlib
import re
from dataclasses import dataclass
from typing import Optional

import config


@dataclass
class DetectedRef:
    ref_id: str
    document_id: str
    source_block_id: str
    source_offset: int           # character position in block text
    ref_text: str                # raw matched string e.g. "Table 3"
    ref_type: str                # "table" | "section" | "figure" | "citation" | "page"
    target_id: Optional[str]     # resolved entity ID or None
    target_type: Optional[str]   # "dis_table" | "section" | "block" | "page"
    is_resolved: bool


def _make_ref_id(document_id: str, block_id: str, offset: int, ref_text: str) -> str:
    raw = f"{document_id}:{block_id}:{offset}:{ref_text}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def detect_references_in_block(
    document_id: str,
    block_id: str,
    text: str,
) -> list[DetectedRef]:
    """
    Apply all XREF_PATTERNS to block text.
    Each match becomes a DetectedRef with is_resolved=False (resolved later).
    """
    refs: list[DetectedRef] = []
    for pattern, ref_type, capture_group in config.XREF_PATTERNS:
        for m in re.finditer(pattern, text):
            matched_text = m.group(0)
            offset = m.start()
            ref_id = _make_ref_id(document_id, block_id, offset, matched_text)
            refs.append(
                DetectedRef(
                    ref_id=ref_id,
                    document_id=document_id,
                    source_block_id=block_id,
                    source_offset=offset,
                    ref_text=matched_text,
                    ref_type=ref_type,
                    target_id=None,
                    target_type=None,
                    is_resolved=False,
                )
            )
    return refs


def resolve_references(
    refs: list[DetectedRef],
    table_index: dict[str, str],    # table_number → table_id
    section_index: dict[str, str],  # heading_number_or_title → section_id
    page_index: dict[int, str],     # page_number → page_id
) -> list[DetectedRef]:
    """
    Attempt to resolve each reference to a known entity ID.

    Resolution strategy:
    - "Table X" → look up table_number in table_index
    - "Section X" / "Chapter X" → look up in section_index
    - "Figure X" → look up in table_index (figures may be stored as tables)
    - "page X" → look up page number
    - "[X]" citation → cannot auto-resolve (mark as unresolvable)

    If a match is found → is_resolved=True, target_id set.
    If not found → is_resolved=False, target_id=None. NEVER silently omit.
    """
    resolved: list[DetectedRef] = []
    for ref in refs:
        r = DetectedRef(**ref.__dict__)  # copy

        if ref.ref_type == "table":
            m = re.search(r"(\d+[a-zA-Z]?)", ref.ref_text)
            if m:
                table_num = m.group(1)
                tid = table_index.get(table_num)
                if tid:
                    r.target_id = tid
                    r.target_type = "dis_table"
                    r.is_resolved = True

        elif ref.ref_type == "section":
            m = re.search(r"([\d.]+|[IVX]+)", ref.ref_text)
            if m:
                key = m.group(1)
                sid = section_index.get(key)
                if sid:
                    r.target_id = sid
                    r.target_type = "section"
                    r.is_resolved = True

        elif ref.ref_type == "page":
            m = re.search(r"(\d+)", ref.ref_text)
            if m:
                pnum = int(m.group(1))
                pid = page_index.get(pnum)
                if pid:
                    r.target_id = pid
                    r.target_type = "page"
                    r.is_resolved = True

        elif ref.ref_type == "citation":
            # [1], [2] etc. — bibliography entries, cannot auto-resolve
            r.is_resolved = False

        resolved.append(r)
    return resolved
