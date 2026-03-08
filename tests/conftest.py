"""Pytest configuration for NexusOS tests."""

import sys
from pathlib import Path

# Add source packages to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "nexus-core"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "nexus-directory"))
