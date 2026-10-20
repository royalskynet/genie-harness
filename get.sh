#!/usr/bin/env bash
# Genie Harness: install or update in one line, for whichever hosts are on this machine.
#   curl -fsSL https://raw.githubusercontent.com/royalskynet/genie-harness/main/get.sh | bash
# Only one host: append `-s claude` or `-s codex`. Safe to re-run; an existing install is updated.
#   Claude Code: marketplace add/update, then plugin install, or router/safe_update.py when already
#                installed (keeps the old version for sessions still running it).
#   Codex:       clone to ~/genie-harness and run install.sh, or run the latest update.sh.
set -euo pipefail
REPO=royalskynet/genie-harness
KEY=genie-harness@genie-harness
PLUGINS="$HOME/.claude/plugins"
want="${1:-auto}"

json_has() {  # json_has <file> <python expr on d>: exit 0 when the expression is truthy
  [ -f "$1" ] && python3 -c "import json,sys;d=json.load(open(sys.argv[1]));sys.exit(0 if ($2) else 1)" "$1"
}

do_claude() {
  if json_has "$PLUGINS/known_marketplaces.json" "'genie-harness' in d"; then
    claude plugin marketplace update genie-harness
  else
    claude plugin marketplace add "$REPO"
  fi
  if json_has "$PLUGINS/installed_plugins.json" "d.get('plugins',{}).get('$KEY')"; then
    loc=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['genie-harness']['installLocation'])" "$PLUGINS/known_marketplaces.json")
    python3 "$loc/router/safe_update.py" "$KEY"
  else
    claude plugin install "$KEY"
  fi
  echo "genie: Claude Code done. Restart Claude Code to load it."
}

do_codex() {
  d="$HOME/genie-harness"
  if [ -d "$d/.git" ]; then
    git -C "$d" fetch -q origin main
    bash <(git -C "$d" show FETCH_HEAD:update.sh) "$d"
  else
    git clone -q "https://github.com/$REPO" "$d"
    bash "$d/install.sh"
  fi
  echo "genie: Codex done. Restart Codex to load it."
}

main() {
  case "$want" in
    claude) do_claude ;;
    codex) do_codex ;;
    auto)
      ran=0
      if command -v claude >/dev/null; then do_claude; ran=1; fi
      if command -v codex >/dev/null || [ -d "$HOME/genie-harness/.git" ]; then do_codex; ran=1; fi
      if [ "$ran" = 0 ]; then
        echo "genie: neither claude nor codex found on PATH. Install one first, or pass -s claude / -s codex." >&2
        exit 1
      fi ;;
    *) echo "genie: unknown host '$want' (use claude or codex)" >&2; exit 2 ;;
  esac
}

# Run only after the whole script is read (curl | bash), with stdin off the pipe.
main </dev/null
