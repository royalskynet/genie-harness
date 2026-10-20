#!/usr/bin/env bash
# Genie Harness: install or update in one line, for whichever hosts are on this machine.
#   curl -fsSL https://raw.githubusercontent.com/royalskynet/genie-harness/main/get.sh | bash
# Only one host: append `-s claude` or `-s codex`. Safe to re-run; an existing install is updated.
#   Claude Code: marketplace add/update, then plugin install, or router/safe_update.py when already
#                installed (keeps the old version for sessions still running it).
#   Codex:       clone to ~/genie-harness and run install.sh, or run the latest update.sh.
# Add-ons (separate repos): wheel (prior-art search, used by $wheel and the wheel gate) is installed by
# default, `--no-wheel` skips it. fixindex and ponytail only on request: `--with fixindex,ponytail` or
# `--with all`. Example: curl -fsSL .../get.sh | bash -s -- claude --with all
set -euo pipefail
REPO=royalskynet/genie-harness
KEY=genie-harness@genie-harness
PLUGINS="$HOME/.claude/plugins"
want=auto; with=""; wheel=1
while [ $# -gt 0 ]; do
  case "$1" in
    --with) with="${2:-}"; shift ;;
    --with=*) with="${1#--with=}" ;;
    --no-wheel) wheel=0 ;;
    *) want="$1" ;;
  esac
  shift
done
case ",$with," in *,all,*) with=fixindex,ponytail ;; esac
for a in ${with//,/ }; do
  case "$a" in fixindex|ponytail|wheel) ;; *) echo "genie: unknown add-on '$a' (use fixindex, ponytail, all)" >&2; exit 2 ;; esac
done
case "$want" in auto|claude|codex) ;; *) echo "genie: unknown host '$want' (use claude or codex)" >&2; exit 2 ;; esac
wants() { case ",$with," in *,"$1",*) return 0 ;; *) return 1 ;; esac; }
has_claude() { [ "$want" = claude ] || { [ "$want" = auto ] && command -v claude >/dev/null; }; }
has_codex() { [ "$want" = codex ] || { [ "$want" = auto ] && { command -v codex >/dev/null || [ -d "$HOME/genie-harness/.git" ]; }; }; }

clone_or_pull() {  # clone_or_pull <github owner/repo> <dir>
  if [ -d "$2/.git" ]; then
    git -C "$2" pull -q --ff-only || echo "genie: $2 has local changes or diverged, left as is" >&2
  else
    mkdir -p "$(dirname "$2")" && git clone -q "https://github.com/$1" "$2"
  fi
}

do_wheel() {
  local dir="${GENIE_WHEEL_UPSTREAM:-$HOME/dev/wheel}"
  clone_or_pull royalskynet/wheel-it "$dir"
  # Codex: install.sh links it. Claude Code: a user-level skill, unless one is already there.
  if has_claude && [ ! -e "$HOME/.claude/skills/wheel" ] && [ ! -e "$HOME/.claude/commands/wheel.md" ]; then
    mkdir -p "$HOME/.claude/skills" && ln -s "$dir/skills/wheel" "$HOME/.claude/skills/wheel"
  fi
  echo "genie: wheel ready ($dir)"
}

do_fixindex() {
  local dir="$HOME/dev/fixindex"
  clone_or_pull royalskynet/fixindex "$dir"
  bash "$dir/install.sh" >/dev/null
  mkdir -p "$HOME/notes/runbook/fixes"
  command -v rg >/dev/null || echo "genie: fixindex needs ripgrep (macOS: brew install ripgrep)" >&2
  echo "genie: fixindex ready. Add to your shell profile: export FIXINDEX_DIR=\$HOME/notes/runbook/fixes"
}

do_ponytail() {
  if has_claude; then
    json_has "$PLUGINS/known_marketplaces.json" "'ponytail' in d" || claude plugin marketplace add DietrichGebert/ponytail
    json_has "$PLUGINS/installed_plugins.json" "d.get('plugins',{}).get('ponytail@ponytail')" || claude plugin install ponytail@ponytail
    echo "genie: ponytail ready for Claude Code"
  fi
  if has_codex; then
    codex plugin marketplace add DietrichGebert/ponytail || true
    echo "genie: ponytail added to Codex; open /plugins in Codex to install it"
  fi
}

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
  if ! has_claude && ! has_codex; then
    echo "genie: neither claude nor codex found on PATH. Install one first, or pass -s claude / -s codex." >&2
    exit 1
  fi
  # Add-ons first: Codex install.sh links wheel only if its clone is already there.
  if [ "$wheel" = 1 ]; then do_wheel; fi
  if wants fixindex; then do_fixindex; fi
  if wants ponytail; then do_ponytail; fi
  if has_claude; then do_claude; fi
  if has_codex; then do_codex; fi
}

# Run only after the whole script is read (curl | bash), with stdin off the pipe.
main </dev/null
