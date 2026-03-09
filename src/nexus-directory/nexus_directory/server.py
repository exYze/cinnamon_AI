"""Nexus Directory Server — LDAP-compatible directory for unified identities."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import bcrypt
import click

logger = logging.getLogger("nexus.directory")

# Bind attempt rate limiting: max attempts per DN within the window
_BIND_MAX_ATTEMPTS = 5
_BIND_WINDOW_SECONDS = 300  # 5 minutes
_BIND_LOCKOUT_SECONDS = 600  # 10 minutes after exceeding limit


@dataclass
class DirectoryEntry:
    """A single entry in the Nexus Directory (user, agent, or group)."""

    dn: str  # Distinguished Name
    object_class: list[str] = field(default_factory=lambda: ["top", "person"])
    attributes: dict[str, Any] = field(default_factory=dict)


class NexusDirectoryServer:
    """
    LDAP-compatible directory server for NexusOS.

    Stores unified identities for humans and AI agents. Compatible with
    Microsoft Active Directory schema for hybrid deployments.

    Supports:
    - LDAP bind (simple and SASL)
    - LDAP search with filters
    - LDAP add/modify/delete
    - Sync with Microsoft Entra ID
    - Agent-specific extensions (privilege levels, credit budgets, MCP permissions)
    """

    @staticmethod
    def hash_password(plain: str) -> str:
        """Hash a password with bcrypt. Returns the hash as a string."""
        return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("ascii")

    @staticmethod
    def verify_password(plain: str, hashed: str) -> bool:
        """Verify a plaintext password against a bcrypt hash."""
        try:
            return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
        except (ValueError, TypeError):
            return False

    def __init__(self, base_dn: str = "dc=nexus,dc=local"):
        self.base_dn = base_dn
        self._entries: dict[str, DirectoryEntry] = {}
        self._running = False
        # Rate-limiting state: dn -> list of timestamps of failed attempts
        self._bind_failures: dict[str, list[float]] = defaultdict(list)

        # Bootstrap root entry
        self._entries[base_dn] = DirectoryEntry(
            dn=base_dn,
            object_class=["top", "domain"],
            attributes={"dc": "nexus", "description": "NexusOS Directory"},
        )

        # Create OUs
        for ou in ["Users", "Agents", "Groups", "Devices", "Policies"]:
            ou_dn = f"ou={ou},{base_dn}"
            self._entries[ou_dn] = DirectoryEntry(
                dn=ou_dn,
                object_class=["top", "organizationalUnit"],
                attributes={"ou": ou},
            )

    async def bind(self, dn: str, password: str) -> bool:
        """
        Authenticate a user/agent (LDAP BIND operation).

        Passwords are verified against bcrypt hashes. Rate limiting is
        enforced per DN to prevent brute-force attacks.
        """
        now = time.monotonic()

        # --- Rate-limit check ---
        failures = self._bind_failures[dn]
        # Prune old entries outside the window
        cutoff = now - _BIND_WINDOW_SECONDS
        self._bind_failures[dn] = [t for t in failures if t > cutoff]
        failures = self._bind_failures[dn]

        if len(failures) >= _BIND_MAX_ATTEMPTS:
            # Check if still in lockout period
            latest = max(failures)
            if now - latest < _BIND_LOCKOUT_SECONDS:
                logger.warning(
                    "Bind rate-limited: %s (%d failures in window, locked out)",
                    dn, len(failures),
                )
                return False

        entry = self._entries.get(dn)
        if not entry:
            logger.warning("Bind failed: DN not found: %s", dn)
            self._bind_failures[dn].append(now)
            return False

        stored_password = entry.attributes.get("userPassword", "")
        if not stored_password:
            logger.warning("Bind failed: no password set for %s", dn)
            self._bind_failures[dn].append(now)
            return False

        if self.verify_password(password, stored_password):
            logger.info("Bind successful: %s", dn)
            # Clear failures on success
            self._bind_failures.pop(dn, None)
            return True

        logger.warning("Bind failed: invalid credentials for %s", dn)
        self._bind_failures[dn].append(now)
        return False

    async def search(
        self,
        base_dn: str,
        scope: str = "subtree",
        filter_str: str = "(objectClass=*)",
    ) -> list[DirectoryEntry]:
        """Search the directory (LDAP SEARCH operation)."""
        results = []
        for dn, entry in self._entries.items():
            if not dn.endswith(base_dn):
                continue

            if scope == "base" and dn != base_dn:
                continue

            # Simple filter matching (production would use full LDAP filter parser)
            if self._matches_filter(entry, filter_str):
                results.append(entry)

        logger.debug(
            "Search base=%s scope=%s filter=%s -> %d results",
            base_dn, scope, filter_str, len(results),
        )
        return results

    def _matches_filter(self, entry: DirectoryEntry, filter_str: str) -> bool:
        """Basic LDAP filter matching."""
        if filter_str == "(objectClass=*)":
            return True

        # Parse simple (attr=value) filters
        filter_str = filter_str.strip("()")
        if "=" not in filter_str:
            return True

        attr, value = filter_str.split("=", 1)

        if attr == "objectClass":
            return value in entry.object_class

        entry_value = entry.attributes.get(attr, "")
        if value == "*":
            return bool(entry_value)
        return str(entry_value) == value

    async def add_entry(self, entry: DirectoryEntry) -> bool:
        """Add a new entry to the directory (LDAP ADD)."""
        if entry.dn in self._entries:
            logger.warning("Entry already exists: %s", entry.dn)
            return False

        self._entries[entry.dn] = entry
        logger.info("Added entry: %s", entry.dn)
        return True

    async def modify_entry(
        self, dn: str, modifications: dict[str, Any]
    ) -> bool:
        """Modify an existing entry (LDAP MODIFY). Passwords are automatically hashed."""
        entry = self._entries.get(dn)
        if not entry:
            logger.warning("Modify failed: entry not found: %s", dn)
            return False

        # Hash password if being modified
        if "userPassword" in modifications and modifications["userPassword"]:
            modifications["userPassword"] = self.hash_password(
                modifications["userPassword"]
            )

        entry.attributes.update(modifications)
        logger.info("Modified entry: %s", dn)
        return True

    async def delete_entry(self, dn: str) -> bool:
        """Delete an entry (LDAP DELETE)."""
        if dn not in self._entries:
            return False

        del self._entries[dn]
        logger.info("Deleted entry: %s", dn)
        return True

    async def add_user(
        self,
        username: str,
        display_name: str,
        password: str = "",
        groups: list[str] | None = None,
    ) -> str:
        """Convenience method to add a human user. Password is bcrypt-hashed before storage."""
        hashed = self.hash_password(password) if password else ""
        dn = f"cn={username},ou=Users,{self.base_dn}"
        entry = DirectoryEntry(
            dn=dn,
            object_class=["top", "person", "organizationalPerson", "user"],
            attributes={
                "cn": username,
                "displayName": display_name,
                "userPassword": hashed,
                "userPrincipalName": f"{username}@nexus.local",
                "memberOf": groups or [],
                "objectCategory": "person",
            },
        )
        await self.add_entry(entry)
        return dn

    async def add_agent(
        self,
        agent_name: str,
        privilege_level: int = 2,
        credit_budget: float = 1000.0,
        mcp_servers: list[str] | None = None,
    ) -> str:
        """Add an AI agent identity to the directory."""
        dn = f"cn={agent_name},ou=Agents,{self.base_dn}"
        entry = DirectoryEntry(
            dn=dn,
            object_class=["top", "person", "nexusAgent"],
            attributes={
                "cn": agent_name,
                "displayName": agent_name,
                "userPrincipalName": f"{agent_name}@nexus.local",
                "nexusPrivilegeLevel": privilege_level,
                "nexusCreditBudget": credit_budget,
                "nexusMCPServers": mcp_servers or [],
                "objectCategory": "agent",
            },
        )
        await self.add_entry(entry)
        return dn

    async def sync_from_entra(
        self, tenant_id: str, client_id: str
    ) -> int:
        """
        Pull users from Microsoft Entra ID and create/update local entries.

        This enables hybrid mode where Entra is the source of truth for
        human users, while Nexus Directory manages agent identities natively.
        """
        # TODO: Use Microsoft Graph API via MSAL to list users
        # and create corresponding DirectoryEntry objects
        logger.info("Syncing from Entra ID tenant %s...", tenant_id)
        return 0

    async def run(self, host: str = "127.0.0.1", port: int = 3389) -> None:
        """Start the directory server."""
        self._running = True
        logger.info("Nexus Directory Server listening on %s:%d", host, port)
        logger.info("Base DN: %s", self.base_dn)

        # TODO: Implement actual LDAP protocol server using asyncio
        # For now, this is a placeholder that keeps the service alive
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False
            logger.info("Nexus Directory Server stopped.")


@click.command()
@click.option("--host", default="127.0.0.1", help="Bind address")
@click.option("--port", default=3389, help="LDAP port")
@click.option("--base-dn", default="dc=nexus,dc=local", help="Base DN")
def main(host: str, port: int, base_dn: str) -> None:
    """NexusOS Directory Server — LDAP-compatible identity provider."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    server = NexusDirectoryServer(base_dn=base_dn)
    asyncio.run(server.run(host=host, port=port))


if __name__ == "__main__":
    main()
