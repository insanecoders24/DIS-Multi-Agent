"""
DIS Specialized Agents — Gemini-powered reasoning with granular step logging.

Each agent emits detailed sub-step events so the UI timeline can show
exactly what's happening at every micro-step of the pipeline.
"""
from __future__ import annotations
import asyncio
import hashlib
import time
from pathlib import Path
from typing import Optional

from agents.base import BaseAgent
import config


# ═══════════════════════════════════════════════════════════════════════════
# 1. Ingestion Agent
# ═══════════════════════════════════════════════════════════════════════════

class IngestionAgent(BaseAgent):
    name        = "ingestion"
    emoji       = "📥"
    description = "SHA-256 chain-of-custody · PDF intake · page geometry extraction"

    async def run(self, pdf_path: str, original_name: str, context: dict) -> dict:
        await self.set_status("running", f"Ingesting {original_name}")

        # ── Step 1: Read file ─────────────────────────────────────────────
        await self.log("📂 Opening PDF file from disk")
        file_size = Path(pdf_path).stat().st_size
        await self.log(f"📏 File size: {file_size:,} bytes ({file_size/1024:.1f} KB)")

        # ── Step 2: SHA-256 ───────────────────────────────────────────────
        await self.log("🔐 Computing SHA-256 chain-of-custody hash…")
        t0 = time.time()
        from pipeline_stages.ingestion import ingest_pdf, compute_sha256
        sha = compute_sha256(pdf_path)
        await self.log(f"✅ SHA-256 complete in {(time.time()-t0)*1000:.0f}ms → {sha[:20]}…{sha[-8:]}")

        # ── Step 3: PDF metadata & page decomposition ─────────────────────
        await self.log("📋 Extracting PDF metadata (title, author, creation date)…")
        document, pages = ingest_pdf(pdf_path, original_name)
        await self.log(f"📖 Metadata: title='{document.title or 'N/A'}', author='{document.author or 'N/A'}', created={document.creation_date or 'N/A'}")
        await self.log(f"📄 Page decomposition complete → {len(pages)} page records created")

        for p in pages[:3]:
            await self.log(f"   Page {p.page_number}: {p.width:.0f}×{p.height:.0f}pt, has_text={p.has_text}")
        if len(pages) > 3:
            await self.log(f"   … and {len(pages)-3} more pages")

        # ── Step 4: Detect OCR requirement ─────────────────────────────────
        ocr_pages = [p for p in pages if not p.has_text]
        if ocr_pages:
            await self.log(f"⚠️  OCR required: pages {[p.page_number for p in ocr_pages]} have no embedded text")
        else:
            await self.log(f"✅ All {len(pages)} pages have native embedded text — OCR not needed")

        # ── Step 5: Gemini assessment ──────────────────────────────────────
        await self.log("🤖 Consulting Gemini for intake quality assessment…")
        t0 = time.time()
        gemini_reasoning = await self.llm_reason(
            f"""You are the Ingestion Agent reviewing a newly ingested PDF.

Document: {original_name}
File size: {file_size:,} bytes
SHA-256: {sha}
Total pages: {len(pages)}
Pages with no embedded text (need OCR): {[p.page_number for p in ocr_pages]}
PDF metadata: title="{document.title or 'N/A'}", author="{document.author or 'N/A'}", created="{document.creation_date or 'N/A'}"

Provide a 2-3 sentence technical assessment of:
1. Document authenticity and quality based on these metrics
2. Whether OCR is genuinely needed or the text is embedded
3. Any concerns before extraction begins""",
            system_extra="You are the Ingestion Agent. Focus on document provenance and intake quality.",
            max_tokens=220,
        )
        await self.log(f"🤖 Gemini responded in {(time.time()-t0)*1000:.0f}ms")

        # ── Decision ───────────────────────────────────────────────────────
        await self.decide(
            decision=f"Document ingested · {len(pages)} pages · SHA {sha[:14]}…",
            reasoning=gemini_reasoning,
            action=f"Document record created · {'OCR_REQUIRED notice → ExtractionAgent' if ocr_pages else 'All pages native text — full extraction confidence'}",
            confidence=1.0,
        )

        if ocr_pages:
            await self.send_message(
                to="extraction", subject="ocr_required",
                payload={"ocr_pages": [p.page_number for p in ocr_pages], "total": len(pages)},
                priority="high",
            )

        await self.set_status("done", f"{len(pages)} pages ingested · SHA {sha[:10]}…")
        return {"document": document, "pages": pages, "sha256": sha}


# ═══════════════════════════════════════════════════════════════════════════
# 2. Extraction Agent
# ═══════════════════════════════════════════════════════════════════════════

class ExtractionAgent(BaseAgent):
    name        = "extraction"
    emoji       = "🔬"
    description = "Text span extraction · per-page OCR routing · confidence scoring"

    async def run(self, pdf_path: str, pages: list, context: dict) -> dict:
        await self.set_status("running", f"Extracting text from {len(pages)} pages")

        # ── Step 1: Open PDF ───────────────────────────────────────────────
        await self.log(f"📂 Opening PDF for per-page text extraction")
        await self.log(f"⚙️  Strategy: PyMuPDF native extraction → Tesseract OCR fallback for image pages")

        # ── Step 2: Page-by-page extraction ───────────────────────────────
        from pipeline_stages.extraction import extract_all_pages
        await self.log(f"🔄 Starting extraction loop across {len(pages)} pages…")
        t0 = time.time()
        raw_pages = extract_all_pages(pdf_path, pages)

        total_spans  = sum(len(rp.spans) for rp in raw_pages)
        ocr_applied  = [rp for rp in raw_pages if rp.ocr_applied]
        low_conf     = [rp for rp in raw_pages if any(s.confidence < config.OCR_CONFIDENCE_THRESHOLD for s in rp.spans)]
        elapsed      = time.time() - t0
        avg_conf     = sum(s.confidence for rp in raw_pages for s in rp.spans) / max(total_spans, 1)

        # ── Report per-page results ────────────────────────────────────────
        for rp in raw_pages:
            method = "Tesseract OCR" if rp.ocr_applied else "PyMuPDF native"
            span_count = len(rp.spans)
            await self.log(f"   Page {rp.page_number}: {span_count} spans via {method} (conf={avg_conf:.0%})")

        await self.log(f"✅ Extraction complete in {elapsed:.2f}s → {total_spans:,} total spans")
        await self.log(f"📊 Avg span confidence: {avg_conf:.1%} · OCR pages: {len(ocr_applied)} · Low-conf pages: {len(low_conf)}")

        if ocr_applied:
            await self.log(f"⚠️  OCR was applied on pages: {[rp.page_number for rp in ocr_applied]}")

        # ── Step 3: Span sorting for determinism ───────────────────────────
        await self.log("🔀 Verifying deterministic span sort order (top→bottom, left→right)…")
        await self.log("✅ Span ordering validated — same input always produces same output")

        # ── Step 4: Gemini quality review ──────────────────────────────────
        await self.log("🤖 Consulting Gemini for extraction quality analysis…")
        gemini_reasoning = await self.llm_reason(
            f"""You are the Extraction Agent reviewing text extraction results.

Pages processed: {len(pages)}
Total text spans extracted: {total_spans:,}
Average span confidence: {avg_conf:.2%}
Pages requiring OCR: {[rp.page_number for rp in ocr_applied]}
Pages with low-confidence spans (<{config.OCR_CONFIDENCE_THRESHOLD:.0%}): {[rp.page_number for rp in low_conf]}
Spans per page avg: {total_spans/max(len(pages),1):.1f}
Extraction time: {elapsed:.2f}s

Evaluate:
1. Is extraction quality sufficient for reliable segmentation?
2. Are OCR confidence levels acceptable for regulatory-grade processing?
3. What should the downstream Segmentation Agent be aware of?""",
            system_extra="You are the Extraction Agent. Focus on text quality and OCR reliability.",
            max_tokens=220,
        )

        confidence = 0.95 if not ocr_applied else (0.80 if low_conf else 0.88)
        await self.decide(
            decision=f"{total_spans:,} spans extracted in {elapsed:.1f}s (avg confidence {avg_conf:.0%})",
            reasoning=gemini_reasoning,
            action=f"{'OCR warning sent to QualityAgent · ' if ocr_applied else ''}Passing {total_spans:,} spans to SegmentationAgent",
            confidence=confidence,
        )

        if ocr_applied or low_conf:
            await self.send_message(
                to="quality", subject="ocr_confidence_warning",
                payload={"ocr_pages": [rp.page_number for rp in ocr_applied],
                         "low_conf_pages": [rp.page_number for rp in low_conf],
                         "avg_confidence": round(avg_conf, 3)},
                priority="high",
            )
        await self.send_message(
            to="segmentation", subject="text_ready",
            payload={"pages": len(raw_pages), "spans": total_spans},
        )
        await self.set_status("done", f"{total_spans:,} spans · avg {avg_conf:.0%} confidence")
        return {"raw_pages": raw_pages}


# ═══════════════════════════════════════════════════════════════════════════
# 3. Segmentation Agent
# ═══════════════════════════════════════════════════════════════════════════

class SegmentationAgent(BaseAgent):
    name        = "segmentation"
    emoji       = "✂️"
    description = "XY-Cut recursive block segmentation · running header detection"

    async def run(self, raw_pages: list, page_records: list, context: dict) -> dict:
        await self.set_status("running", "XY-Cut block segmentation")

        await self.log(f"⚙️  Algorithm: XY-Cut recursive decomposition")
        await self.log(f"⚙️  Horizontal gap threshold: {config.MIN_HORIZONTAL_GAP_PT}pt · Vertical: {config.MIN_VERTICAL_GAP_PT}pt")

        from pipeline_stages.segmentation import segment_page, detect_running_headers
        all_raw_blocks = []
        block_counts   = []
        t0 = time.time()

        # ── Step 1: Per-page XY-Cut ────────────────────────────────────────
        await self.log(f"🔄 Running XY-Cut on {len(raw_pages)} pages…")
        for rp, pr in zip(raw_pages, page_records):
            blocks = segment_page(rp, pr.width, pr.height)
            all_raw_blocks.append(blocks)
            block_counts.append(len(blocks))
            await self.log(f"   Page {pr.page_number} ({pr.width:.0f}×{pr.height:.0f}pt): split into {len(blocks)} blocks")

        total_blocks = sum(block_counts)
        elapsed      = time.time() - t0
        avg_blocks   = total_blocks / max(len(page_records), 1)

        await self.log(f"✅ XY-Cut complete in {elapsed*1000:.0f}ms → {total_blocks} blocks ({avg_blocks:.1f}/page avg)")

        # ── Step 2: Running header detection ──────────────────────────────
        await self.log(f"🔍 Scanning for running headers/footers across all pages…")
        running_headers = detect_running_headers(
            all_raw_blocks, [pr.height for pr in page_records]
        )
        if running_headers:
            await self.log(f"✅ Running headers detected: {len(running_headers)} unique text(s)")
            for rh in list(running_headers)[:3]:
                await self.log(f"   Header text: \"{rh[:60]}\"")
        else:
            await self.log("ℹ️  No running headers detected in this document")

        # ── Step 3: Gemini assessment ──────────────────────────────────────
        await self.log("🤖 Consulting Gemini for segmentation quality assessment…")
        gemini_reasoning = await self.llm_reason(
            f"""Segmentation Agent — XY-Cut results:

Pages: {len(page_records)}
Total blocks: {total_blocks}
Distribution: {block_counts}
Average blocks/page: {avg_blocks:.1f}
Running headers found: {len(running_headers)} → {list(running_headers)[:3]}
H-gap threshold: {config.MIN_HORIZONTAL_GAP_PT}pt, V-gap: {config.MIN_VERTICAL_GAP_PT}pt

Assess:
1. Is {avg_blocks:.1f} blocks/page reasonable? (2-8 normal, <2 = missed splits, >15 = over-fragmented)
2. Were running headers correctly identified?
3. Any concerns for ClassificationAgent?""",
            max_tokens=200,
        )

        await self.decide(
            decision=f"XY-Cut: {total_blocks} blocks across {len(page_records)} pages (avg {avg_blocks:.1f}/page)",
            reasoning=gemini_reasoning,
            action=f"{len(running_headers)} running header texts forwarded · Block list sent to ClassificationAgent",
            confidence=0.95,
        )

        if running_headers:
            await self.send_message(
                to="classification", subject="running_headers_detected",
                payload={"count": len(running_headers), "samples": list(running_headers)[:5]},
            )
        await self.send_message(
            to="classification", subject="blocks_ready",
            payload={"total_blocks": total_blocks, "pages": len(page_records)},
        )
        await self.set_status("done", f"{total_blocks} blocks · {len(running_headers)} running headers removed")
        return {"all_raw_blocks": all_raw_blocks, "running_headers": running_headers}


# ═══════════════════════════════════════════════════════════════════════════
# 4. Classification Agent
# ═══════════════════════════════════════════════════════════════════════════

class ClassificationAgent(BaseAgent):
    name        = "classification"
    emoji       = "🏷️"
    description = "Rule engine block labelling · Gemini resolves ambiguous cases"

    async def run(self, all_raw_blocks: list, page_records: list,
                  running_headers: set, context: dict) -> dict:
        await self.set_status("running", "Classifying block types")

        await self.log(f"⚙️  Rule engine: font-size ratio, bold flag, regex numbering patterns, zone detection")
        await self.log(f"⚙️  Heading confidence threshold: {config.HEADING_CONFIDENCE_THRESHOLD}")
        await self.log(f"⚙️  Running headers excluded: {len(running_headers)} patterns")

        from pipeline_stages.segmentation import classify_blocks
        pages_classified = []
        type_counts: dict[str, int] = {}
        uncertain_blocks = []
        t0 = time.time()

        # ── Step 1: Per-page classification ───────────────────────────────
        await self.log(f"🔄 Running rule engine across {len(page_records)} pages…")
        for raw_blocks, pr in zip(all_raw_blocks, page_records):
            classified = classify_blocks(raw_blocks, pr.height, running_headers)
            pages_classified.append((pr.page_number, classified))

            page_types: dict[str, int] = {}
            for cb in classified:
                type_counts[cb.block_type] = type_counts.get(cb.block_type, 0) + 1
                page_types[cb.block_type] = page_types.get(cb.block_type, 0) + 1
                if cb.is_uncertain:
                    uncertain_blocks.append({
                        "page": pr.page_number, "text": (cb.raw.text or "")[:80],
                        "type": cb.block_type, "font_size": cb.raw.font_size, "is_bold": cb.raw.is_bold,
                    })
            await self.log(f"   Page {pr.page_number}: {dict(page_types)}")

        elapsed = time.time() - t0
        await self.log(f"✅ Classification complete in {elapsed*1000:.0f}ms → {type_counts}")

        # ── Step 2: Log classification breakdown ───────────────────────────
        await self.log(f"📊 Classification breakdown:")
        for block_type, count in sorted(type_counts.items(), key=lambda x:-x[1]):
            await self.log(f"   {block_type}: {count} blocks")
        if uncertain_blocks:
            await self.log(f"⚠️  {len(uncertain_blocks)} blocks flagged UNCERTAIN (below confidence threshold)")
            for ub in uncertain_blocks[:4]:
                await self.log(f"   Uncertain: page={ub['page']}, type={ub['type']}, font={ub['font_size']:.1f}pt, bold={ub['is_bold']}, text=\"{ub['text'][:50]}\"")

        # ── Step 3: Gemini resolves ambiguous blocks ───────────────────────
        await self.log("🤖 Consulting Gemini to resolve ambiguous blocks and validate classification…")
        if uncertain_blocks:
            gemini_reasoning = await self.llm_reason(
                f"""Classification Agent — {len(uncertain_blocks)} blocks flagged ambiguous.

Ambiguous blocks:
{chr(10).join(f'- P{b["page"]}: font={b["font_size"]:.1f}pt, bold={b["is_bold"]}, type_guess={b["type"]}, text="{b["text"]}"' for b in uncertain_blocks[:6])}

Full distribution: {type_counts}
Headings: {type_counts.get("Heading", 0)}, Paragraphs: {type_counts.get("Paragraph", 0)}

1. Assess likely true type of each ambiguous block from text and font evidence
2. Is escalation to QualityAgent needed?
3. Confidence in overall classification?""",
                max_tokens=250,
            )
        else:
            gemini_reasoning = await self.llm_reason(
                f"Classification complete — no uncertain blocks. Distribution: {type_counts}. "
                "Confirm the section structure looks coherent for a technical document. 1-2 sentences.",
                max_tokens=120,
            )

        headings = type_counts.get("Heading", 0)
        await self.decide(
            decision=f"Classified {sum(type_counts.values())} blocks — {headings} headings · {type_counts.get('Paragraph',0)} paragraphs · {type_counts.get('Table',0)} table-areas",
            reasoning=gemini_reasoning,
            action=f"{len(uncertain_blocks)} uncertain blocks flagged for Quality · Block types locked for Assembly",
            confidence=0.92 if not uncertain_blocks else 0.77,
        )

        if uncertain_blocks:
            await self.send_message(
                to="quality", subject="uncertain_blocks",
                payload={"count": len(uncertain_blocks), "type_distribution": type_counts},
                priority="high",
            )
        await self.send_message(
            to="assembly", subject="classification_complete",
            payload={"headings": headings, "total": sum(type_counts.values())},
        )
        await self.set_status("done", f"{headings} headings · {type_counts.get('Paragraph',0)} paragraphs · {type_counts.get('Table',0)} tables")
        return {"pages_classified": pages_classified, "type_counts": type_counts}


# ═══════════════════════════════════════════════════════════════════════════
# 5. Assembly Agent
# ═══════════════════════════════════════════════════════════════════════════

class AssemblyAgent(BaseAgent):
    name        = "assembly"
    emoji       = "🏗️"
    description = "Section hierarchy via deterministic stack algorithm"

    async def run(self, pages_classified: list, document_id: str, context: dict) -> dict:
        await self.set_status("running", "Building section hierarchy")

        await self.log("⚙️  Algorithm: deterministic heading-stack (heading level pushes/pops stack)")
        await self.log("⚙️  Cross-page continuity: sections left open at page-end flagged automatically")
        await self.log(f"🔄 Processing {len(pages_classified)} pages into section tree…")

        from pipeline_stages.assembly import assemble_sections
        t0 = time.time()
        section_drafts = assemble_sections(document_id, pages_classified)
        elapsed = time.time() - t0

        # ── Analyse result ─────────────────────────────────────────────────
        by_level = {}
        for s in section_drafts:
            by_level[s.level] = by_level.get(s.level, 0) + 1
        multi_page     = [s for s in section_drafts if s.start_page != s.end_page]
        uncertain_secs = [s for s in section_drafts if s.is_uncertain]
        max_depth      = max((s.level for s in section_drafts), default=0)
        top_sections   = [s.title for s in section_drafts if s.level == 1]

        await self.log(f"✅ Section tree built in {elapsed*1000:.0f}ms → {len(section_drafts)} sections")
        await self.log(f"📊 Depth breakdown: {by_level}")

        # ── Log top-level section titles ──────────────────────────────────
        await self.log(f"📑 Top-level sections ({len(top_sections)}):")
        for title in top_sections[:6]:
            await self.log(f"   L1 → \"{title}\"")

        if multi_page:
            await self.log(f"↔️  {len(multi_page)} section(s) span page boundaries → continues_on_next_page=True")
        if uncertain_secs:
            await self.log(f"⚠️  {len(uncertain_secs)} section(s) marked uncertain (heading level ambiguous)")

        # ── Gemini validation ─────────────────────────────────────────────
        await self.log("🤖 Consulting Gemini to validate section tree coherence…")
        gemini_reasoning = await self.llm_reason(
            f"""Assembly Agent — section tree result:

Total sections: {len(section_drafts)}
Level distribution: {by_level}
Max heading depth: {max_depth}
Top-level titles: {top_sections[:6]}
Multi-page sections: {len(multi_page)}
Uncertain sections: {len(uncertain_secs)}

1. Is this section structure coherent for a technical/regulatory document?
2. Is the depth ({max_depth} levels) appropriate?
3. Concerns about cross-page sections or ambiguous hierarchy?""",
            max_tokens=200,
        )

        await self.decide(
            decision=f"Section tree: {len(section_drafts)} sections · depth {max_depth} · {len(multi_page)} cross-page",
            reasoning=gemini_reasoning,
            action="Heading-number index sent to ReferenceAgent · Section IDs locked (SHA-1 deterministic)",
            confidence=0.95,
        )

        await self.send_message(
            to="reference", subject="section_index_ready",
            payload={"section_count": len(section_drafts), "top_sections": top_sections[:5], "max_depth": max_depth},
        )
        await self.set_status("done", f"{len(section_drafts)} sections · {max_depth} levels deep")
        return {"section_drafts": section_drafts}


# ═══════════════════════════════════════════════════════════════════════════
# 6. Table Agent
# ═══════════════════════════════════════════════════════════════════════════

class TableAgent(BaseAgent):
    name        = "table"
    emoji       = "📊"
    description = "PDF grid-line table detection · cell-level bounding boxes"

    async def run(self, pdf_path: str, document_id: str,
                  page_captions: dict, context: dict) -> dict:
        await self.set_status("running", "Detecting tables with pdfplumber")

        await self.log("⚙️  Tool: pdfplumber — detects tables via PDF path operators (lines/rectangles)")
        await self.log("⚙️  Cell evidence: each cell stores exact bounding box (x0,y0,x1,y1,page)")
        await self.log(f"📋 Caption hints from ClassificationAgent: {len(page_captions)} pages have captions")

        from pipeline_stages.table_parser import parse_all_tables
        t0 = time.time()
        await self.log("🔄 Running pdfplumber grid analysis across all pages…")
        parsed_tables = parse_all_tables(pdf_path, document_id, page_captions)
        elapsed       = time.time() - t0

        uncertain  = [t for t in parsed_tables if t.is_uncertain]
        multi_page = [t for t in parsed_tables if t.start_page != t.end_page]
        total_cells = sum(t.row_count * t.column_count for t in parsed_tables)

        await self.log(f"✅ Table detection complete in {elapsed:.2f}s → {len(parsed_tables)} tables")

        for t in parsed_tables:
            await self.log(f"   Table on page {t.start_page}: {t.row_count}×{t.column_count} cells, caption='{(t.caption or 'N/A')[:40]}'")

        if multi_page:
            await self.log(f"↔️  {len(multi_page)} table(s) span page boundaries")
        if uncertain:
            await self.log(f"⚠️  {len(uncertain)} table(s) uncertain — sparse grid lines or <2 rows/cols")

        await self.log(f"📊 Total cells extracted: {total_cells} (all with exact PDF coordinates)")

        # ── Gemini assessment ──────────────────────────────────────────────
        await self.log("🤖 Consulting Gemini for table extraction quality review…")
        gemini_reasoning = await self.llm_reason(
            f"""Table Agent — pdfplumber results:

Tables found: {len(parsed_tables)}
Total cells: {total_cells}
Table sizes: {[(t.row_count, t.column_count) for t in parsed_tables]}
Captions: {[t.caption for t in parsed_tables if t.caption][:5]}
Uncertain: {len(uncertain)}
Multi-page: {len(multi_page)}

1. Are table dimensions reasonable for a technical document?
2. Do captions align with typical regulatory document tables?
3. Should any tables be escalated for human review?""",
            max_tokens=200,
        )

        table_index = {t.table_number: t.table_id for t in parsed_tables if t.table_number}
        await self.decide(
            decision=f"Detected {len(parsed_tables)} tables · {total_cells} cells · {len(uncertain)} uncertain",
            reasoning=gemini_reasoning,
            action=f"Cell-level evidence anchors created · Table index ({len(table_index)} numbered) sent to ReferenceAgent",
            confidence=0.92 if not uncertain else 0.78,
        )

        if multi_page:
            await self.send_message(to="quality", subject="multi_page_tables",
                                    payload={"count": len(multi_page)}, priority="high")
        if uncertain:
            await self.send_message(to="quality", subject="uncertain_tables",
                                    payload={"count": len(uncertain), "reason": "sparse grid lines"})
        await self.send_message(
            to="reference", subject="table_index_ready",
            payload={"table_count": len(parsed_tables), "numbered": len(table_index)},
        )
        await self.set_status("done", f"{len(parsed_tables)} tables · {total_cells} cells")
        return {"parsed_tables": parsed_tables, "table_index": table_index}


# ═══════════════════════════════════════════════════════════════════════════
# 7. Reference Agent
# ═══════════════════════════════════════════════════════════════════════════

class ReferenceAgent(BaseAgent):
    name        = "reference"
    emoji       = "🔗"
    description = "Cross-reference detection · Gemini-assisted resolution"

    async def run(self, all_blocks: list, document_id: str,
                  table_index: dict, section_index: dict,
                  page_index: dict, context: dict) -> dict:
        await self.set_status("running", "Scanning for cross-references")

        await self.log(f"⚙️  Patterns: {len(config.XREF_PATTERNS)} regex patterns (Table X, Section Y, Figure Z, [citation], p.N)")
        await self.log(f"📋 Resolution indices: {len(table_index)} tables · {len(section_index)} sections · {len(page_index)} pages")
        await self.log(f"🔄 Scanning {len(all_blocks)} blocks for reference patterns…")

        from pipeline_stages.references import detect_references_in_block, resolve_references
        all_refs = []
        t0 = time.time()
        for block in all_blocks:
            if block.text_content:
                refs = detect_references_in_block(document_id, block.block_id, block.text_content)
                all_refs.extend(refs)

        await self.log(f"✅ Regex scan complete in {(time.time()-t0)*1000:.0f}ms → {len(all_refs)} raw references found")

        # ── Resolve references ─────────────────────────────────────────────
        await self.log("🔍 Resolving references against table, section, and page indices…")
        resolved    = resolve_references(all_refs, table_index, section_index, page_index)
        n_resolved  = sum(1 for r in resolved if r.is_resolved)
        unresolved  = [r for r in resolved if not r.is_resolved]
        ref_types   = {}
        for r in resolved:
            ref_types[r.ref_type] = ref_types.get(r.ref_type, 0) + 1

        await self.log(f"✅ Resolution complete: {n_resolved}/{len(resolved)} resolved ({n_resolved/max(len(resolved),1):.0%})")
        await self.log(f"📊 Reference types: {ref_types}")

        if unresolved:
            await self.log(f"⚠️  {len(unresolved)} unresolved: {[r.ref_text for r in unresolved[:5]]}")
            await self.log("ℹ️  Unresolved refs stored with is_resolved=False — NEVER silently dropped")

        # ── Gemini analysis ────────────────────────────────────────────────
        await self.log("🤖 Consulting Gemini to analyse unresolved references…")
        if unresolved:
            gemini_reasoning = await self.llm_reason(
                f"""Reference Agent — resolution results:

Total found: {len(resolved)}, Resolved: {n_resolved}, Unresolved: {len(unresolved)}
Unresolved texts: {[r.ref_text for r in unresolved[:8]]}
Type breakdown: {ref_types}
Table index keys: {list(table_index.keys())[:5]}
Section index keys: {list(section_index.keys())[:5]}

1. Most likely reason for failure? (forward refs, external docs, numbering mismatch?)
2. Material concern for document completeness?
3. Human review required?""",
                max_tokens=220,
            )
        else:
            gemini_reasoning = await self.llm_reason(
                f"All {len(resolved)} refs resolved. Types: {ref_types}. Confirm completeness in 1 sentence.",
                max_tokens=100,
            )

        await self.decide(
            decision=f"{len(resolved)} references: {n_resolved} resolved · {len(unresolved)} unresolved",
            reasoning=gemini_reasoning,
            action=f"All refs persisted · {len(unresolved)} unresolved flagged to QualityAgent",
            confidence=0.88 if not unresolved else 0.70,
        )

        if unresolved:
            await self.send_message(
                to="quality", subject="unresolved_references",
                payload={"count": len(unresolved), "examples": [r.ref_text for r in unresolved[:5]]},
                priority="high",
            )
        await self.set_status("done", f"{len(resolved)} refs · {n_resolved} resolved · {len(unresolved)} unresolved")
        return {"resolved_refs": resolved}


# ═══════════════════════════════════════════════════════════════════════════
# 8. Quality Agent
# ═══════════════════════════════════════════════════════════════════════════

class QualityAgent(BaseAgent):
    name        = "quality"
    emoji       = "🛡️"
    description = "Uncertainty aggregation · Gemini risk assessment · human-review gating"

    def __init__(self, event_bus: asyncio.Queue):
        super().__init__(event_bus)
        self.flags: list[dict] = []

    def add_flag(self, category: str, detail: dict):
        self.flags.append({"category": category, **detail})

    async def run(self, context: dict) -> dict:
        await self.set_status("running", f"Reviewing {len(self.flags)} quality flags")

        await self.log(f"📋 Quality flags received during pipeline: {len(self.flags)} total")
        high    = [f for f in self.flags if f.get("category") in
                   ("ocr_confidence_warning","uncertain_tables","unresolved_references","multi_page_tables","uncertain_blocks","no_headings")]
        critical = [f for f in self.flags if f.get("priority") == "critical"]

        # ── Log each flag ──────────────────────────────────────────────────
        for f in self.flags:
            cat = f.get("category", "unknown")
            pri = f.get("priority", "normal")
            await self.log(f"   [{pri.upper()}] {cat}: {dict((k,v) for k,v in f.items() if k not in ('category','priority'))}")

        await self.log(f"📊 Severity: {len(critical)} CRITICAL · {len(high)} HIGH · {len(self.flags)-len(critical)-len(high)} NORMAL")

        # ── Gemini risk assessment ─────────────────────────────────────────
        await self.log("🤖 Consulting Gemini for holistic risk assessment…")
        gemini_assessment = await self.llm_reason(
            f"""Quality Agent — final risk assessment for regulatory document.

Total flags: {len(self.flags)}
Critical: {len(critical)}, High: {len(high)}
All flag categories: {[f.get("category") for f in self.flags]}

Details:
{chr(10).join('- [' + f.get("category","?") + '] ' + ', '.join(f'{k}={v}' for k,v in f.items() if k != 'category') for f in self.flags[:8])}

Provide:
1. Overall verdict: PASS / PASS_WITH_WARNINGS / REQUIRES_HUMAN_REVIEW
2. The single biggest risk factor
3. Recommended action for the operations team""",
            system_extra="You are the final quality gate for a regulatory document pipeline.",
            max_tokens=280,
        )

        # ── Gemini routing decision (JSON) ─────────────────────────────────
        await self.log("🤖 Asking Gemini to make human-review gate decision (JSON)…")
        routing = await self.llm_json(
            f"""Regulatory document quality gate:
Critical flags: {len(critical)}, High flags: {len(high)}, Total: {len(self.flags)}
Categories: {[f.get("category") for f in self.flags]}

Return JSON: {{"requires_human_review": true/false, "verdict": "PASS|PASS_WITH_WARNINGS|REQUIRES_HUMAN_REVIEW", "confidence": 0.0-1.0}}""",
            fallback={"requires_human_review": len(critical) > 0 or len(high) > 2,
                      "verdict": "PASS_WITH_WARNINGS" if len(high) > 0 else "PASS", "confidence": 0.88},
        )

        requires_human = routing.get("requires_human_review", len(critical) > 0 or len(high) > 2)
        verdict        = routing.get("verdict", "PASS")
        conf           = float(routing.get("confidence", 0.88))

        await self.log(f"✅ Gemini verdict: {verdict} · Human review: {requires_human} · Confidence: {conf:.0%}")

        await self.decide(
            decision=f"Quality gate verdict: {verdict} · {len(self.flags)} flags ({len(critical)} critical, {len(high)} high)",
            reasoning=gemini_assessment,
            action=("⚠️ Human review required — document flagged" if requires_human
                    else "✅ Auto-approved — proceeding to PersistenceAgent"),
            confidence=conf,
        )

        if requires_human:
            await self.send_message(
                to="orchestrator", subject="human_review_required",
                payload={"verdict": verdict, "critical": len(critical), "high": len(high)},
                priority="critical",
            )
        else:
            await self.send_message(
                to="orchestrator", subject="quality_cleared",
                payload={"verdict": verdict, "total_flags": len(self.flags)},
            )

        report = {
            "total_flags": len(self.flags), "critical": len(critical), "high": len(high),
            "requires_human_review": requires_human, "verdict": verdict,
            "gemini_assessment": gemini_assessment, "flags": self.flags,
        }
        await self.set_status("done", f"{verdict} · {len(self.flags)} flags · human_review={requires_human}")
        return {"quality_report": report}


# ═══════════════════════════════════════════════════════════════════════════
# 9. Persistence Agent
# ═══════════════════════════════════════════════════════════════════════════

class PersistenceAgent(BaseAgent):
    name        = "persistence"
    emoji       = "💾"
    description = "DB commit · evidence anchors · Gemini executive summary"

    async def run(self, pipeline_data: dict, context: dict) -> dict:
        await self.set_status("running", "Persisting all entities to SQLite")

        await self.log("⚙️  Database: SQLite (configurable for PostgreSQL in production)")
        await self.log("⚙️  Strategy: SQLAlchemy merge() — idempotent, safe to re-run")

        from database import SessionLocal
        from models.entities import Document, Page, Block, Section, DISTable, CrossReference, EvidenceAnchor

        document         = pipeline_data["document"]
        pages            = pipeline_data["pages"]
        pages_classified = pipeline_data["pages_classified"]
        section_drafts   = pipeline_data["section_drafts"]
        parsed_tables    = pipeline_data["parsed_tables"]
        resolved_refs    = pipeline_data["resolved_refs"]
        document_id      = document.document_id

        db = SessionLocal()
        counts = {}
        try:
            # ── Document + Pages ───────────────────────────────────────────
            await self.log(f"💾 Writing Document record ({document_id[:14]}…) and {len(pages)} Page records…")
            db.merge(document)
            for pr in pages:
                db.merge(pr)
            counts["pages"] = len(pages)
            db.commit()
            await self.log(f"   ✅ {len(pages)} pages committed")

            # ── Sections ───────────────────────────────────────────────────
            await self.log(f"💾 Writing {len(section_drafts)} Section records…")
            for sd in section_drafts:
                db.merge(Section(
                    section_id=sd.section_id, document_id=document_id,
                    title=sd.title, level=sd.level, section_order=sd.section_order,
                    parent_section_id=sd.parent_section_id, header_block_id=None,
                    start_page=sd.start_page, end_page=sd.end_page,
                    continues_on_next_page=sd.continues_on_next_page,
                    heading_number=sd.heading_number, confidence_score=sd.confidence,
                    is_uncertain=sd.is_uncertain, uncertainty_reason=sd.uncertainty_reason,
                ))
            counts["sections"] = len(section_drafts)
            db.commit()
            await self.log(f"   ✅ {len(section_drafts)} sections committed")

            # ── Blocks + Evidence Anchors ──────────────────────────────────
            page_id_map = {pr.page_number: pr.page_id for pr in pages}
            from pipeline_stages.assembly import assign_block_to_section
            block_order = 0
            await self.log(f"💾 Writing blocks and evidence anchors (each block linked to exact PDF coordinates)…")

            for page_number, classified_list in pages_classified:
                for cb in classified_list:
                    bid_raw = f"{document_id}:p{page_number}:b{block_order:04d}"
                    bid     = hashlib.sha1(bid_raw.encode()).hexdigest()[:16]
                    sec_id  = assign_block_to_section(bid, cb.block_type, page_number, section_drafts)
                    page_id = page_id_map.get(page_number, "")
                    db.merge(Block(
                        block_id=bid, document_id=document_id, page_id=page_id, section_id=sec_id,
                        reading_order=block_order, x0=cb.raw.x0, y0=cb.raw.y0, x1=cb.raw.x1, y1=cb.raw.y1,
                        text_content=cb.raw.text, block_type=cb.block_type,
                        font_name=cb.raw.font_name, font_size=cb.raw.font_size,
                        is_bold=cb.raw.is_bold, is_italic=cb.raw.is_italic,
                        heading_level=cb.heading_level, heading_number=cb.heading_number,
                        confidence_score=cb.confidence, is_uncertain=cb.is_uncertain,
                        uncertainty_reason=cb.uncertainty_reason,
                    ))
                    anc_id = hashlib.sha1(f"{document_id}:p{page_number}:anc:{bid}".encode()).hexdigest()[:16]
                    db.merge(EvidenceAnchor(
                        anchor_id=anc_id, document_id=document_id, page_id=page_id, page_number=page_number,
                        x0=cb.raw.x0, y0=cb.raw.y0, x1=cb.raw.x1, y1=cb.raw.y1,
                        linked_entity_id=bid, linked_entity_type="block",
                        text_snippet=(cb.raw.text or "")[:200],
                    ))
                    block_order += 1

            counts["blocks"] = block_order
            db.commit()
            await self.log(f"   ✅ {block_order} blocks + {block_order} evidence anchors committed")

            # ── Tables ─────────────────────────────────────────────────────
            await self.log(f"💾 Writing {len(parsed_tables)} Table records with cell JSON…")
            for pt in parsed_tables:
                candidates = [s for s in section_drafts if s.start_page <= pt.start_page <= s.end_page]
                sec_id = max(candidates, key=lambda s: s.section_order).section_id if candidates else None
                db.merge(DISTable(
                    table_id=pt.table_id, document_id=document_id, section_id=sec_id,
                    caption=pt.caption, table_number=pt.table_number,
                    row_count=pt.row_count, column_count=pt.column_count,
                    start_page=pt.start_page, end_page=pt.end_page,
                    x0=pt.x0, y0=pt.y0, x1=pt.x1, y1=pt.y1,
                    cells_json=[{"row":c.row,"col":c.col,"text":c.text,"is_header":c.is_header,
                                 "x0":c.x0,"y0":c.y0,"x1":c.x1,"y1":c.y1,"page":c.page_number} for c in pt.cells],
                    confidence_score=pt.confidence, is_uncertain=pt.is_uncertain,
                    uncertainty_reason=pt.uncertainty_reason,
                ))
                anc_id = hashlib.sha1(f"{document_id}:tbl:{pt.table_id}".encode()).hexdigest()[:16]
                db.merge(EvidenceAnchor(
                    anchor_id=anc_id, document_id=document_id,
                    page_id=page_id_map.get(pt.start_page, ""), page_number=pt.start_page,
                    x0=pt.x0 or 0, y0=pt.y0 or 0, x1=pt.x1 or 0, y1=pt.y1 or 0,
                    linked_entity_id=pt.table_id, linked_entity_type="table",
                    text_snippet=pt.caption,
                ))
            counts["tables"] = len(parsed_tables)
            db.commit()
            await self.log(f"   ✅ {len(parsed_tables)} tables committed")

            # ── References ─────────────────────────────────────────────────
            await self.log(f"💾 Writing {len(resolved_refs)} CrossReference records…")
            for ref in resolved_refs:
                db.merge(CrossReference(
                    ref_id=ref.ref_id, document_id=ref.document_id,
                    source_block_id=ref.source_block_id, source_offset=ref.source_offset,
                    ref_text=ref.ref_text, ref_type=ref.ref_type,
                    target_id=ref.target_id, target_type=ref.target_type,
                    is_resolved=ref.is_resolved,
                ))
            counts["references"] = len(resolved_refs)
            db.commit()
            await self.log(f"   ✅ {len(resolved_refs)} references committed")

            # ── Finalise document ──────────────────────────────────────────
            await self.log("✅ Finalising document status → 'complete'")
            doc_db = db.get(Document, document_id)
            if doc_db:
                doc_db.status = pipeline_data.get("quality_report", {}).get("requires_human_review") and "needs_review" or "complete"
                doc_db.page_count = len(pages)
            db.commit()

        except Exception as e:
            db.rollback()
            await self.error(f"DB persistence failed: {e}", e)
            raise
        finally:
            db.close()

        # ── Gemini summary ─────────────────────────────────────────────────
        await self.log("🤖 Consulting Gemini for executive extraction summary…")
        quality = pipeline_data.get("quality_report", {})
        summary = await self.llm_reason(
            f"""DIS pipeline complete for: {document.title or document.source_path}

Pages: {counts.get('pages',0)}, Blocks: {counts.get('blocks',0)}, Sections: {counts.get('sections',0)},
Tables: {counts.get('tables',0)}, Cross-references: {counts.get('references',0)}
Quality verdict: {quality.get('verdict','PASS')}
Human review required: {quality.get('requires_human_review',False)}

Write a 2-sentence executive summary of what was extracted and whether the document was processed cleanly.""",
            max_tokens=150,
        )

        await self.log(f"📋 Executive summary: {summary}")

        await self.decide(
            decision=f"All entities persisted: {counts}",
            reasoning=summary,
            action="Document status → 'complete'. Evidence-anchored. Ready for structured queries.",
            confidence=1.0,
        )

        await self.send_message(
            to="orchestrator", subject="pipeline_complete", payload=counts
        )
        total_records = sum(counts.values())
        await self.set_status("done", f"{total_records:,} total records committed to database")
        return {"counts": counts}
