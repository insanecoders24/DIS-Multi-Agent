"""
DIS Entity Models — SQLAlchemy ORM (clean, tested relationships).

Every entity has:
  - A stable, deterministic ID (derived from content position, not random)
  - A confidence_score / is_uncertain flag for uncertainty propagation
  - Version metadata (parser_version, config_id) for reproducibility audit
"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, String, Text, JSON,
)
from sqlalchemy.orm import relationship
from database import Base


# ─────────────────────────────────────────────────────────────────────────────
# 1. Document
# ─────────────────────────────────────────────────────────────────────────────

class Document(Base):
    __tablename__ = "documents"

    document_id     = Column(String, primary_key=True)
    source_path     = Column(String, nullable=False)
    stored_path     = Column(String, nullable=False)
    ingest_time     = Column(DateTime, default=datetime.utcnow)
    sha256_hash     = Column(String, nullable=False)
    file_size_bytes = Column(Integer)
    title           = Column(String, nullable=True)
    author          = Column(String, nullable=True)
    creation_date   = Column(String, nullable=True)
    page_count      = Column(Integer, default=0)
    status          = Column(String, default="pending")
    error_message   = Column(Text, nullable=True)
    parser_version  = Column(String, nullable=False)
    config_id       = Column(String, nullable=False)

    pages      = relationship("Page",           back_populates="document", cascade="all,delete-orphan")
    sections   = relationship("Section",        back_populates="document", cascade="all,delete-orphan")
    tables     = relationship("DISTable",       back_populates="document", cascade="all,delete-orphan")
    references = relationship("CrossReference", back_populates="document", cascade="all,delete-orphan")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Page
# ─────────────────────────────────────────────────────────────────────────────

class Page(Base):
    __tablename__ = "pages"

    page_id     = Column(String, primary_key=True)
    document_id = Column(String, ForeignKey("documents.document_id"), nullable=False)
    page_number = Column(Integer, nullable=False)
    width       = Column(Float, nullable=False)
    height      = Column(Float, nullable=False)
    rotation    = Column(Integer, default=0)
    normalized  = Column(Boolean, default=True)
    image_path  = Column(String, nullable=True)
    has_text    = Column(Boolean, default=True)
    ocr_applied = Column(Boolean, default=False)

    document = relationship("Document", back_populates="pages")
    blocks   = relationship("Block", back_populates="page", cascade="all,delete-orphan")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Block
# ─────────────────────────────────────────────────────────────────────────────

class Block(Base):
    __tablename__ = "blocks"

    block_id      = Column(String, primary_key=True)
    document_id   = Column(String, nullable=False)
    page_id       = Column(String, ForeignKey("pages.page_id"), nullable=False)
    section_id    = Column(String, ForeignKey("sections.section_id"), nullable=True)
    reading_order = Column(Integer, nullable=False)

    x0 = Column(Float, nullable=False)
    y0 = Column(Float, nullable=False)
    x1 = Column(Float, nullable=False)
    y1 = Column(Float, nullable=False)

    text_content = Column(Text, default="")
    block_type   = Column(String, default="Paragraph")

    font_name = Column(String, nullable=True)
    font_size = Column(Float, nullable=True)
    is_bold   = Column(Boolean, default=False)
    is_italic = Column(Boolean, default=False)

    heading_level  = Column(Integer, nullable=True)
    heading_number = Column(String, nullable=True)

    confidence_score   = Column(Float, default=1.0)
    is_uncertain       = Column(Boolean, default=False)
    uncertainty_reason = Column(String, nullable=True)

    page    = relationship("Page",    back_populates="blocks")
    section = relationship("Section", back_populates="blocks", foreign_keys=[section_id])


# ─────────────────────────────────────────────────────────────────────────────
# 4. Section
# ─────────────────────────────────────────────────────────────────────────────

class Section(Base):
    __tablename__ = "sections"

    section_id             = Column(String, primary_key=True)
    document_id            = Column(String, ForeignKey("documents.document_id"), nullable=False)
    title                  = Column(String, default="")
    level                  = Column(Integer, default=1)
    section_order          = Column(Integer, nullable=False)
    parent_section_id      = Column(String, ForeignKey("sections.section_id"), nullable=True)
    header_block_id        = Column(String, nullable=True)
    start_page             = Column(Integer, nullable=False)
    end_page               = Column(Integer, nullable=False)
    continues_on_next_page = Column(Boolean, default=False)
    heading_number         = Column(String, nullable=True)

    confidence_score   = Column(Float, default=1.0)
    is_uncertain       = Column(Boolean, default=False)
    uncertainty_reason = Column(String, nullable=True)

    document       = relationship("Document", back_populates="sections")
    blocks         = relationship("Block",    back_populates="section", foreign_keys="Block.section_id")
    child_sections = relationship("Section",  foreign_keys=[parent_section_id])
    tables         = relationship("DISTable", back_populates="section")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Table
# ─────────────────────────────────────────────────────────────────────────────

class DISTable(Base):
    __tablename__ = "dis_tables"

    table_id        = Column(String, primary_key=True)
    document_id     = Column(String, ForeignKey("documents.document_id"), nullable=False)
    section_id      = Column(String, ForeignKey("sections.section_id"), nullable=True)
    caption         = Column(String, nullable=True)
    table_number    = Column(String, nullable=True)
    row_count       = Column(Integer, default=0)
    column_count    = Column(Integer, default=0)
    start_page      = Column(Integer, nullable=False)
    end_page        = Column(Integer, nullable=False)
    continuation_id = Column(String, nullable=True)

    x0 = Column(Float, nullable=True)
    y0 = Column(Float, nullable=True)
    x1 = Column(Float, nullable=True)
    y1 = Column(Float, nullable=True)

    cells_json = Column(JSON, default=list)

    confidence_score   = Column(Float, default=1.0)
    is_uncertain       = Column(Boolean, default=False)
    uncertainty_reason = Column(String, nullable=True)

    document = relationship("Document", back_populates="tables")
    section  = relationship("Section",  back_populates="tables")


# ─────────────────────────────────────────────────────────────────────────────
# 6. CrossReference
# ─────────────────────────────────────────────────────────────────────────────

class CrossReference(Base):
    __tablename__ = "cross_references"

    ref_id          = Column(String, primary_key=True)
    document_id     = Column(String, ForeignKey("documents.document_id"), nullable=False)
    source_block_id = Column(String, nullable=False)
    source_offset   = Column(Integer, default=0)
    ref_text        = Column(String, nullable=False)
    ref_type        = Column(String, nullable=False)
    target_id       = Column(String, nullable=True)
    target_type     = Column(String, nullable=True)
    is_resolved     = Column(Boolean, default=False)

    document = relationship("Document", back_populates="references")


# ─────────────────────────────────────────────────────────────────────────────
# 7. EvidenceAnchor — standalone (polymorphic entity_id, no ORM FK join)
# ─────────────────────────────────────────────────────────────────────────────

class EvidenceAnchor(Base):
    """
    Maps a structured entity back to exact PDF coordinates.
    linked_entity_id is polymorphic (block_id OR table_id) so no ORM FK is used;
    queries are done directly by linked_entity_id lookup.
    """
    __tablename__ = "evidence_anchors"

    anchor_id          = Column(String, primary_key=True)
    document_id        = Column(String, nullable=False)
    page_id            = Column(String, ForeignKey("pages.page_id"), nullable=False)
    page_number        = Column(Integer, nullable=False)

    x0 = Column(Float, nullable=False)
    y0 = Column(Float, nullable=False)
    x1 = Column(Float, nullable=False)
    y1 = Column(Float, nullable=False)

    linked_entity_id   = Column(String, nullable=False)  # block_id / table_id
    linked_entity_type = Column(String, nullable=False)  # "block" | "table" | "cell"
    text_snippet       = Column(Text, nullable=True)
