"""Security primitives — rate limiting and input validation for NexusOS."""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("nexus.security")


# ---------------------------------------------------------------------------
# Rate Limiter — Token-bucket algorithm per agent
# ---------------------------------------------------------------------------

@dataclass
class _Bucket:
    """Token bucket for a single agent."""

    tokens: float
    last_refill: float
    max_tokens: float
    refill_rate: float  # tokens per second


class RateLimiter:
    """
    Per-agent token-bucket rate limiter.

    Each agent gets a bucket that refills at `refill_rate` tokens/sec
    up to `max_tokens`. Each tool invocation consumes 1 token.
    When the bucket is empty, requests are denied until tokens refill.

    Args:
        max_tokens: Maximum burst capacity per agent (default 30).
        refill_rate: Tokens restored per second (default 2.0 = 120/min).
    """

    def __init__(self, max_tokens: int = 30, refill_rate: float = 2.0):
        self.max_tokens = max_tokens
        self.refill_rate = refill_rate
        self._buckets: dict[str, _Bucket] = {}

    def _get_bucket(self, agent_id: str) -> _Bucket:
        if agent_id not in self._buckets:
            self._buckets[agent_id] = _Bucket(
                tokens=float(self.max_tokens),
                last_refill=time.monotonic(),
                max_tokens=float(self.max_tokens),
                refill_rate=self.refill_rate,
            )
        return self._buckets[agent_id]

    def allow(self, agent_id: str, cost: float = 1.0) -> bool:
        """
        Check whether an agent is allowed to make a request.

        Returns True and consumes a token, or False if rate-limited.
        """
        bucket = self._get_bucket(agent_id)
        now = time.monotonic()

        # Refill tokens based on elapsed time
        elapsed = now - bucket.last_refill
        bucket.tokens = min(
            bucket.max_tokens,
            bucket.tokens + elapsed * bucket.refill_rate,
        )
        bucket.last_refill = now

        if bucket.tokens >= cost:
            bucket.tokens -= cost
            return True

        logger.warning(
            "Rate limit exceeded for agent %s (%.1f tokens available, %.1f needed)",
            agent_id, bucket.tokens, cost,
        )
        return False

    def get_status(self, agent_id: str) -> dict[str, Any]:
        """Get rate limiter status for an agent."""
        bucket = self._get_bucket(agent_id)
        return {
            "tokens_available": round(bucket.tokens, 1),
            "max_tokens": bucket.max_tokens,
            "refill_rate": bucket.refill_rate,
        }


# ---------------------------------------------------------------------------
# Input Validator — Schema-based validation for MCP tool arguments
# ---------------------------------------------------------------------------

# Characters that could indicate injection in various contexts
_DANGEROUS_PATTERNS = [
    re.compile(r"[;&|`$]"),          # Shell metacharacters
    re.compile(r"\.\./"),            # Path traversal
    re.compile(r"(?i)<script"),      # XSS
    re.compile(r"(?i);\s*drop\s"),   # SQL injection
    re.compile(r"(?i);\s*delete\s"), # SQL injection
    re.compile(r"\x00"),             # Null bytes
]

# Per-server tool schemas defining allowed tools and argument constraints
# This is the enforcement layer — tools not listed here are denied
_TOOL_SCHEMAS: dict[str, dict[str, "ToolSchema"]] = {}


@dataclass
class ArgConstraint:
    """Constraint for a single tool argument."""

    type: str = "string"            # string, int, float, bool, path, enum
    required: bool = False
    max_length: int = 4096          # max string length
    min_value: float | None = None  # for numeric types
    max_value: float | None = None
    pattern: str | None = None      # regex the value must match
    allowed_values: list[str] | None = None  # for enum type
    allow_shell_chars: bool = False  # if True, skip dangerous-char check


@dataclass
class ToolSchema:
    """Schema for a single MCP tool, defining allowed arguments."""

    name: str
    description: str = ""
    args: dict[str, ArgConstraint] = field(default_factory=dict)
    max_total_size: int = 65536     # max total JSON size of arguments


class ValidationError(Exception):
    """Raised when tool arguments fail validation."""

    def __init__(self, tool: str, field: str, reason: str):
        self.tool = tool
        self.field = field
        self.reason = reason
        super().__init__(f"Validation failed for {tool}.{field}: {reason}")


class InputValidator:
    """
    Validates MCP tool arguments against registered schemas.

    If no schema is registered for a server+tool, the invocation is
    denied by default (allowlist model). Generic safety checks
    (injection patterns, size limits) are always applied.
    """

    def __init__(self, strict: bool = True):
        self.strict = strict  # if True, deny tools with no schema
        self._schemas: dict[str, dict[str, ToolSchema]] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register built-in tool schemas for known MCP servers."""
        # Filesystem server
        self.register_tool("filesystem", ToolSchema(
            name="read_file",
            description="Read a file's contents",
            args={
                "path": ArgConstraint(type="path", required=True, max_length=1024),
            },
        ))
        self.register_tool("filesystem", ToolSchema(
            name="write_file",
            description="Write content to a file",
            args={
                "path": ArgConstraint(type="path", required=True, max_length=1024),
                "content": ArgConstraint(type="string", required=True, max_length=1_000_000),
            },
        ))
        self.register_tool("filesystem", ToolSchema(
            name="list_directory",
            description="List files in a directory",
            args={
                "path": ArgConstraint(type="path", required=True, max_length=1024),
            },
        ))
        self.register_tool("filesystem", ToolSchema(
            name="search_files",
            description="Search for files matching a pattern",
            args={
                "path": ArgConstraint(type="path", required=True, max_length=1024),
                "pattern": ArgConstraint(type="string", required=True, max_length=256),
            },
        ))

        # Credits server
        self.register_tool("credits", ToolSchema(
            name="get_balance",
            description="Get agent credit balance",
            args={
                "agent_id": ArgConstraint(type="string", required=True, max_length=64,
                                          pattern=r"^[a-zA-Z0-9_:-]+$"),
            },
        ))
        self.register_tool("credits", ToolSchema(
            name="get_usage",
            description="Get credit usage history",
            args={
                "agent_id": ArgConstraint(type="string", required=True, max_length=64,
                                          pattern=r"^[a-zA-Z0-9_:-]+$"),
                "limit": ArgConstraint(type="int", required=False, min_value=1, max_value=1000),
            },
        ))

        # Identity server
        self.register_tool("identity", ToolSchema(
            name="search",
            description="Search directory entries",
            args={
                "filter": ArgConstraint(type="string", required=True, max_length=512),
                "base_dn": ArgConstraint(type="string", required=False, max_length=256,
                                         pattern=r"^[a-zA-Z0-9=,. _-]+$"),
            },
        ))
        self.register_tool("identity", ToolSchema(
            name="lookup",
            description="Lookup a specific entry by DN",
            args={
                "dn": ArgConstraint(type="string", required=True, max_length=256,
                                    pattern=r"^[a-zA-Z0-9=,. _@-]+$"),
            },
        ))

        # Process server
        self.register_tool("process", ToolSchema(
            name="list",
            description="List running processes",
            args={},
        ))
        self.register_tool("process", ToolSchema(
            name="start",
            description="Start a process",
            args={
                "command": ArgConstraint(type="string", required=True, max_length=1024,
                                        pattern=r"^[a-zA-Z0-9/._-]+$"),
                "args": ArgConstraint(type="string", required=False, max_length=2048),
            },
        ))

        # Database server
        self.register_tool("database", ToolSchema(
            name="query",
            description="Execute a read-only SQL query",
            args={
                "sql": ArgConstraint(type="string", required=True, max_length=4096),
                "params": ArgConstraint(type="string", required=False, max_length=2048),
            },
        ))

    def register_tool(self, server: str, schema: ToolSchema) -> None:
        """Register a tool schema for validation."""
        if server not in self._schemas:
            self._schemas[server] = {}
        self._schemas[server][schema.name] = schema

    def validate(
        self, server: str, tool: str, arguments: dict[str, Any]
    ) -> list[ValidationError]:
        """
        Validate tool arguments against the registered schema.

        Returns a list of validation errors (empty = valid).
        """
        errors: list[ValidationError] = []

        # Check total argument size
        try:
            import json
            arg_json = json.dumps(arguments)
            if len(arg_json) > 65536:
                errors.append(ValidationError(
                    tool, "__total__",
                    f"Total argument size {len(arg_json)} exceeds limit 65536",
                ))
                return errors  # Don't continue if payload is too large
        except (TypeError, ValueError):
            errors.append(ValidationError(tool, "__total__", "Arguments not serializable"))
            return errors

        # Look up schema
        server_schemas = self._schemas.get(server)
        if not server_schemas:
            if self.strict:
                errors.append(ValidationError(
                    tool, "__server__",
                    f"No schemas registered for server '{server}'",
                ))
            else:
                self._check_generic_safety(tool, arguments, errors)
            return errors

        schema = server_schemas.get(tool)
        if not schema:
            if self.strict:
                errors.append(ValidationError(
                    tool, "__tool__",
                    f"Tool '{tool}' not in allowlist for server '{server}'",
                ))
            else:
                self._check_generic_safety(tool, arguments, errors)
            return errors

        # Validate each argument against constraints
        for arg_name, constraint in schema.args.items():
            value = arguments.get(arg_name)

            if value is None and constraint.required:
                errors.append(ValidationError(tool, arg_name, "Required argument missing"))
                continue

            if value is None:
                continue

            self._validate_arg(tool, arg_name, value, constraint, errors)

        # Check for unexpected arguments not in schema
        known_args = set(schema.args.keys())
        for arg_name in arguments:
            if arg_name not in known_args:
                errors.append(ValidationError(
                    tool, arg_name, "Unexpected argument not in schema",
                ))

        return errors

    def _validate_arg(
        self,
        tool: str,
        name: str,
        value: Any,
        constraint: ArgConstraint,
        errors: list[ValidationError],
    ) -> None:
        """Validate a single argument against its constraint."""
        str_value = str(value)

        # Type checking
        if constraint.type == "int":
            if not isinstance(value, int):
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    errors.append(ValidationError(tool, name, f"Expected int, got {type(value).__name__}"))
                    return
        elif constraint.type == "float":
            if not isinstance(value, (int, float)):
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    errors.append(ValidationError(tool, name, f"Expected float, got {type(value).__name__}"))
                    return
        elif constraint.type == "bool":
            if not isinstance(value, bool):
                errors.append(ValidationError(tool, name, f"Expected bool, got {type(value).__name__}"))
                return

        # String/path length
        if constraint.type in ("string", "path") and len(str_value) > constraint.max_length:
            errors.append(ValidationError(
                tool, name,
                f"Length {len(str_value)} exceeds max {constraint.max_length}",
            ))
            return

        # Numeric range
        if constraint.type in ("int", "float"):
            num_value = float(value)
            if constraint.min_value is not None and num_value < constraint.min_value:
                errors.append(ValidationError(
                    tool, name, f"Value {num_value} below minimum {constraint.min_value}",
                ))
            if constraint.max_value is not None and num_value > constraint.max_value:
                errors.append(ValidationError(
                    tool, name, f"Value {num_value} above maximum {constraint.max_value}",
                ))

        # Pattern match
        if constraint.pattern and not re.fullmatch(constraint.pattern, str_value):
            errors.append(ValidationError(
                tool, name,
                f"Value does not match required pattern {constraint.pattern}",
            ))

        # Enum check
        if constraint.allowed_values and str_value not in constraint.allowed_values:
            errors.append(ValidationError(
                tool, name,
                f"Value '{str_value}' not in allowed values: {constraint.allowed_values}",
            ))

        # Path traversal check
        if constraint.type == "path":
            if ".." in str_value:
                errors.append(ValidationError(tool, name, "Path traversal detected (..)"))
            if "\x00" in str_value:
                errors.append(ValidationError(tool, name, "Null byte in path"))

        # Dangerous character check (unless explicitly allowed)
        if not constraint.allow_shell_chars:
            for pattern in _DANGEROUS_PATTERNS:
                if pattern.search(str_value):
                    errors.append(ValidationError(
                        tool, name,
                        f"Dangerous pattern detected: {pattern.pattern}",
                    ))
                    break

    def _check_generic_safety(
        self, tool: str, arguments: dict[str, Any], errors: list[ValidationError]
    ) -> None:
        """Apply generic safety checks when no schema is available."""
        for name, value in arguments.items():
            str_value = str(value)
            if len(str_value) > 65536:
                errors.append(ValidationError(tool, name, f"Value too large ({len(str_value)} chars)"))
            for pattern in _DANGEROUS_PATTERNS:
                if pattern.search(str_value):
                    errors.append(ValidationError(
                        tool, name,
                        f"Dangerous pattern detected: {pattern.pattern}",
                    ))
                    break
