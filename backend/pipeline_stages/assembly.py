"""
DIS Stage 6 — Section Assembly.

Groups classified blocks into a hierarchical section tree.
All logic is deterministic: no randomness, no ML inference.
Cross-page section continuity is handled explicitly.
"""
from __future__ import annotations
import hashlib
from dataclasses import dataclass, field
from typing import Optional

import config
from pipeline_stages.segmentation import ClassifiedBlock


@dataclass
class SectionDraft:
    section_id: str
    title: str
    level: int
    heading_number: Optional[str]
    header_block_ref: Optional[str]   # block_id of the heading block (set after DB persist)
    start_page: int
    end_page: int
    section_order: int
    parent_section_id: Optional[str]
    block_refs: list[str] = field(default_factory=list)   # block_ids in order
    continues_on_next_page: bool = False
    confidence: float = 1.0
    is_uncertain: bool = False
    uncertainty_reason: Optional[str] = None


def _make_section_id(document_id: str, order: int, title: str) -> str:
    """
    Deterministic section ID: derived from document + position + title.
    Same document + same run → identical IDs.
    """
    raw = f"{document_id}:sec{order:04d}:{title[:40]}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def assemble_sections(
    document_id: str,
    pages_classified: list[tuple[int, list[ClassifiedBlock]]],
    # [(page_number, classified_blocks_on_page), ...]
) -> list[SectionDraft]:
    """
    Stage 6: Walk all classified blocks in document order, build section tree.

    Rules (deterministic):
    1. A Heading block → close current section, open a new one.
    2. A lower-level heading → start a child section.
    3. A higher/equal-level heading → end child, continue at parent level.
    4. Non-heading block → append to the current section.
    5. Page ends without a new heading → set continues_on_next_page flag.
    """
    sections: list[SectionDraft] = []
    # Stack of open sections (innermost last)
    section_stack: list[SectionDraft] = []
    section_order = 0

    # Implicit root section (holds everything before first heading)
    root = SectionDraft(
        section_id=_make_section_id(document_id, 0, "__root__"),
        title="(Document Start)",
        level=0,
        heading_number=None,
        header_block_ref=None,
        start_page=1,
        end_page=1,
        section_order=0,
        parent_section_id=None,
    )
    section_stack.append(root)
    sections.append(root)

    def current() -> SectionDraft:
        return section_stack[-1]

    def parent_at_level(level: int) -> Optional[SectionDraft]:
        for sec in reversed(section_stack):
            if sec.level < level:
                return sec
        return None

    for page_number, blocks in pages_classified:
        for cb in blocks:
            # Skip non-content blocks
            if cb.block_type in ("RunningHeader", "Footer"):
                continue

            if cb.block_type == "Heading":
                new_level = cb.heading_level or 1

                # Pop stack until we find a section whose level < new_level
                while len(section_stack) > 1 and section_stack[-1].level >= new_level:
                    closed = section_stack.pop()
                    closed.end_page = page_number

                section_order += 1
                parent = current()

                new_sec = SectionDraft(
                    section_id=_make_section_id(document_id, section_order, cb.raw.text),
                    title=cb.raw.text.strip(),
                    level=new_level,
                    heading_number=cb.heading_number,
                    header_block_ref=None,  # Will be filled after block is persisted
                    start_page=page_number,
                    end_page=page_number,
                    section_order=section_order,
                    parent_section_id=parent.section_id,
                    confidence=cb.confidence,
                    is_uncertain=cb.is_uncertain,
                    uncertainty_reason=cb.uncertainty_reason,
                )
                section_stack.append(new_sec)
                sections.append(new_sec)

            else:
                # Append block reference to current section
                current().end_page = page_number
                # block_refs are filled in by the pipeline after block DB persist

        # End of page: check if next page continues the section
        if section_stack:
            current().continues_on_next_page = True  # Tentative; cleared if new heading found

    # Close all open sections at document end
    for sec in section_stack:
        if sections:
            sec.end_page = pages_classified[-1][0] if pages_classified else 1

    # Clear the continues_on_next_page flag for the last section
    if sections:
        sections[-1].continues_on_next_page = False

    return sections


def assign_block_to_section(
    block_id: str,
    block_type: str,
    page_number: int,
    sections: list[SectionDraft],
) -> Optional[str]:
    """
    Deterministically assign a block to its section by matching page range.
    Returns the section_id of the deepest (highest-level) section that
    contains this page and is not a Heading or RunningHeader.
    """
    if block_type in ("RunningHeader", "Footer"):
        return None

    candidates = [
        s for s in sections
        if s.start_page <= page_number <= s.end_page
    ]
    if not candidates:
        return None

    # Deepest (highest section_order) that contains the page
    return max(candidates, key=lambda s: s.section_order).section_id
