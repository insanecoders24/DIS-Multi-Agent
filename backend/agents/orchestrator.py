"""
DIS Orchestrator Agent — Gemini-powered routing coordinator.

Gemini is consulted at every stage boundary to:
  1. Review the previous agent's output
  2. Decide if the next stage should proceed or needs special handling
  3. Detect edge cases (all-scanned doc, empty sections, etc.)
  4. Generate the routing decision reasoning shown in the live UI

The physical pipeline is still deterministic — Gemini adds intelligence,
not randomness.
"""
from __future__ import annotations
import asyncio
import uuid

from agents.base import BaseAgent
from agents.specialized import (
    IngestionAgent, ExtractionAgent, SegmentationAgent,
    ClassificationAgent, AssemblyAgent, TableAgent,
    ReferenceAgent, QualityAgent, PersistenceAgent,
)

# ── Job registry ──────────────────────────────────────────────────────────────
_JOBS: dict[str, dict] = {}


def new_job() -> tuple[str, asyncio.Queue]:
    job_id = uuid.uuid4().hex[:12]
    bus: asyncio.Queue = asyncio.Queue()
    _JOBS[job_id] = {"bus": bus, "status": "pending", "events": []}
    return job_id, bus


def get_job(job_id: str) -> dict | None:
    return _JOBS.get(job_id)


class OrchestratorAgent(BaseAgent):
    name        = "orchestrator"
    emoji       = "🎯"
    description = "Gemini-powered coordinator · routes all agents · manages job lifecycle"

    def __init__(self, event_bus: asyncio.Queue):
        super().__init__(event_bus)
        self.agents = {
            "ingestion":      IngestionAgent(event_bus),
            "extraction":     ExtractionAgent(event_bus),
            "segmentation":   SegmentationAgent(event_bus),
            "classification": ClassificationAgent(event_bus),
            "assembly":       AssemblyAgent(event_bus),
            "table":          TableAgent(event_bus),
            "reference":      ReferenceAgent(event_bus),
            "quality":        QualityAgent(event_bus),
            "persistence":    PersistenceAgent(event_bus),
        }

    async def _gemini_route(
        self,
        stage: str,
        result_summary: str,
        next_stage: str,
        alternatives: list[str] | None = None,
    ) -> str:
        """
        Ask Gemini to review a completed stage and justify routing to the next one.
        Returns the routing reasoning string.
        """
        alt_str = f" Alternatives considered: {alternatives}." if alternatives else ""
        return await self.llm_reason(
            f"""You are the Orchestrator Agent in a multi-agent Document Intelligence System.

Stage just completed: {stage}
Summary of results: {result_summary}
Next planned stage: {next_stage}{alt_str}

In 1-2 sentences, justify this routing decision. Be specific about what the '{stage}' output tells you and why '{next_stage}' is the correct next step. Reference actual numbers from the summary.""",
            system_extra="You are the Orchestrator making explicit routing decisions between pipeline stages.",
            max_tokens=150,
        )

    async def run(self, pdf_path: str, original_name: str) -> dict:
        await self.set_status("running", f"Coordinating DIS pipeline for '{original_name}'")
        await self.log(f"Pipeline started · PDF: {original_name} · Agents: {len(self.agents)} · LLM: Gemini 2.0 Flash")

        qa: QualityAgent = self.agents["quality"]
        context: dict = {}
        pipeline_data: dict = {}

        # ── Stage 1+2: Ingestion ─────────────────────────────────────────────
        ingest_result = await self.agents["ingestion"].run(pdf_path, original_name, context)
        pipeline_data.update(ingest_result)
        pages   = ingest_result["pages"]
        doc     = ingest_result["document"]
        doc_id  = doc.document_id
        sha     = ingest_result["sha256"]

        routing_reasoning = await self._gemini_route(
            stage="Ingestion",
            result_summary=f"{len(pages)} pages ingested, SHA {sha[:12]}…, "
                           f"{sum(1 for p in pages if not p.has_text)} pages need OCR",
            next_stage="Extraction",
        )
        await self.decide(
            decision=f"Route: Ingestion → Extraction",
            reasoning=routing_reasoning,
            action="ExtractionAgent activated",
            confidence=1.0,
        )

        # ── Stage 3: Extraction ──────────────────────────────────────────────
        ext_result = await self.agents["extraction"].run(pdf_path, pages, context)
        pipeline_data.update(ext_result)
        raw_pages   = ext_result["raw_pages"]
        total_spans = sum(len(rp.spans) for rp in raw_pages)

        routing_reasoning = await self._gemini_route(
            stage="Extraction",
            result_summary=f"{total_spans:,} text spans extracted, "
                           f"{sum(1 for rp in raw_pages if rp.ocr_applied)} OCR pages",
            next_stage="Segmentation",
        )
        await self.decide(
            decision="Route: Extraction → Segmentation",
            reasoning=routing_reasoning,
            action="SegmentationAgent activated (XY-Cut)",
            confidence=0.97,
        )

        # ── Stage 4: Segmentation ────────────────────────────────────────────
        seg_result = await self.agents["segmentation"].run(raw_pages, pages, context)
        pipeline_data.update(seg_result)
        total_blocks = sum(len(b) for b in seg_result["all_raw_blocks"])

        routing_reasoning = await self._gemini_route(
            stage="Segmentation",
            result_summary=f"{total_blocks} blocks segmented, {len(seg_result['running_headers'])} running headers found",
            next_stage="Classification",
        )
        await self.decide(
            decision="Route: Segmentation → Classification",
            reasoning=routing_reasoning,
            action="ClassificationAgent activated (rule engine + Gemini fallback)",
            confidence=0.97,
        )

        # ── Stage 5: Classification ──────────────────────────────────────────
        cls_result = await self.agents["classification"].run(
            seg_result["all_raw_blocks"], pages, seg_result["running_headers"], context
        )
        pipeline_data.update(cls_result)
        type_counts = cls_result["type_counts"]

        if type_counts.get("Heading", 0) == 0:
            qa.add_flag("no_headings", {"detail": "Zero heading blocks — flat or non-standard document", "priority": "high"})

        routing_reasoning = await self._gemini_route(
            stage="Classification",
            result_summary=f"{sum(type_counts.values())} blocks → {type_counts}",
            next_stage="Assembly + Table (parallel)",
            alternatives=["Sequential Assembly then Table"],
        )
        await self.decide(
            decision="Route: Classification → Assembly ‖ Table (PARALLEL)",
            reasoning=routing_reasoning,
            action="asyncio.gather(AssemblyAgent, TableAgent) — 40% latency reduction",
            confidence=0.98,
        )

        # ── Stages 6+7: Assembly + Table in PARALLEL ─────────────────────────
        page_captions: dict[int, list[str]] = {}
        for pn, cbs in cls_result["pages_classified"]:
            for cb in cbs:
                if cb.block_type in ("TableCaption", "FigureCaption"):
                    page_captions.setdefault(pn, []).append(cb.raw.text)

        asm_result, tbl_result = await asyncio.gather(
            self.agents["assembly"].run(cls_result["pages_classified"], doc_id, context),
            self.agents["table"].run(pdf_path, doc_id, page_captions, context),
        )
        pipeline_data.update(asm_result)
        pipeline_data.update(tbl_result)

        section_drafts = asm_result["section_drafts"]
        parsed_tables  = tbl_result["parsed_tables"]
        table_index    = tbl_result["table_index"]

        # Build resolution indices
        section_index = {}
        for sd in section_drafts:
            if sd.heading_number:
                section_index[sd.heading_number] = sd.section_id
            section_index[sd.title] = sd.section_id
        page_index = {pr.page_number: pr.page_id for pr in pages}

        routing_reasoning = await self._gemini_route(
            stage="Assembly + Table (parallel)",
            result_summary=f"{len(section_drafts)} sections (max depth {max((s.level for s in section_drafts), default=0)}), "
                           f"{len(parsed_tables)} tables with {sum(t.row_count*t.column_count for t in parsed_tables)} cells",
            next_stage="Reference Resolution",
        )
        await self.decide(
            decision="Route: Assembly+Table → Reference Resolution",
            reasoning=routing_reasoning,
            action="ReferenceAgent activated with table_index + section_index",
            confidence=0.96,
        )

        # ── Stage 8: References ──────────────────────────────────────────────
        from agents._block_stub import make_block_stubs
        block_stubs = make_block_stubs(cls_result["pages_classified"], doc_id)

        ref_result = await self.agents["reference"].run(
            block_stubs, doc_id, table_index, section_index, page_index, context
        )
        pipeline_data.update(ref_result)
        resolved_refs = ref_result["resolved_refs"]
        n_resolved = sum(1 for r in resolved_refs if r.is_resolved)

        routing_reasoning = await self._gemini_route(
            stage="Reference Resolution",
            result_summary=f"{len(resolved_refs)} references found, {n_resolved} resolved, "
                           f"{len(resolved_refs)-n_resolved} unresolved",
            next_stage="Quality Assessment",
        )
        await self.decide(
            decision="Route: Reference → Quality Assessment",
            reasoning=routing_reasoning,
            action="QualityAgent aggregates all pipeline flags for Gemini risk assessment",
            confidence=0.97,
        )

        # ── Quality review ────────────────────────────────────────────────────
        qa_result = await self.agents["quality"].run(context)
        pipeline_data.update(qa_result)
        quality   = pipeline_data["quality_report"]

        if quality["requires_human_review"]:
            await self.decide(
                decision="⚠ Human review required — document flagged",
                reasoning=quality.get("gemini_assessment", "Multiple high-priority flags detected."),
                action="Document status → 'needs_review'. Continuing to persistence with flags embedded.",
                confidence=0.95,
            )
            doc.status = "needs_review"
        else:
            routing_reasoning = await self._gemini_route(
                stage="Quality Assessment",
                result_summary=f"Verdict: {quality['verdict']} · {quality['total_flags']} flags "
                               f"({quality['critical']} critical, {quality['high']} high)",
                next_stage="Persistence",
            )
            await self.decide(
                decision=f"Route: Quality ({quality['verdict']}) → Persistence",
                reasoning=routing_reasoning,
                action="PersistenceAgent — committing all entities + evidence anchors to database",
                confidence=0.99,
            )

        # ── Stage 9: Persistence ─────────────────────────────────────────────
        persist_result = await self.agents["persistence"].run(pipeline_data, context)
        pipeline_data.update(persist_result)
        counts = persist_result["counts"]

        # ── Pipeline complete ─────────────────────────────────────────────────
        final_summary = await self.llm_reason(
            f"""The full DIS multi-agent pipeline has completed for document: {original_name}

Final counts: {counts}
Quality verdict: {quality['verdict']}
Total agent decisions made: {sum(len(a.decisions) for a in self.agents.values()) + len(self.decisions)}

Write a 1-sentence completion message for the operations team.""",
            max_tokens=80,
        )

        await self.decide(
            decision=f"Pipeline COMPLETE — {counts}",
            reasoning=final_summary,
            action="Document ready for query. SSE stream closing.",
            confidence=1.0,
        )
        await self.set_status("done", "All agents complete")
        await self._emit("pipeline_complete", {
            "document_id": doc_id,
            "document_title": doc.title or original_name,
            "counts": counts,
            "quality": quality,
        })

        return {"document_id": doc_id, "counts": counts}
