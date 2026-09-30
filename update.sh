#!/usr/bin/env bash
# Genie Harness updater: pull the latest code, then re-run install.sh
# (idempotent: refreshes hooks, trust hashes and skill links; keeps backups).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
git -C "$HERE" pull --ff-only
exec bash "$HERE/install.sh"
