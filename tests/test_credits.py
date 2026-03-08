"""Tests for the Digital Labor Credit system."""

import os
import tempfile
import pytest
from nexus_core.credits import CreditLedger


@pytest.fixture
async def ledger():
    """Create a temporary credit ledger for testing."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name

    ledger = CreditLedger(db_path=db_path)
    await ledger.initialize()
    yield ledger
    await ledger.close()
    os.unlink(db_path)


class TestCreditAllocation:
    @pytest.mark.asyncio
    async def test_allocate_budget(self, ledger):
        await ledger.allocate_budget("agent-001", 500.0)
        usage = await ledger.get_usage("agent-001")
        assert usage is not None
        assert usage.total_budget == 500.0
        assert usage.used == 0.0
        assert usage.remaining == 500.0

    @pytest.mark.asyncio
    async def test_update_existing_budget(self, ledger):
        await ledger.allocate_budget("agent-001", 500.0)
        await ledger.allocate_budget("agent-001", 1000.0)
        usage = await ledger.get_usage("agent-001")
        assert usage.total_budget == 1000.0


class TestCreditConsumption:
    @pytest.mark.asyncio
    async def test_consume_within_budget(self, ledger):
        await ledger.allocate_budget("agent-001", 100.0)
        result = await ledger.consume("agent-001", 25.0, "API call")
        assert result is True
        usage = await ledger.get_usage("agent-001")
        assert usage.used == 25.0
        assert usage.remaining == 75.0

    @pytest.mark.asyncio
    async def test_consume_exceeds_budget(self, ledger):
        await ledger.allocate_budget("agent-001", 100.0)
        await ledger.consume("agent-001", 90.0)
        result = await ledger.consume("agent-001", 20.0)
        assert result is False

    @pytest.mark.asyncio
    async def test_consume_no_budget(self, ledger):
        result = await ledger.consume("nonexistent", 10.0)
        assert result is False

    @pytest.mark.asyncio
    async def test_multiple_consumptions(self, ledger):
        await ledger.allocate_budget("agent-001", 100.0)
        await ledger.consume("agent-001", 10.0, "call 1")
        await ledger.consume("agent-001", 20.0, "call 2")
        await ledger.consume("agent-001", 30.0, "call 3")
        usage = await ledger.get_usage("agent-001")
        assert usage.used == 60.0
        assert usage.event_count == 3


class TestCreditRefund:
    @pytest.mark.asyncio
    async def test_refund(self, ledger):
        await ledger.allocate_budget("agent-001", 100.0)
        await ledger.consume("agent-001", 50.0)
        await ledger.refund("agent-001", 20.0, "cancelled task")
        usage = await ledger.get_usage("agent-001")
        assert usage.used == 30.0


class TestCreditEvents:
    @pytest.mark.asyncio
    async def test_event_history(self, ledger):
        await ledger.allocate_budget("agent-001", 100.0)
        await ledger.consume("agent-001", 10.0, "test action", "filesystem", "read")
        events = await ledger.get_events("agent-001")
        assert len(events) == 1
        assert events[0]["type"] == "consume"
        assert events[0]["amount"] == 10.0
        assert events[0]["tool"] == "filesystem.read"


class TestSystemTotals:
    @pytest.mark.asyncio
    async def test_system_total(self, ledger):
        await ledger.allocate_budget("agent-001", 100.0)
        await ledger.allocate_budget("agent-002", 200.0)
        await ledger.consume("agent-001", 30.0)
        await ledger.consume("agent-002", 50.0)
        totals = await ledger.get_system_total()
        assert totals["total_allocated"] == 300.0
        assert totals["total_used"] == 80.0
        assert totals["total_remaining"] == 220.0
        assert totals["agent_count"] == 2
