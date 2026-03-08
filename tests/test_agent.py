"""Tests for the NexusOS Agent."""

import asyncio
import pytest
from nexus_core.agent import Agent, AgentConfig, AgentDecision, AgentState, PrivilegeLevel


@pytest.fixture
def agent():
    config = AgentConfig(
        name="test-agent",
        credit_budget=100.0,
        auto_escalate_below_confidence=0.7,
        allowed_mcp_servers=["filesystem", "credits"],
    )
    return Agent(agent_id="test-001", config=config)


class TestAgentLifecycle:
    def test_initial_state(self, agent):
        assert agent.state == AgentState.CREATED
        assert agent.credits_used == 0.0
        assert agent.credits_remaining == 100.0
        assert len(agent.decisions) == 0

    def test_stop(self, agent):
        agent.stop()
        assert agent.state == AgentState.STOPPED

    def test_pause(self, agent):
        agent.pause()
        assert agent.state == AgentState.PAUSED

    def test_terminate(self, agent):
        agent.terminate()
        assert agent.state == AgentState.TERMINATED


class TestAgentBudget:
    def test_budget_check_within_limit(self, agent):
        assert agent._check_budget(50.0) is True

    def test_budget_check_exceeds_limit(self, agent):
        agent.credits_used = 95.0
        assert agent._check_budget(10.0) is False

    def test_budget_check_exact_limit(self, agent):
        agent.credits_used = 90.0
        assert agent._check_budget(10.0) is True

    def test_credits_remaining(self, agent):
        agent.credits_used = 30.0
        assert agent.credits_remaining == 70.0


class TestAgentTaskExecution:
    @pytest.mark.asyncio
    async def test_execute_task_success(self, agent):
        task = {
            "action": "test_action",
            "goal": "test goal",
            "confidence": 0.9,
            "estimated_credits": 5.0,
            "tool_calls": [],
        }
        decision = await agent._execute_task(task)
        assert decision.outcome == "completed"
        assert decision.credits_consumed == 5.0
        assert agent.credits_used == 5.0

    @pytest.mark.asyncio
    async def test_execute_task_low_confidence_escalates(self, agent):
        task = {
            "action": "risky_action",
            "goal": "risky goal",
            "confidence": 0.3,
            "estimated_credits": 5.0,
            "tool_calls": [],
        }
        decision = await agent._execute_task(task)
        assert decision.outcome == "escalated_to_human"
        assert agent.credits_used == 0.0  # No credits consumed on escalation

    @pytest.mark.asyncio
    async def test_execute_task_budget_exceeded(self, agent):
        agent.credits_used = 99.0
        task = {
            "action": "expensive_action",
            "confidence": 0.9,
            "estimated_credits": 5.0,
            "tool_calls": [],
        }
        decision = await agent._execute_task(task)
        assert decision.outcome == "budget_exceeded"

    @pytest.mark.asyncio
    async def test_execute_task_denied_mcp_server(self, agent):
        task = {
            "action": "network_action",
            "confidence": 0.9,
            "estimated_credits": 1.0,
            "tool_calls": [
                {"server": "network", "tool": "http_get", "arguments": {"url": "http://example.com"}}
            ],
        }
        decision = await agent._execute_task(task)
        # Tool call should be skipped (network not in allowed servers)
        assert decision.outcome == "completed"
        assert len(decision.tool_calls) == 0


class TestAgentAudit:
    @pytest.mark.asyncio
    async def test_audit_log(self, agent):
        task = {
            "action": "audited_action",
            "goal": "test audit",
            "confidence": 0.95,
            "estimated_credits": 2.0,
            "tool_calls": [],
        }
        await agent._execute_task(task)

        log = agent.get_audit_log()
        assert len(log) == 1
        assert log[0]["action"] == "audited_action"
        assert log[0]["confidence"] == 0.95
        assert log[0]["credits"] == 2.0
        assert "explainability" in log[0]
        assert log[0]["explainability"].startswith("nexus://decisions/")


class TestAgentDecision:
    def test_explainability_link(self):
        decision = AgentDecision(decision_id="abc123", action="test")
        assert decision.explainability_link == "nexus://decisions/abc123"
