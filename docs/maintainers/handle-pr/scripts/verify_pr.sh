#!/usr/bin/env bash
# Verify a pull request in an isolated worktree: fast tests, release check, frontend build.
#
# Usage: docs/maintainers/handle-pr/scripts/verify_pr.sh <PR number> [--keep]
#
# This EXECUTES the PR's code (tests and scripts). Read the whole diff first, especially
# .github/, Dockerfile, requirements.txt, scripts/ and conftest.py.
# It never touches the development database. Integration tests and real-channel checks are
# separate steps, see README.md.
set -euo pipefail

PR="${1:-}"
KEEP="${2:-}"
[[ "$PR" =~ ^[0-9]+$ ]] || { echo "usage: $0 <PR number> [--keep]" >&2; exit 2; }

ROOT="$(git rev-parse --show-toplevel)"
BRANCH="pr-$PR"
WORKTREE="/tmp/five-pr$PR"
PYTEST="$ROOT/.venv/bin/pytest"
PYTHON="$ROOT/.venv/bin/python"
[ -x "$PYTEST" ] || { echo "missing $PYTEST, run ./service.sh install first" >&2; exit 1; }

cleanup() {
    if [ "$KEEP" != "--keep" ]; then
        rm -f "$WORKTREE/frontend/node_modules" 2>/dev/null || true
        git -C "$ROOT" worktree remove --force "$WORKTREE" 2>/dev/null || true
        git -C "$ROOT" branch -D "$BRANCH" >/dev/null 2>&1 || true
        echo "==> cleaned worktree and branch (use --keep to retain them)"
    else
        echo "==> kept $WORKTREE and branch $BRANCH, remove them yourself when finished"
    fi
}
trap cleanup EXIT

[ ! -e "$WORKTREE" ] || { echo "$WORKTREE already exists, remove it first" >&2; exit 1; }

echo "==> fetching PR #$PR"
timeout 90 git -C "$ROOT" fetch origin "pull/$PR/head:$BRANCH"
git -C "$ROOT" worktree add "$WORKTREE" "$BRANCH" >/dev/null
echo "    head: $(git -C "$WORKTREE" log --oneline -1)"

CHANGED="$(git -C "$ROOT" diff --name-only "origin/main...$BRANCH" 2>/dev/null || git -C "$ROOT" diff --name-only "main...$BRANCH")"

echo "==> fast tests (compare with the baseline on main)"
( cd "$WORKTREE/backend" && timeout 900 "$PYTEST" -q 2>&1 | tail -2 )

echo "==> release check"
( cd "$WORKTREE" && "$PYTHON" backend/scripts/release_check.py )

if [ -z "$CHANGED" ]; then
    echo "    cannot tell which files changed (already merged?), running every step"
    CHANGED="frontend/"
fi

if grep -q '^frontend/' <<<"$CHANGED"; then
    echo "==> frontend build (type check included)"
    ln -s "$ROOT/frontend/node_modules" "$WORKTREE/frontend/node_modules"
    ( cd "$WORKTREE/frontend" && timeout 280 npm run build 2>&1 | grep -E "error|built in|✓ built" || true )
    rm -f "$WORKTREE/frontend/node_modules"
else
    echo "==> frontend untouched, build skipped"
fi

if grep -q '^backend/migrations/\|^backend/app/models/' <<<"$CHANGED"; then
    echo "!! models or migrations changed: also test a fresh install and a legacy upgrade against a disposable DB"
fi
if grep -q '^\.github/\|^Dockerfile\|requirements' <<<"$CHANGED"; then
    echo "!! supply-chain files changed: re-read them before merging"
fi
echo "==> done. Baseline count is on main; skipped count should be unchanged."
