#!/bin/sh
# Claude Code SessionStart: a plugin's CLAUDE.md is never loaded, so the rules
# arrive as this hook's stdout. Also fetches the router model on first use;
# install.sh does that for Codex, a marketplace install has no install step.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cat "$ROOT/AGENTS.md"

# macOS without Command Line Tools has a /usr/bin/python3 stub that only opens
# an install dialog, so test that it runs, not that it exists.
if ! python3 -c "" 2>/dev/null; then
  echo
  echo "Genie setup: python3 is missing, so intent routing and the guard are off."
  echo "Tell the user in one sentence, and offer to run: xcode-select --install (macOS) or install python3."
  exit 0
fi
# Static prefs once per session (and again after /compact or /clear): a
# UserPromptSubmit copy every turn stays in the transcript and piles up.
echo
python3 "$ROOT/router/prefs.py" context 2>/dev/null

MODEL="$HOME/.genie/model"
[ -f "$ROOT/router/model/vocab.json" ] || [ -f "$MODEL/vocab.json" ] && exit 0
if ! python3 -c "import numpy" 2>/dev/null; then
  echo
  echo "Genie setup: numpy is missing, so the intent router runs on keywords only."
  echo "Tell the user in one sentence, and offer to run: python3 -m pip install --user numpy"
  exit 0
fi
mkdir -p "$HOME/.genie"
# A crashed download leaves the lock behind; retry after an hour.
find "$HOME/.genie/model.lock" -maxdepth 0 -mmin +60 -exec rmdir {} \; 2>/dev/null
# mkdir is atomic: one download even if several sessions start at once.
mkdir "$HOME/.genie/model.lock" 2>/dev/null || exit 0
( GENIE_MODEL_DIR="$MODEL" python3 "$ROOT/router/setup_model.py" \
    >"$HOME/.genie/setup.log" 2>&1; rmdir "$HOME/.genie/model.lock" ) </dev/null >/dev/null 2>&1 &
echo
echo "Genie setup: downloading the intent model in the background (one time, ~512 MB, a few minutes)."
