"""Orchestrator — manages multiple concurrent agents as the main system daemon."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
from pathlib import Path

import click

from nexus_core.agent import Agent, AgentConfig, AgentState, PrivilegeLevel
from nexus_core.credits import CreditLedger
from nexus_core.dashboard import DashboardAPI

logger = logging.getLogger("nexus.orchestrator")

DEFAULT_CONFIG_PATH = "/etc/nexus/nexus.conf"
DEFAULT_REGISTRY_PATH = "/etc/nexus/mcp-registry.json"


class Orchestrator:
    """
    Central orchestrator that manages the lifecycle of all agents.

    Responsibilities:
    - Spawn and manage concurrent agents
    - Route tasks to appropriate agents
    - Enforce system-wide credit budgets
    - Handle inter-agent communication
    - Provide health monitoring
    """

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.agents: dict[str, Agent] = {}
        self.max_concurrent = self.config.get("agents", {}).get("max_concurrent", 8)
        self._running = False
        self._ledger: CreditLedger | None = None
        self._mcp_registry: dict = {}
        self._dashboard: DashboardAPI | None = None

    async def initialize(self) -> None:
        """Initialize the orchestrator and its subsystems."""
        logger.info("Initializing NexusOS Orchestrator...")

        # Initialize credit ledger
        ledger_path = (
            self.config.get("credits", {})
            .get("ledger_db_path", "/var/lib/nexus/credits.sqlite")
        )
        self._ledger = CreditLedger(ledger_path)
        await self._ledger.initialize()

        # Load MCP registry
        registry_path = Path(DEFAULT_REGISTRY_PATH)
        if registry_path.exists():
            self._mcp_registry = json.loads(registry_path.read_text())
            logger.info(
                "Loaded %d MCP servers from registry.",
                len(self._mcp_registry.get("servers", {})),
            )

        # Start dashboard API for Cinnamon applet/desklet
        dashboard_cfg = self.config.get("dashboard", {})
        if dashboard_cfg.get("enabled", True):
            self._dashboard = DashboardAPI(
                orchestrator=self,
                host=dashboard_cfg.get("bind_address", "127.0.0.1"),
                port=dashboard_cfg.get("port", 9500),
            )
            await self._dashboard.start()

        logger.info("Orchestrator initialized.")

    async def spawn_agent(
        self,
        name: str,
        privilege: PrivilegeLevel = PrivilegeLevel.READ_WRITE,
        credit_budget: float = 1000.0,
        allowed_servers: list[str] | None = None,
    ) -> Agent:
        """Spawn a new agent with the given configuration."""
        if len(self.agents) >= self.max_concurrent:
            raise RuntimeError(
                f"Maximum concurrent agents ({self.max_concurrent}) reached."
            )

        config = AgentConfig(
            name=name,
            max_privilege=privilege,
            credit_budget=credit_budget,
            allowed_mcp_servers=allowed_servers or ["filesystem", "credits"],
        )
        agent = Agent(config=config)
        self.agents[agent.agent_id] = agent

        logger.info(
            "Spawned agent '%s' (id=%s, privilege=%s, budget=%.0f)",
            name, agent.agent_id, privilege.name, credit_budget,
        )
        return agent

    async def start_agent(self, agent_id: str) -> None:
        """Start an agent's autonomous loop in the background."""
        agent = self.agents.get(agent_id)
        if not agent:
            raise KeyError(f"Agent {agent_id} not found.")

        asyncio.create_task(agent.start(), name=f"agent-{agent_id}")

    async def stop_agent(self, agent_id: str) -> None:
        """Stop an agent gracefully."""
        agent = self.agents.get(agent_id)
        if agent:
            agent.stop()

    async def terminate_agent(self, agent_id: str) -> None:
        """Force-terminate an agent."""
        agent = self.agents.get(agent_id)
        if agent:
            agent.terminate()
            del self.agents[agent_id]

    async def route_goal(self, goal: str, agent_name: str | None = None) -> str:
        """
        Route a high-level goal to the most appropriate agent.

        If agent_name is specified, routes directly. Otherwise, selects
        the best available agent based on capability and budget.
        """
        target: Agent | None = None

        if agent_name:
            for agent in self.agents.values():
                if agent.config.name == agent_name:
                    target = agent
                    break

        if not target:
            # Select agent with most remaining budget
            running_agents = [
                a for a in self.agents.values()
                if a.state == AgentState.RUNNING
            ]
            if not running_agents:
                raise RuntimeError("No running agents available.")
            target = max(running_agents, key=lambda a: a.credits_remaining)

        await target.submit_goal(goal)
        logger.info(
            "Routed goal to agent '%s' (%s): %s",
            target.config.name, target.agent_id, goal[:80],
        )
        return target.agent_id

    def get_system_status(self) -> dict:
        """Get overall system status."""
        return {
            "orchestrator": "running" if self._running else "stopped",
            "agents": {
                aid: {
                    "name": a.config.name,
                    "state": a.state.value,
                    "credits_used": a.credits_used,
                    "credits_remaining": a.credits_remaining,
                    "decisions_made": len(a.decisions),
                }
                for aid, a in self.agents.items()
            },
            "total_agents": len(self.agents),
            "max_agents": self.max_concurrent,
        }

    async def run(self) -> None:
        """Main daemon loop."""
        self._running = True
        logger.info("NexusOS Orchestrator running. Press Ctrl+C to stop.")

        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Gracefully shut down all agents and subsystems."""
        logger.info("Shutting down orchestrator...")
        self._running = False

        for agent_id in list(self.agents.keys()):
            await self.stop_agent(agent_id)

        if self._ledger:
            await self._ledger.close()

        logger.info("Orchestrator shut down complete.")


def _load_config(path: str) -> dict:
    """Load TOML config file."""
    config_path = Path(path)
    if not config_path.exists():
        logger.warning("Config not found at %s, using defaults.", path)
        return {}

    try:
        import tomli
        return tomli.loads(config_path.read_text())
    except ImportError:
        logger.warning("tomli not available, using empty config.")
        return {}


@click.command()
@click.option("--config", "-c", default=DEFAULT_CONFIG_PATH, help="Config file path")
def main(config: str) -> None:
    """NexusOS Core — Autonomous Agentic AI Orchestration Daemon."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    cfg = _load_config(config)
    orchestrator = Orchestrator(cfg)

    loop = asyncio.new_event_loop()

    def _handle_signal() -> None:
        loop.create_task(orchestrator.shutdown())

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    try:
        loop.run_until_complete(orchestrator.initialize())
        loop.run_until_complete(orchestrator.run())
    except KeyboardInterrupt:
        loop.run_until_complete(orchestrator.shutdown())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
