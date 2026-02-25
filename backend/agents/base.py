"""
Base Agent infrastructure for DIS Multi-Agent System.

Every agent:
  - Has a name, emoji, role description
  - Can call await self.llm_reason(prompt) to get Gemini intelligence
  - Can emit typed events to the shared SSE event bus
  - Can log decisions (with reasoning + confidence)
  - Can send/receive messages to/from other agents
  - Maintains its own status lifecycle: idle → running → waiting → done / error
"""
from __future__ import annotations
import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────── Data structures ───────────────────────────────

@dataclass
class AgentMessage:
    """Typed inter-agent message (not a raw function call)."""
    message_id: str
    sender: str
    recipient: str        # agent name or "orchestrator" or "broadcast"
    subject: str          # machine-readable intent: "ocr_required", "table_found", etc.
    payload: dict
    timestamp: str = field(default_factory=_ts)
    priority: str = "normal"   # "critical" | "normal" | "low"


@dataclass
class AgentDecision:
    """A logged decision made by an agent during processing."""
    decision_id: str
    agent: str
    decision: str      # short headline
    reasoning: str     # full reasoning
    action: str        # action taken
    confidence: float  # 0.0–1.0
    timestamp: str = field(default_factory=_ts)


# ─────────────────────────────── Base Agent ────────────────────────────────────

class BaseAgent:
    name: str = "base"
    emoji: str = "🤖"
    description: str = "Base agent"

    def __init__(self, event_bus: asyncio.Queue):
        self.event_bus = event_bus
        self.status = "idle"           # idle | running | waiting | done | error
        self.current_task = ""
        self.decisions: list[AgentDecision] = []
        self.messages_sent: list[AgentMessage] = []
        self.messages_received: list[AgentMessage] = []
        self._inbox: asyncio.Queue = asyncio.Queue()

    # ── Event emission ────────────────────────────────────────────────────────

    async def _emit(self, event_type: str, extra: dict):
        await self.event_bus.put({
            "type": event_type,
            "agent": self.name,
            "emoji": self.emoji,
            "timestamp": _ts(),
            **extra,
        })

    async def set_status(self, status: str, task: str = ""):
        self.status = status
        self.current_task = task
        await self._emit("agent_status", {"status": status, "task": task})

    async def log(self, message: str, level: str = "info"):
        await self._emit("agent_log", {"message": message, "level": level})

    async def decide(
        self,
        decision: str,
        reasoning: str,
        action: str,
        confidence: float = 1.0,
    ) -> AgentDecision:
        d = AgentDecision(
            decision_id=uuid.uuid4().hex[:8],
            agent=self.name,
            decision=decision,
            reasoning=reasoning,
            action=action,
            confidence=confidence,
        )
        self.decisions.append(d)
        await self._emit("agent_decision", {
            "decision_id": d.decision_id,
            "decision": decision,
            "reasoning": reasoning,
            "action": action,
            "confidence": confidence,
        })
        return d

    async def send_message(
        self,
        to: str,
        subject: str,
        payload: dict,
        priority: str = "normal",
    ) -> AgentMessage:
        msg = AgentMessage(
            message_id=uuid.uuid4().hex[:8],
            sender=self.name,
            recipient=to,
            subject=subject,
            payload=payload,
            priority=priority,
        )
        self.messages_sent.append(msg)
        await self._emit("agent_message", {
            "message_id": msg.message_id,
            "from": self.name,
            "to": to,
            "subject": subject,
            "summary": _summarise(payload),
            "priority": priority,
        })
        return msg

    async def receive_message(self, msg: AgentMessage):
        self.messages_received.append(msg)
        await self._emit("agent_message_received", {
            "message_id": msg.message_id,
            "from": msg.sender,
            "subject": msg.subject,
        })

    async def error(self, message: str, exc: Optional[Exception] = None):
        await self.set_status("error", message)
        await self._emit("agent_error", {
            "message": message,
            "detail": str(exc) if exc else "",
        })

    async def llm_reason(
        self,
        prompt: str,
        system_extra: str = "",
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> str:
        """
        Ask Gemini to reason about the current situation.
        Runs in a thread executor so it never blocks the async event loop.
        Returns the reasoning text (or a fallback string on error).
        """
        from agents import gemini_client
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: gemini_client.query(prompt, system_extra, temperature, max_tokens),
        )
        return result

    async def llm_json(
        self,
        prompt: str,
        system_extra: str = "",
        fallback: dict | None = None,
    ) -> dict:
        """Ask Gemini to return a JSON decision object."""
        from agents import gemini_client
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: gemini_client.query_json(prompt, system_extra, fallback),
        )
        return result


def _summarise(payload: dict) -> str:
    """One-line payload summary for the UI message feed."""
    if not payload:
        return "(empty)"
    items = []
    for k, v in list(payload.items())[:3]:
        items.append(f"{k}={v!r:.40}")
    return ", ".join(items)
