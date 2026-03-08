"""Dashboard API — local HTTP server for Cinnamon applet/desklet communication."""

from __future__ import annotations

import asyncio
import json
import logging

from aiohttp import web

logger = logging.getLogger("nexus.dashboard")


class DashboardAPI:
    """
    Local HTTP API that serves agent status to the Cinnamon panel applet
    and Fish Tank desklet. Binds to localhost only.
    """

    def __init__(self, orchestrator, host: str = "127.0.0.1", port: int = 9500):
        self.orchestrator = orchestrator
        self.host = host
        self.port = port
        self._app = web.Application()
        self._app.router.add_get("/api/status", self._handle_status)
        self._app.router.add_get("/api/agents/{agent_id}", self._handle_agent_detail)
        self._app.router.add_get(
            "/api/agents/{agent_id}/decisions", self._handle_agent_decisions
        )
        self._app.router.add_post("/api/agents", self._handle_spawn_agent)
        self._app.router.add_post(
            "/api/agents/{agent_id}/goal", self._handle_submit_goal
        )
        self._app.router.add_delete(
            "/api/agents/{agent_id}", self._handle_stop_agent
        )

    async def start(self) -> None:
        """Start the dashboard API server."""
        runner = web.AppRunner(self._app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        logger.info("Dashboard API listening on http://%s:%d", self.host, self.port)

    async def _handle_status(self, request: web.Request) -> web.Response:
        """GET /api/status — system overview for panel applet."""
        status = self.orchestrator.get_system_status()
        return web.json_response(status)

    async def _handle_agent_detail(self, request: web.Request) -> web.Response:
        """GET /api/agents/{agent_id} — single agent detail."""
        agent_id = request.match_info["agent_id"]
        agent = self.orchestrator.agents.get(agent_id)
        if not agent:
            return web.json_response({"error": "Agent not found"}, status=404)

        return web.json_response({
            "agent_id": agent.agent_id,
            "name": agent.config.name,
            "state": agent.state.value,
            "identity_id": agent.identity_id,
            "credits_used": agent.credits_used,
            "credits_remaining": agent.credits_remaining,
            "credits_budget": agent.config.credit_budget,
            "decisions_made": len(agent.decisions),
            "privilege": agent.config.max_privilege.value,
            "allowed_servers": agent.config.allowed_mcp_servers,
        })

    async def _handle_agent_decisions(self, request: web.Request) -> web.Response:
        """GET /api/agents/{agent_id}/decisions — audit trail."""
        agent_id = request.match_info["agent_id"]
        agent = self.orchestrator.agents.get(agent_id)
        if not agent:
            return web.json_response({"error": "Agent not found"}, status=404)

        return web.json_response(agent.get_audit_log())

    async def _handle_spawn_agent(self, request: web.Request) -> web.Response:
        """POST /api/agents — spawn a new agent."""
        try:
            body = await request.json()
            agent = await self.orchestrator.spawn_agent(
                name=body.get("name", "unnamed"),
                credit_budget=body.get("credit_budget", 1000.0),
                allowed_servers=body.get("allowed_servers"),
            )
            await self.orchestrator.start_agent(agent.agent_id)
            return web.json_response({
                "agent_id": agent.agent_id,
                "name": agent.config.name,
                "state": agent.state.value,
            }, status=201)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def _handle_submit_goal(self, request: web.Request) -> web.Response:
        """POST /api/agents/{agent_id}/goal — submit a high-level goal."""
        agent_id = request.match_info["agent_id"]
        agent = self.orchestrator.agents.get(agent_id)
        if not agent:
            return web.json_response({"error": "Agent not found"}, status=404)

        body = await request.json()
        goal = body.get("goal", "")
        if not goal:
            return web.json_response({"error": "goal is required"}, status=400)

        await agent.submit_goal(goal, priority=body.get("priority", 5))
        return web.json_response({"status": "submitted", "goal": goal})

    async def _handle_stop_agent(self, request: web.Request) -> web.Response:
        """DELETE /api/agents/{agent_id} — stop an agent."""
        agent_id = request.match_info["agent_id"]
        try:
            await self.orchestrator.stop_agent(agent_id)
            return web.json_response({"status": "stopped"})
        except KeyError:
            return web.json_response({"error": "Agent not found"}, status=404)
