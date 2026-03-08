.PHONY: build-iso install-deps test lint clean dev-setup

SHELL := /bin/bash
ISO_NAME := nexus-os
ISO_VERSION := 0.1.0
MINT_VERSION := 22
MINT_EDITION := cinnamon
WORK_DIR := $(CURDIR)/work
OUT_DIR := $(CURDIR)/out

# Development setup
dev-setup:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt
	.venv/bin/pip install -e src/nexus-core
	.venv/bin/pip install -e src/nexus-directory
	@echo "Development environment ready. Activate with: source .venv/bin/activate"

# Install build dependencies (requires root on Linux)
install-deps:
	sudo apt-get update
	sudo apt-get install -y \
		squashfs-tools \
		genisoimage \
		xorriso \
		isolinux \
		syslinux-utils \
		debootstrap \
		rsync \
		git \
		python3-venv \
		python3-pip

# Run tests
test:
	.venv/bin/pytest tests/ -v --tb=short

# Run tests with coverage
test-cov:
	.venv/bin/pytest tests/ -v --cov=nexus_core --cov-report=term-missing

# Lint
lint:
	.venv/bin/ruff check src/ tests/
	.venv/bin/mypy src/nexus-core/nexus_core/ --ignore-missing-imports

# Format
format:
	.venv/bin/ruff format src/ tests/

# Build the ISO (must run on Linux or WSL)
build-iso:
	@echo "Building $(ISO_NAME) $(ISO_VERSION)..."
	mkdir -p $(OUT_DIR)
	sudo bash build.sh \
		--mint-version $(MINT_VERSION) \
		--mint-edition $(MINT_EDITION) \
		--work-dir $(WORK_DIR) \
		--output $(OUT_DIR)/$(ISO_NAME)-$(ISO_VERSION).iso
	@echo "ISO built: $(OUT_DIR)/$(ISO_NAME)-$(ISO_VERSION).iso"

# Clean build artifacts
clean:
	rm -rf $(WORK_DIR) $(OUT_DIR) .venv
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true

# Quick clean (keep .venv)
clean-build:
	rm -rf $(WORK_DIR) $(OUT_DIR)
