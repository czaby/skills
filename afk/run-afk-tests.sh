#!/bin/bash
#
# run-afk-tests.sh
#
# Docker-first test runner for the AFK skill snapshot builder (and future afk modules).
# Zero host installs or modifications (per grok.md, AGENTS.md Docker-first policy, and AFK Implementor Checklist).
#
# Usage (from repo root or afk dir):
#   .grok/skills/afk/run-afk-tests.sh
#   HEADED=0 .grok/skills/afk/run-afk-tests.sh   # (future)
#
# It runs pytest for AFK tests inside an official python Docker image (no local python/pip/pytest needed).
# Mounts the worktree read-only where possible for safety.
#
# Exit non-zero on any test failure (standard for CI/local verification).
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

echo "=== AFK Engine Tests (full suite: state_machine, translator, engine_flow+apply #24, etc.; Docker-first) ==="
echo "Repo root: ${REPO_ROOT}"
echo "Running inside python:3.12-slim (installs pytest in container only)..."
echo "Using PYTHONPATH=.grok/skills for correct package imports (afk.* + relative imports in modules)."
echo

# Use a clean python slim image; install only pytest (stdlib + pytest sufficient for our pure tests)
# PYTHONPATH set so "from afk.xxx" succeeds and relative imports (from .data_models) work inside modules.
docker run --rm \
  -v "${REPO_ROOT}:/workspace:ro" \
  -w /workspace \
  -e PYTHONPATH=.grok/skills \
  python:3.12-slim \
  bash -c '
    set -euo pipefail
    pip install -q --no-cache-dir pytest
    echo "pytest installed in container."
    python -m pytest .grok/skills/afk/tests/ -q --tb=short
  '

echo
echo "=== AFK tests completed successfully (or failed with details above) ==="