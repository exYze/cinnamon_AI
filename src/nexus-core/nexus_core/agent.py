"""Core Agent — autonomous unit that executes tasks independently."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger("nexus.agent")


class AgentState(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    TERMINATED = "terminated"
    ERROR = "error"


class PrivilegeLevel(int, Enum):
    READ_ONLY = 1
    READ_WRITE = 2
    EXECUTE = 3
    ADMIN = 4


@dataclass
class AgentDecision:
    """A recorded decision made by an agent, with full auditability."""

    decision_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    action: str = ""
    reasoning: str = ""
    confidence: float = 0.0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    outcome: str | None = None
    credits_consumed: float = 0.0

    @property
    def explainability_link(self) -> str:
        return f"nexus://decisions/{self.decision_id}"


@dataclass
class AgentConfig:
    """Configuration for an agent instance."""

    name: str = "unnamed-agent"
    model: str = "claude-sonnet-4-6"
    max_privilege: PrivilegeLevel = PrivilegeLevel.READ_WRITE
    sandbox: bool = True
    credit_budget: float = 1000.0
    hotl_window_seconds: int = 300
    auto_escalate_below_confidence: float = 0.7
    allowed_mcp_servers: list[str] = field(default_factory=lambda: ["filesystem", "credits"])


class Agent:
    """
    An autonomous agentic unit that executes tasks independently.

    Each agent has its own identity, credit budget, permission scope, and
    decision log. Agents interact with the system through MCP servers and
    can make multi-step decisions without human approval.
    """

    def __init__(
        self,
        agent_id: str | None = None,
        identity_id: str | None = None,
        config: AgentConfig | None = None,
    ):
        self.agent_id = agent_id or uuid.uuid4().hex[:16]
        self.identity_id = identity_id or f"agent:{self.agent_id}"
        self.config = config or AgentConfig()
        self.state = AgentState.CREATED
        self.credits_used: float = 0.0
        self.decisions: list[AgentDecision] = []
        self._task_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._cancel_event = asyncio.Event()
        self._mcp_clients: dict[str, Any] = {}

    @property
    def credits_remaining(self) -> float:
        return self.config.credit_budget - self.credits_used

    def _check_budget(self, cost: float) -> bool:
        if self.credits_used + cost > self.config.credit_budget:
            logger.warning(
                "Agent %s: budget exceeded (used=%.1f, budget=%.1f)",
                self.agent_id, self.credits_used, self.config.credit_budget,
            )
            return False
        return True

    async def start(self) -> None:
        """Start the agent's autonomous task loop."""
        if self.state not in (AgentState.CREATED, AgentState.STOPPED):
            raise RuntimeError(f"Cannot start agent in state {self.state}")

        self.state = AgentState.RUNNING
        self._cancel_event.clear()
        logger.info("Agent %s (%s) started.", self.agent_id, self.config.name)

        try:
            await self._run_loop()
        except asyncio.CancelledError:
            logger.info("Agent %s cancelled.", self.agent_id)
        except Exception:
            self.state = AgentState.ERROR
            logger.exception("Agent %s encountered an error.", self.agent_id)
            raise
        finally:
            if self.state == AgentState.RUNNING:
                self.state = AgentState.STOPPED

    async def _run_loop(self) -> None:
        """Main task execution loop."""
        while not self._cancel_event.is_set():
            try:
                task = await asyncio.wait_for(
                    self._task_queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue

            await self._execute_task(task)

    async def _execute_task(self, task: dict[str, Any]) -> AgentDecision:
        """
        Execute a single task autonomously.

        The agent analyzes the task, determines the best action,
        checks confidence thresholds, and executes via MCP tools.
        """
        decision = AgentDecision(
            action=task.get("action", "unknown"),
            reasoning=task.get("goal", ""),
        )

        # Simulate decision-making (replace with actual LLM call)
        decision.confidence = task.get("confidence", 0.8)

        # HOTL check: if confidence is below threshold, escalate
        if decision.confidence < self.config.auto_escalate_below_confidence:
            logger.info(
                "Agent %s: confidence %.2f below threshold, escalating.",
                self.agent_id, decision.confidence,
            )
            decision.outcome = "escalated_to_human"
            self.decisions.append(decision)
            return decision

        # Budget check
        estimated_cost = task.get("estimated_credits", 1.0)
        if not self._check_budget(estimated_cost):
            decision.outcome = "budget_exceeded"
            self.decisions.append(decision)
            return decision

        # Execute tool calls via MCP
        tool_calls = task.get("tool_calls", [])
        for tool_call in tool_calls:
            server = tool_call.get("server", "")
            if server not in self.config.allowed_mcp_servers:
                logger.warning(
                    "Agent %s: denied access to MCP server '%s'",
                    self.agent_id, server,
                )
                continue

            result = await self._invoke_mcp_tool(
                server=server,
                tool=tool_call.get("tool", ""),
                arguments=tool_call.get("arguments", {}),
            )
            decision.tool_calls.append({**tool_call, "result": result})

        # Deduct credits
        self.credits_used += estimated_cost
        decision.credits_consumed = estimated_cost
        decision.outcome = "completed"

        self.decisions.append(decision)
        logger.info(
            "Agent %s: completed action '%s' (confidence=%.2f, credits=%.1f)",
            self.agent_id, decision.action, decision.confidence,
            decision.credits_consumed,
        )
        return decision

    async def _invoke_mcp_tool(
        self, server: str, tool: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Invoke a tool on an MCP server."""
        # TODO: Replace with actual MCP client calls
        logger.debug(
            "Agent %s: invoking %s.%s(%s)",
            self.agent_id, server, tool, arguments,
        )
        return {"status": "ok", "server": server, "tool": tool}

    async def submit_task(self, task: dict[str, Any]) -> None:
        """Submit a task for autonomous execution."""
        await self._task_queue.put(task)

    async def submit_goal(self, goal: str, priority: int = 5) -> None:
        """
        Submit a high-level goal for autonomous decomposition and execution.
        Example: "Increase quarterly profit by 15% while reducing carbon footprint by 5%"
        """
        await self._task_queue.put({
            "action": "goal_decomposition",
            "goal": goal,
            "priority": priority,
            "confidence": 0.9,
            "estimated_credits": 5.0,
            "tool_calls": [],
        })

    def pause(self) -> None:
        """Pause the agent (it will finish current task)."""
        self.state = AgentState.PAUSED
        self._cancel_event.set()
        logger.info("Agent %s paused.", self.agent_id)

    def stop(self) -> None:
        """Stop the agent gracefully."""
        self.state = AgentState.STOPPED
        self._cancel_event.set()
        logger.info("Agent %s stopped.", self.agent_id)

    def terminate(self) -> None:
        """Force-terminate the agent immediately."""
        self.state = AgentState.TERMINATED
        self._cancel_event.set()
        logger.warning("Agent %s terminated.", self.agent_id)

    def get_audit_log(self) -> list[dict[str, Any]]:
        """Return full decision audit trail for this agent."""
        return [
            {
                "decision_id": d.decision_id,
                "timestamp": d.timestamp.isoformat(),
                "action": d.action,
                "confidence": d.confidence,
                "outcome": d.outcome,
                "credits": d.credits_consumed,
                "explainability": d.explainability_link,
                "tool_calls": d.tool_calls,
            }
            for d in self.decisions
        ]
