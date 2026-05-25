#!/bin/bash
#
# create_afk_worktree.sh
#
# Helper for the /afk orchestrator.
# Creates an isolated git worktree + branch for a given agent (autonomous) issue number.
#
# Usage:
#   ./create_afk_worktree.sh 42
#
# Output (on success):
#   WORKTREE=/home/czaby/w/grok-afk-worktrees/issue-42
#   BRANCH=afk/42
#   ISSUE=42
#
# Note: While the skill now uses the `agent` label on GitHub issues,
# we keep the `afk/` branch prefix by convention for worktree branches.
#
# The orchestrator should parse these lines (or capture the whole output) and
# embed the paths into the subagent prompt + session state.
#
# Safety: will refuse to overwrite an existing worktree/branch for the same issue.

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <issue-number>" >&2
    echo "  (issue-number must be a positive integer per documented convention)" >&2
    exit 1
fi

ISSUE="$1"

# Harden: numeric validation for reliable discovery/creation (issue #25)
if ! [[ "$ISSUE" =~ ^[0-9]+$ ]]; then
    echo "ERROR: issue-number must be a positive integer (got: $ISSUE)." >&2
    exit 1
fi

# Resolve paths relative to this script's location (works even if called from elsewhere)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The main repo root is one level above the .grok/skills/afk directory
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

WORKTREE_BASE="${REPO_ROOT}/../grok-afk-worktrees"
WORKTREE_PATH="${WORKTREE_BASE}/issue-${ISSUE}"
BRANCH="afk/${ISSUE}"

echo "Creating AFK worktree for issue #${ISSUE}..." >&2
echo "  Repo root:   ${REPO_ROOT}" >&2
echo "  Worktree:    ${WORKTREE_PATH}" >&2
echo "  Branch:      ${BRANCH}" >&2

# Harden: verify git repo (reliable discovery precondition)
if ! git -C "${REPO_ROOT}" rev-parse --git-dir >/dev/null 2>&1; then
    echo "ERROR: ${REPO_ROOT} is not a valid git repository." >&2
    exit 1
fi

mkdir -p "${WORKTREE_BASE}"

# Reliable pre-discovery using git worktree list (in addition to direct checks)
# Helps detect stale or conflicting worktrees for the same issue per convention.
if git -C "${REPO_ROOT}" worktree list --porcelain 2>/dev/null | grep -q "branch refs/heads/${BRANCH}"; then
    echo "ERROR: Branch ${BRANCH} already exists (discovered via git worktree list)." >&2
    echo "       Use 'git worktree list' and clean up manually if this is a stale AFK worker." >&2
    exit 1
fi

# Check if the worktree or branch already exists
if git -C "${REPO_ROOT}" rev-parse --verify "${BRANCH}" >/dev/null 2>&1; then
    echo "ERROR: Branch ${BRANCH} already exists." >&2
    echo "       Use 'git worktree list' and clean up manually if this is a stale AFK worker." >&2
    exit 1
fi

if [[ -d "${WORKTREE_PATH}" ]]; then
    echo "ERROR: Directory ${WORKTREE_PATH} already exists." >&2
    exit 1
fi

# Create the worktree on a new branch from the current HEAD (usually main)
git -C "${REPO_ROOT}" worktree add -b "${BRANCH}" "${WORKTREE_PATH}"

echo
echo "SUCCESS"
echo "WORKTREE=${WORKTREE_PATH}"
echo "BRANCH=${BRANCH}"
echo "ISSUE=${ISSUE}"
echo
echo "Next steps for the orchestrator:"
echo "  1. Record WORKTREE and BRANCH in .grok/afk-session.json"
echo "  2. The GitHub issue should have the 'agent' label (not 'afk')."
echo "  2. Prepend the CRITICAL WORKTREE block (with these exact paths) to the worker prompt"
echo "  3. Spawn the subagent"