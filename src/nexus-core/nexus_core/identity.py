"""Identity — unified identity for humans and agents across all devices."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger("nexus.identity")


class IdentityType(str, Enum):
    HUMAN = "human"
    AGENT = "agent"
    SERVICE = "service"


class IdentityProvider(str, Enum):
    NEXUS = "nexus"       # Native Nexus Directory
    ENTRA = "entra"       # Microsoft Entra ID (Azure AD)
    HYBRID = "hybrid"     # Both synced


@dataclass
class NexusIdentity:
    """
    Unified identity that works for both humans and AI agents.

    Every entity in NexusOS gets a single NexusIdentity that follows
    them across all devices. This is a first-class citizen in the
    identity system — agents are not second-class users.
    """

    identity_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    display_name: str = ""
    identity_type: IdentityType = IdentityType.HUMAN
    provider: IdentityProvider = IdentityProvider.NEXUS
    email: str = ""
    upn: str = ""  # User Principal Name (user@domain.com or agent@domain.com)
    groups: list[str] = field(default_factory=list)
    privilege_level: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    devices: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Entra ID fields (populated when provider is entra or hybrid)
    entra_object_id: str | None = None
    entra_tenant_id: str | None = None

    @property
    def is_agent(self) -> bool:
        return self.identity_type == IdentityType.AGENT

    @property
    def is_human(self) -> bool:
        return self.identity_type == IdentityType.HUMAN

    def has_group(self, group: str) -> bool:
        return group in self.groups


class IdentityManager:
    """
    Manages identities across Nexus Directory and Microsoft Entra ID.

    Supports three modes:
    - nexus: Native LDAP-compatible directory only
    - entra: Microsoft Entra ID (Azure AD) only
    - hybrid: Both synced, Nexus Directory as primary
    """

    def __init__(self, provider: IdentityProvider = IdentityProvider.NEXUS):
        self.provider = provider
        self._identities: dict[str, NexusIdentity] = {}
        self._entra_client: Any = None

    async def initialize(
        self,
        entra_tenant_id: str = "",
        entra_client_id: str = "",
        entra_authority: str = "https://login.microsoftonline.com",
    ) -> None:
        """Initialize the identity manager and connect to providers."""
        logger.info("Initializing IdentityManager (provider=%s)", self.provider.value)

        if self.provider in (IdentityProvider.ENTRA, IdentityProvider.HYBRID):
            await self._init_entra(entra_tenant_id, entra_client_id, entra_authority)

        if self.provider in (IdentityProvider.NEXUS, IdentityProvider.HYBRID):
            await self._init_nexus_directory()

        logger.info("IdentityManager initialized.")

    async def _init_entra(
        self, tenant_id: str, client_id: str, authority: str
    ) -> None:
        """Initialize Microsoft Entra ID (Azure AD) connection."""
        try:
            from msal import ConfidentialClientApplication

            self._entra_client = ConfidentialClientApplication(
                client_id=client_id,
                authority=f"{authority}/{tenant_id}",
            )
            logger.info("Entra ID client initialized for tenant %s", tenant_id)
        except ImportError:
            logger.warning("MSAL not installed; Entra ID integration unavailable.")
        except Exception:
            logger.exception("Failed to initialize Entra ID client.")

    async def _init_nexus_directory(self) -> None:
        """Initialize native Nexus Directory (LDAP) connection."""
        # TODO: Connect to local nexus-directory service
        logger.info("Nexus Directory connection initialized.")

    async def create_identity(
        self,
        display_name: str,
        identity_type: IdentityType = IdentityType.HUMAN,
        email: str = "",
        groups: list[str] | None = None,
        privilege_level: int = 1,
    ) -> NexusIdentity:
        """Create a new identity (human or agent)."""
        domain = "nexus.local"  # TODO: from config
        upn_prefix = display_name.lower().replace(" ", ".")

        identity = NexusIdentity(
            display_name=display_name,
            identity_type=identity_type,
            provider=self.provider,
            email=email or f"{upn_prefix}@{domain}",
            upn=f"{upn_prefix}@{domain}",
            groups=groups or [],
            privilege_level=privilege_level,
        )

        self._identities[identity.identity_id] = identity
        logger.info(
            "Created %s identity: %s (%s)",
            identity_type.value, display_name, identity.upn,
        )

        # Sync to Entra if hybrid
        if self.provider == IdentityProvider.HYBRID:
            await self._sync_to_entra(identity)

        return identity

    async def get_identity(self, identity_id: str) -> NexusIdentity | None:
        """Look up an identity by ID."""
        return self._identities.get(identity_id)

    async def find_by_upn(self, upn: str) -> NexusIdentity | None:
        """Find an identity by User Principal Name."""
        for identity in self._identities.values():
            if identity.upn == upn:
                return identity
        return None

    async def authenticate(self, upn: str, credential: str) -> NexusIdentity | None:
        """
        Authenticate a user or agent.

        For agents, the credential is a signed token.
        For humans, it's handled via PAM/Kerberos/Entra.
        """
        identity = await self.find_by_upn(upn)
        if not identity:
            logger.warning("Authentication failed: unknown UPN %s", upn)
            return None

        # TODO: Actual credential verification
        # - For Nexus: verify against local directory
        # - For Entra: verify via MSAL token
        # - For agents: verify cryptographic signature

        identity.last_seen = datetime.now(timezone.utc)
        logger.info("Authenticated: %s (%s)", identity.display_name, upn)
        return identity

    async def register_device(self, identity_id: str, device_id: str) -> None:
        """Register a device for cross-device identity sync."""
        identity = self._identities.get(identity_id)
        if identity and device_id not in identity.devices:
            identity.devices.append(device_id)
            logger.info(
                "Device %s registered for %s", device_id, identity.display_name
            )

    async def _sync_to_entra(self, identity: NexusIdentity) -> None:
        """Sync an identity to Microsoft Entra ID."""
        if not self._entra_client:
            return
        # TODO: Use Microsoft Graph API to create/update user in Entra
        logger.debug("Syncing identity %s to Entra ID", identity.upn)

    async def sync_from_entra(self) -> int:
        """Pull identities from Entra ID into Nexus Directory."""
        if not self._entra_client:
            return 0
        # TODO: Use Microsoft Graph API to list users and sync
        logger.info("Syncing identities from Entra ID...")
        return 0

    def list_identities(
        self, identity_type: IdentityType | None = None
    ) -> list[NexusIdentity]:
        """List all identities, optionally filtered by type."""
        identities = list(self._identities.values())
        if identity_type:
            identities = [i for i in identities if i.identity_type == identity_type]
        return identities
