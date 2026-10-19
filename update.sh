#!/usr/bin/env bash
# Genie Harness updater: pull the latest code, then re-run install.sh
# (idempotent: refreshes hooks, trust hashes and skill links; keeps backups).
# Usage: bash update.sh [install-dir]  (dir arg is for running this file from
# git show, where BASH_SOURCE is a pipe, not the checkout).
set -euo pipefail
HERE="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
git -C "$HERE" fetch -q origin main
if ! git -C "$HERE" merge -q --ff-only FETCH_HEAD 2>/dev/null; then
  # Upstream history was rewritten once (2026-10-19), so an old checkout cannot
  # fast-forward. Never throw away local edits; keep the old tip on a branch.
  if [ -n "$(git -C "$HERE" status --porcelain --untracked-files=no)" ]; then
    echo "genie: $HERE has local edits, not updated. Commit or revert them, then re-run." >&2
    exit 1
  fi
  b="genie-before-update-$(date +%Y%m%d%H%M%S)"
  git -C "$HERE" branch -q "$b" HEAD
  git -C "$HERE" reset -q --hard FETCH_HEAD
  echo "genie: upstream history was rewritten; now on the latest version. Old version kept on branch $b."
fi
exec bash "$HERE/install.sh"
