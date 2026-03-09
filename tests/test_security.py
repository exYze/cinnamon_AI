"""Tests for NexusOS security features: password hashing, rate limiting, input validation."""

import asyncio
import time

import pytest

from nexus_core.security import InputValidator, RateLimiter, ValidationError


# ---------------------------------------------------------------------------
# Rate Limiter Tests
# ---------------------------------------------------------------------------

class TestRateLimiter:
    def test_allows_requests_within_limit(self):
        limiter = RateLimiter(max_tokens=5, refill_rate=1.0)
        for _ in range(5):
            assert limiter.allow("agent-1") is True

    def test_blocks_requests_over_limit(self):
        limiter = RateLimiter(max_tokens=3, refill_rate=0.0)  # no refill
        assert limiter.allow("agent-1") is True
        assert limiter.allow("agent-1") is True
        assert limiter.allow("agent-1") is True
        assert limiter.allow("agent-1") is False

    def test_separate_buckets_per_agent(self):
        limiter = RateLimiter(max_tokens=2, refill_rate=0.0)
        assert limiter.allow("agent-1") is True
        assert limiter.allow("agent-1") is True
        assert limiter.allow("agent-1") is False
        # agent-2 should still have tokens
        assert limiter.allow("agent-2") is True

    def test_tokens_refill_over_time(self):
        limiter = RateLimiter(max_tokens=2, refill_rate=100.0)  # fast refill
        assert limiter.allow("agent-1") is True
        assert limiter.allow("agent-1") is True
        # Should refill quickly at 100 tokens/sec
        time.sleep(0.05)
        assert limiter.allow("agent-1") is True

    def test_get_status(self):
        limiter = RateLimiter(max_tokens=10, refill_rate=2.0)
        limiter.allow("agent-1")
        status = limiter.get_status("agent-1")
        assert status["max_tokens"] == 10.0
        assert status["refill_rate"] == 2.0
        assert status["tokens_available"] <= 10.0


# ---------------------------------------------------------------------------
# Input Validator Tests
# ---------------------------------------------------------------------------

class TestInputValidator:
    @pytest.fixture
    def validator(self):
        return InputValidator(strict=True)

    def test_valid_filesystem_read(self, validator):
        errors = validator.validate("filesystem", "read_file", {
            "path": "/var/log/nexus/agent.log",
        })
        assert errors == []

    def test_valid_filesystem_write(self, validator):
        errors = validator.validate("filesystem", "write_file", {
            "path": "/tmp/output.txt",
            "content": "Hello, world!",
        })
        assert errors == []

    def test_missing_required_argument(self, validator):
        errors = validator.validate("filesystem", "read_file", {})
        assert len(errors) == 1
        assert errors[0].field == "path"
        assert "Required" in errors[0].reason

    def test_path_traversal_blocked(self, validator):
        errors = validator.validate("filesystem", "read_file", {
            "path": "/etc/../../etc/shadow",
        })
        assert any("traversal" in e.reason.lower() for e in errors)

    def test_shell_injection_blocked(self, validator):
        errors = validator.validate("filesystem", "read_file", {
            "path": "/tmp/file; rm -rf /",
        })
        assert len(errors) > 0
        assert any("Dangerous" in e.reason or "pattern" in e.reason.lower() for e in errors)

    def test_null_byte_blocked(self, validator):
        errors = validator.validate("filesystem", "read_file", {
            "path": "/tmp/file\x00.txt",
        })
        assert any("Null byte" in e.reason or "Dangerous" in e.reason for e in errors)

    def test_unexpected_argument_rejected(self, validator):
        errors = validator.validate("filesystem", "read_file", {
            "path": "/tmp/file.txt",
            "evil_param": "something",
        })
        assert any("Unexpected" in e.reason for e in errors)

    def test_unknown_tool_rejected_strict(self, validator):
        errors = validator.validate("filesystem", "delete_everything", {})
        assert any("allowlist" in e.reason.lower() for e in errors)

    def test_unknown_server_rejected_strict(self, validator):
        errors = validator.validate("evil_server", "hack", {"target": "localhost"})
        assert any("No schemas" in e.reason for e in errors)

    def test_string_length_limit(self, validator):
        errors = validator.validate("filesystem", "read_file", {
            "path": "a" * 2000,
        })
        assert any("Length" in e.reason for e in errors)

    def test_numeric_range_validation(self, validator):
        errors = validator.validate("credits", "get_usage", {
            "agent_id": "test-001",
            "limit": 99999,
        })
        assert any("maximum" in e.reason.lower() for e in errors)

    def test_pattern_validation(self, validator):
        errors = validator.validate("credits", "get_balance", {
            "agent_id": "valid-agent_123",
        })
        assert errors == []

        errors = validator.validate("credits", "get_balance", {
            "agent_id": "agent; DROP TABLE",
        })
        assert len(errors) > 0

    def test_non_strict_mode_allows_unknown_tools(self):
        validator = InputValidator(strict=False)
        errors = validator.validate("unknown_server", "unknown_tool", {
            "safe_arg": "safe_value",
        })
        assert errors == []

    def test_non_strict_still_catches_injection(self):
        validator = InputValidator(strict=False)
        errors = validator.validate("unknown_server", "unknown_tool", {
            "evil_arg": "value; rm -rf /",
        })
        assert len(errors) > 0

    def test_oversized_payload_rejected(self, validator):
        errors = validator.validate("filesystem", "write_file", {
            "path": "/tmp/big.txt",
            "content": "x" * 2_000_000,
        })
        assert any("exceeds" in e.reason.lower() or "Length" in e.reason for e in errors)

    def test_sql_injection_blocked(self, validator):
        errors = validator.validate("filesystem", "read_file", {
            "path": "/tmp/file; DROP TABLE users",
        })
        assert len(errors) > 0

    def test_xss_blocked(self, validator):
        errors = validator.validate("filesystem", "write_file", {
            "path": "/tmp/safe.txt",
            "content": "<script>alert('xss')</script>",
        })
        assert any("Dangerous" in e.reason for e in errors)


# ---------------------------------------------------------------------------
# Password Hashing Tests (Directory Server)
# ---------------------------------------------------------------------------

class TestPasswordHashing:
    def test_hash_and_verify(self):
        from nexus_directory.server import NexusDirectoryServer
        hashed = NexusDirectoryServer.hash_password("mysecretpassword")
        assert hashed != "mysecretpassword"
        assert hashed.startswith("$2")  # bcrypt prefix
        assert NexusDirectoryServer.verify_password("mysecretpassword", hashed) is True
        assert NexusDirectoryServer.verify_password("wrongpassword", hashed) is False

    def test_different_salts(self):
        from nexus_directory.server import NexusDirectoryServer
        h1 = NexusDirectoryServer.hash_password("same")
        h2 = NexusDirectoryServer.hash_password("same")
        assert h1 != h2  # different salts produce different hashes
        assert NexusDirectoryServer.verify_password("same", h1) is True
        assert NexusDirectoryServer.verify_password("same", h2) is True

    @pytest.mark.asyncio
    async def test_add_user_hashes_password(self):
        from nexus_directory.server import NexusDirectoryServer
        server = NexusDirectoryServer()
        dn = await server.add_user("alice", "Alice Smith", password="hunter2")
        entry = server._entries[dn]
        stored = entry.attributes["userPassword"]
        assert stored != "hunter2"
        assert stored.startswith("$2")

    @pytest.mark.asyncio
    async def test_bind_with_hashed_password(self):
        from nexus_directory.server import NexusDirectoryServer
        server = NexusDirectoryServer()
        dn = await server.add_user("bob", "Bob Jones", password="correct-horse")
        assert await server.bind(dn, "correct-horse") is True
        assert await server.bind(dn, "wrong-password") is False

    @pytest.mark.asyncio
    async def test_modify_entry_hashes_password(self):
        from nexus_directory.server import NexusDirectoryServer
        server = NexusDirectoryServer()
        dn = await server.add_user("carol", "Carol", password="old-pass")
        await server.modify_entry(dn, {"userPassword": "new-pass"})
        entry = server._entries[dn]
        stored = entry.attributes["userPassword"]
        assert stored.startswith("$2")
        assert await server.bind(dn, "new-pass") is True
        assert await server.bind(dn, "old-pass") is False


# ---------------------------------------------------------------------------
# Bind Rate Limiting Tests
# ---------------------------------------------------------------------------

class TestBindRateLimiting:
    @pytest.mark.asyncio
    async def test_lockout_after_failed_attempts(self):
        from nexus_directory.server import NexusDirectoryServer
        server = NexusDirectoryServer()
        dn = await server.add_user("eve", "Eve", password="secret")

        # Exhaust attempts with wrong password
        for _ in range(5):
            assert await server.bind(dn, "wrong") is False

        # Now even the correct password should be locked out
        assert await server.bind(dn, "secret") is False

    @pytest.mark.asyncio
    async def test_successful_bind_resets_failures(self):
        from nexus_directory.server import NexusDirectoryServer
        server = NexusDirectoryServer()
        dn = await server.add_user("frank", "Frank", password="pass123")

        # A few failures
        await server.bind(dn, "wrong1")
        await server.bind(dn, "wrong2")

        # Successful bind should clear failures
        assert await server.bind(dn, "pass123") is True

        # Should be able to fail again without immediate lockout
        assert await server.bind(dn, "wrong3") is False
        assert await server.bind(dn, "pass123") is True
