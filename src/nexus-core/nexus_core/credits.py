"""Credits — Digital Labor Credit tracking and enforcement."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger("nexus.credits")


class Base(DeclarativeBase):
    pass


class CreditEvent(Base):
    """Database model for credit consumption events."""

    __tablename__ = "credit_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String(64), nullable=False, index=True)
    event_type = Column(String(32), nullable=False)  # consume, refund, allocate
    amount = Column(Float, nullable=False)
    balance_after = Column(Float, nullable=False)
    description = Column(Text, default="")
    tool_server = Column(String(64), default="")
    tool_name = Column(String(128), default="")
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AgentBudget(Base):
    """Database model for per-agent credit budgets."""

    __tablename__ = "agent_budgets"

    agent_id = Column(String(64), primary_key=True)
    total_budget = Column(Float, nullable=False, default=1000.0)
    used = Column(Float, nullable=False, default=0.0)
    billing_period_start = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class EventType(str, Enum):
    CONSUME = "consume"
    REFUND = "refund"
    ALLOCATE = "allocate"


@dataclass
class CreditUsage:
    """Summary of credit usage for an agent."""

    agent_id: str
    total_budget: float
    used: float
    remaining: float
    event_count: int


class CreditLedger:
    """
    Local SQLite-based ledger for Digital Labor Credit tracking.

    Handles:
    - Per-agent budget allocation and enforcement
    - Credit consumption metering (API calls, compute, tool invocations)
    - Billing event generation
    - Usage reporting and audit trails
    """

    def __init__(self, db_path: str = "/var/lib/nexus/credits.sqlite"):
        self.db_path = db_path
        self._engine = None
        self._session_factory = None

    async def initialize(self) -> None:
        """Initialize the database and create tables."""
        self._engine = create_engine(f"sqlite:///{self.db_path}", echo=False)
        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(bind=self._engine)
        logger.info("Credit ledger initialized at %s", self.db_path)

    def _get_session(self) -> Session:
        if not self._session_factory:
            raise RuntimeError("CreditLedger not initialized.")
        return self._session_factory()

    async def allocate_budget(self, agent_id: str, budget: float) -> None:
        """Allocate a credit budget to an agent."""
        with self._get_session() as session:
            existing = session.get(AgentBudget, agent_id)
            if existing:
                existing.total_budget = budget
            else:
                session.add(AgentBudget(
                    agent_id=agent_id,
                    total_budget=budget,
                    used=0.0,
                ))
            session.commit()
        logger.info("Allocated %.0f credits to agent %s", budget, agent_id)

    async def consume(
        self,
        agent_id: str,
        amount: float,
        description: str = "",
        tool_server: str = "",
        tool_name: str = "",
    ) -> bool:
        """
        Consume credits from an agent's budget.

        Returns True if successful, False if budget exceeded.
        """
        with self._get_session() as session:
            budget = session.get(AgentBudget, agent_id)
            if not budget:
                logger.warning("No budget found for agent %s", agent_id)
                return False

            if budget.used + amount > budget.total_budget:
                logger.warning(
                    "Agent %s: budget exceeded (used=%.1f + %.1f > %.1f)",
                    agent_id, budget.used, amount, budget.total_budget,
                )
                return False

            budget.used += amount
            balance = budget.total_budget - budget.used

            session.add(CreditEvent(
                agent_id=agent_id,
                event_type=EventType.CONSUME.value,
                amount=amount,
                balance_after=balance,
                description=description,
                tool_server=tool_server,
                tool_name=tool_name,
            ))
            session.commit()

        logger.debug(
            "Agent %s consumed %.2f credits (%s). Remaining: %.1f",
            agent_id, amount, description, balance,
        )
        return True

    async def refund(self, agent_id: str, amount: float, reason: str = "") -> None:
        """Refund credits to an agent's budget."""
        with self._get_session() as session:
            budget = session.get(AgentBudget, agent_id)
            if not budget:
                return

            budget.used = max(0.0, budget.used - amount)
            balance = budget.total_budget - budget.used

            session.add(CreditEvent(
                agent_id=agent_id,
                event_type=EventType.REFUND.value,
                amount=amount,
                balance_after=balance,
                description=reason,
            ))
            session.commit()

    async def get_usage(self, agent_id: str) -> CreditUsage | None:
        """Get credit usage summary for an agent."""
        with self._get_session() as session:
            budget = session.get(AgentBudget, agent_id)
            if not budget:
                return None

            event_count = (
                session.query(CreditEvent)
                .filter(CreditEvent.agent_id == agent_id)
                .count()
            )

            return CreditUsage(
                agent_id=agent_id,
                total_budget=budget.total_budget,
                used=budget.used,
                remaining=budget.total_budget - budget.used,
                event_count=event_count,
            )

    async def get_events(
        self, agent_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get recent credit events for an agent."""
        with self._get_session() as session:
            events = (
                session.query(CreditEvent)
                .filter(CreditEvent.agent_id == agent_id)
                .order_by(CreditEvent.timestamp.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": e.id,
                    "type": e.event_type,
                    "amount": e.amount,
                    "balance_after": e.balance_after,
                    "description": e.description,
                    "tool": f"{e.tool_server}.{e.tool_name}" if e.tool_server else "",
                    "timestamp": e.timestamp.isoformat() if e.timestamp else "",
                }
                for e in events
            ]

    async def get_system_total(self) -> dict[str, float]:
        """Get system-wide credit usage totals."""
        with self._get_session() as session:
            budgets = session.query(AgentBudget).all()
            total_allocated = sum(b.total_budget for b in budgets)
            total_used = sum(b.used for b in budgets)
            return {
                "total_allocated": total_allocated,
                "total_used": total_used,
                "total_remaining": total_allocated - total_used,
                "agent_count": len(budgets),
            }

    async def close(self) -> None:
        """Close the database connection."""
        if self._engine:
            self._engine.dispose()
        logger.info("Credit ledger closed.")
