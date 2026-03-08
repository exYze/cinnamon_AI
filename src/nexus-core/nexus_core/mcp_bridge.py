"""MCP Bridge — connects agents to MCP servers for tool execution."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("nexus.mcp_bridge")


@dataclass
class ToolInvocation:
    """Audit record for a single MCP tool invocation."""

    invocation_id: str
    agent_id: str
    server: str
    tool: str
    arguments: dict[str, Any]
    result: dict[str, Any] | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: float = 0.0
    authorized: bool = True


class MCPServerConnection:
    """Manages a connection to a single MCP server."""

    def __init__(self, name: str, config: dict[str, Any]):
        self.name = name
        self.command = config.get("command", "")
        self.args = config.get("args", [])
        self.required_privilege = config.get("required_privilege", 1)
        self.auto_start = config.get("auto_start", False)
        self._process: asyncio.subprocess.Process | None = None
        self._connected = False

    async def connect(self) -> None:
        """Start the MCP server process and establish connection."""
        logger.info("Connecting to MCP server: %s (%s)", self.name, self.command)
        # TODO: Launch MCP server subprocess via stdio transport
        # self._process = await asyncio.create_subprocess_exec(
        #     self.command, *self.args,
        #     stdin=asyncio.subprocess.PIPE,
        #     stdout=asyncio.subprocess.PIPE,
        #     stderr=asyncio.subprocess.PIPE,
        # )
        self._connected = True
        logger.info("MCP server '%s' connected.", self.name)

    async def invoke(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke a tool on this MCP server."""
        if not self._connected:
            raise RuntimeError(f"MCP server '{self.name}' not connected.")

        # TODO: Send JSON-RPC call over stdio to MCP server
        logger.debug("MCP %s: invoking tool '%s'", self.name, tool)
        return {"status": "ok", "tool": tool, "server": self.name}

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if self._process:
            self._process.terminate()
            await self._process.wait()
        self._connected = False
        logger.info("MCP server '%s' disconnected.", self.name)

    @property
    def is_connected(self) -> bool:
        return self._connected


class MCPBridge:
    """
    Central bridge between agents and MCP servers.

    Handles:
    - Loading MCP server registry
    - Managing server connections
    - Routing agent tool calls to appropriate servers
    - Authorization checks per agent identity
    - Audit logging of all tool invocations
    """

    def __init__(self, registry_path: str = "/etc/nexus/mcp-registry.json"):
        self.registry_path = registry_path
        self.servers: dict[str, MCPServerConnection] = {}
        self.audit_log: list[ToolInvocation] = []
        self._invocation_counter = 0

    async def initialize(self) -> None:
        """Load registry and connect to auto-start servers."""
        registry_file = Path(self.registry_path)
        if not registry_file.exists():
            logger.warning("MCP registry not found at %s", self.registry_path)
            return

        registry = json.loads(registry_file.read_text())
        server_configs = registry.get("servers", {})

        for name, config in server_configs.items():
            conn = MCPServerConnection(name, config)
            self.servers[name] = conn

            if conn.auto_start:
                try:
                    await conn.connect()
                except Exception:
                    logger.exception("Failed to auto-start MCP server: %s", name)

        logger.info(
            "MCP Bridge initialized: %d servers loaded, %d auto-started.",
            len(self.servers),
            sum(1 for s in self.servers.values() if s.is_connected),
        )

    async def invoke_tool(
        self,
        agent_id: str,
        agent_privilege: int,
        server_name: str,
        tool: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Invoke a tool on behalf of an agent, with authorization and audit logging.
        """
        self._invocation_counter += 1
        invocation = ToolInvocation(
            invocation_id=f"inv-{self._invocation_counter:08d}",
            agent_id=agent_id,
            server=server_name,
            tool=tool,
            arguments=arguments,
        )

        # Check server exists
        server = self.servers.get(server_name)
        if not server:
            invocation.authorized = False
            invocation.result = {"error": f"Unknown MCP server: {server_name}"}
            self.audit_log.append(invocation)
            return invocation.result

        # Authorization check
        if agent_privilege < server.required_privilege:
            invocation.authorized = False
            invocation.result = {
                "error": f"Insufficient privilege for {server_name} "
                f"(required={server.required_privilege}, agent={agent_privilege})"
            }
            logger.warning(
                "Agent %s: denied access to %s.%s (privilege %d < %d)",
                agent_id, server_name, tool, agent_privilege,
                server.required_privilege,
            )
            self.audit_log.append(invocation)
            return invocation.result

        # Connect if needed
        if not server.is_connected:
            await server.connect()

        # Invoke
        start = asyncio.get_event_loop().time()
        try:
            result = await server.invoke(tool, arguments)
            invocation.result = result
        except Exception as e:
            invocation.result = {"error": str(e)}
            logger.exception("MCP invocation failed: %s.%s", server_name, tool)
        finally:
            invocation.duration_ms = (
                (asyncio.get_event_loop().time() - start) * 1000
            )

        self.audit_log.append(invocation)
        return invocation.result or {"error": "no result"}

    async def shutdown(self) -> None:
        """Disconnect all MCP servers."""
        for server in self.servers.values():
            if server.is_connected:
                await server.disconnect()
        logger.info("MCP Bridge shut down.")

    def get_audit_trail(self, agent_id: str | None = None) -> list[dict]:
        """Get audit trail, optionally filtered by agent."""
        entries = self.audit_log
        if agent_id:
            entries = [e for e in entries if e.agent_id == agent_id]

        return [
            {
                "id": e.invocation_id,
                "agent": e.agent_id,
                "server": e.server,
                "tool": e.tool,
                "authorized": e.authorized,
                "duration_ms": e.duration_ms,
                "timestamp": e.timestamp.isoformat(),
            }
            for e in entries
        ]
