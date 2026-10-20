#!/usr/bin/env bash
# Genie Harness: install or update in one line, for whichever hosts are on this machine.
#   curl -fsSL https://raw.githubusercontent.com/royalskynet/genie-harness/main/get.sh | bash
#   curl -fsSL .../get.sh | bash -s -- --all        # full install
# Args: [claude|codex] (default: every host found)  [--all]  [-y|--yes]
#
# Genie itself: installed when missing, updated when behind, skipped when already latest.
#   Claude Code updates go through router/safe_update.py (old version kept for open sessions).
# Add-ons, each its own repo: wheel (prior-art search behind $wheel and the wheel gate),
#   fixindex (personal fix log), ponytail (minimal-code mode).
#   Default: asks one by one for each add-on that is missing; installed ones are left alone.
#   --all:   installs every missing add-on without asking; for installed ones (Genie too) asks
#            before updating, and skips what is already latest.
#   -y:      yes to every question.
# Questions are read from the terminal, so they work under curl | bash. With no terminal
# (CI, an agent running it), default mode installs no add-on and --all answers yes.
set -euo pipefail
REPO=royalskynet/genie-harness
KEY=genie-harness@genie-harness
PLUGINS="$HOME/.claude/plugins"
TTY="${GENIE_TTY:-/dev/tty}"  # GENIE_TTY: tests feed answers from a file
want=auto; full=0; yes=0
while [ $# -gt 0 ]; do
  case "$1" in
    --all) full=1 ;;
    -y|--yes) yes=1 ;;
    claude|codex) want="$1" ;;
    *) echo "genie: unknown argument '$1' (use claude, codex, --all, -y)" >&2; exit 2 ;;
  esac
  shift
done

has_claude() { [ "$want" = claude ] || { [ "$want" = auto ] && command -v claude >/dev/null; }; }
has_codex() { [ "$want" = codex ] || { [ "$want" = auto ] && { command -v codex >/dev/null || [ -d "$HOME/genie-harness/.git" ]; }; }; }
say() { echo "genie: $*"; }

# ask <question> <answer with no terminal: y|n>. The terminal default is yes (Enter).
ask() {
  [ "$yes" = 1 ] && return 0
  local a
  if { : <&3; } 2>/dev/null; then  # fd 3 is open only when a terminal (or GENIE_TTY) is there
    [ "$TTY" = /dev/tty ] && printf 'genie: %s [Y/n] ' "$1" >/dev/tty
    read -r a <&3 || a=""
    case "${a:-y}" in [yY]*) return 0 ;; *) return 1 ;; esac
  fi
  [ "$2" = y ]
}

json_has() {  # json_has <file> <python expr on d>: exit 0 when the expression is truthy
  [ -f "$1" ] && python3 -c "import json,sys;d=json.load(open(sys.argv[1]));sys.exit(0 if ($2) else 1)" "$1"
}

# plugin_state <name@marketplace>: prints missing, latest or behind. Refreshes the marketplace first.
plugin_state() {
  local key="$1" mkt="${1#*@}"
  json_has "$PLUGINS/installed_plugins.json" "d.get('plugins',{}).get('$key')" || { echo missing; return; }
  claude plugin marketplace update "$mkt" >/dev/null 2>&1 || true
  python3 - "$PLUGINS" "$key" <<'PY'
import json, os, sys
plugins, key = sys.argv[1], sys.argv[2]
name, mkt = key.split("@", 1)
have = {e.get("version") for e in json.load(open(os.path.join(plugins, "installed_plugins.json")))["plugins"][key]}
try:
    loc = json.load(open(os.path.join(plugins, "known_marketplaces.json")))[mkt]["installLocation"]
    entry = next(p for p in json.load(open(os.path.join(loc, ".claude-plugin", "marketplace.json")))["plugins"]
                 if p["name"] == name)
    src = entry.get("source")
    latest = entry.get("version") or (json.load(open(os.path.join(loc, src, ".claude-plugin", "plugin.json")))["version"]
                                      if isinstance(src, str) else None)
except (OSError, KeyError, StopIteration, ValueError):
    latest = None  # cannot tell -> treat as behind, the update itself decides
print("latest" if latest and have == {latest} else "behind")
PY
}

# git_state <dir>: missing, latest or behind (fetches first).
git_state() {
  [ -d "$1/.git" ] || { echo missing; return; }
  git -C "$1" fetch -q 2>/dev/null || true
  local n; n=$(git -C "$1" rev-list --count 'HEAD..@{u}' 2>/dev/null || echo 0)
  if [ "${n:-0}" -gt 0 ]; then echo behind; else echo latest; fi
}

# handle <label> <state> <what it is> <install fn> <update fn>: the one place the modes differ.
handle() {
  local label="$1" state="$2" what="$3"
  case "$state" in
    missing)
      if [ "$full" = 1 ] || ask "$label is not installed ($what). Install it?" n; then "$4"
      else say "$label skipped (install later with --all)"; fi ;;
    latest) say "$label already latest" ;;
    behind)
      if [ "$full" = 0 ]; then say "$label installed, update available (run with --all to update)"
      elif ask "$label has an update. Update it?" y; then "$5"
      else say "$label update skipped"; fi ;;
  esac
}

genie_loc() { python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['genie-harness']['installLocation'])" "$PLUGINS/known_marketplaces.json"; }

# --- Genie on Claude Code ---
claude_genie_install() {
  json_has "$PLUGINS/known_marketplaces.json" "'genie-harness' in d" || claude plugin marketplace add "$REPO"
  claude plugin install "$KEY"
  say "Genie installed for Claude Code. Restart Claude Code to load it."
}
claude_genie_update() {
  python3 "$(genie_loc)/router/safe_update.py" "$KEY"
  say "Genie updated for Claude Code. Restart Claude Code to load it."
}
do_claude_genie() {
  case "$(plugin_state "$KEY")" in
    missing) claude_genie_install ;;
    latest) say "Genie (Claude Code) already latest" ;;
    behind)
      if [ "$full" = 0 ] || ask "Genie (Claude Code) has an update. Update it?" y; then claude_genie_update
      else say "Genie (Claude Code) update skipped"; fi ;;
  esac
}

# --- Genie on Codex ---
CODEX_DIR="$HOME/genie-harness"
codex_genie_install() {
  git clone -q "https://github.com/$REPO" "$CODEX_DIR"
  bash "$CODEX_DIR/install.sh"
  say "Genie installed for Codex. Restart Codex to load it."
}
codex_genie_update() {
  bash <(git -C "$CODEX_DIR" show FETCH_HEAD:update.sh) "$CODEX_DIR"
  say "Genie updated for Codex. Restart Codex to load it."
}
do_codex_genie() {
  [ -d "$CODEX_DIR/.git" ] || { codex_genie_install; return; }
  git -C "$CODEX_DIR" fetch -q origin main
  if [ "$(git -C "$CODEX_DIR" rev-parse HEAD)" = "$(git -C "$CODEX_DIR" rev-parse FETCH_HEAD)" ]; then
    say "Genie (Codex) already latest"
  elif [ "$full" = 0 ] || ask "Genie (Codex) has an update. Update it?" y; then codex_genie_update
  else say "Genie (Codex) update skipped"; fi
}

# --- wheel ---
WHEEL_DIR="${GENIE_WHEEL_UPSTREAM:-$HOME/dev/wheel}"
own_wheel() { [ -e "$HOME/.claude/skills/wheel" ] || [ -e "$HOME/.claude/commands/wheel.md" ]; }
wheel_install() {
  mkdir -p "$(dirname "$WHEEL_DIR")"
  git clone -q https://github.com/royalskynet/wheel-it "$WHEEL_DIR"
  # Claude Code: a user skill, unless the user already has one. Codex: install.sh links it.
  if has_claude && ! own_wheel; then
    mkdir -p "$HOME/.claude/skills" && ln -s "$WHEEL_DIR/skills/wheel" "$HOME/.claude/skills/wheel"
  fi
  say "wheel installed ($WHEEL_DIR)"
}
wheel_update() {
  if git -C "$WHEEL_DIR" pull -q --ff-only; then say "wheel updated"; else say "wheel has local changes, left as is"; fi
}
wheel_state() {
  local s; s=$(git_state "$WHEEL_DIR")
  if [ "$s" = missing ] && has_claude && own_wheel; then s=latest; fi  # the user's own wheel counts
  echo "$s"
}

# --- fixindex ---
FIX_DIR="$HOME/dev/fixindex"
if command -v fixindex >/dev/null; then  # follow an existing install to its clone
  d=$(dirname "$(readlink -f "$(command -v fixindex)" 2>/dev/null || command -v fixindex)")
  [ -d "$d/.git" ] && FIX_DIR="$d"
fi
fixindex_install() {
  mkdir -p "$(dirname "$FIX_DIR")"
  git clone -q https://github.com/royalskynet/fixindex "$FIX_DIR"
  bash "$FIX_DIR/install.sh" >/dev/null
  mkdir -p "$HOME/notes/runbook/fixes"
  command -v rg >/dev/null || say "fixindex needs ripgrep (macOS: brew install ripgrep)"
  say "fixindex installed. Add to your shell profile: export FIXINDEX_DIR=\$HOME/notes/runbook/fixes"
}
fixindex_update() {
  if git -C "$FIX_DIR" pull -q --ff-only; then bash "$FIX_DIR/install.sh" >/dev/null; say "fixindex updated"
  else say "fixindex has local changes, left as is"; fi
}
fixindex_state() {
  local s; s=$(git_state "$FIX_DIR")
  if [ "$s" = missing ] && command -v fixindex >/dev/null; then s=latest; fi  # installed some other way
  echo "$s"
}

# --- ponytail ---
ponytail_install() {
  if has_claude; then
    json_has "$PLUGINS/known_marketplaces.json" "'ponytail' in d" || claude plugin marketplace add DietrichGebert/ponytail
    claude plugin install ponytail@ponytail
  fi
  if has_codex; then
    codex plugin marketplace add DietrichGebert/ponytail || true
    say "ponytail added to Codex; open /plugins in Codex to install it"
  fi
  say "ponytail installed"
}
ponytail_update() {
  python3 "$(genie_loc)/router/safe_update.py" ponytail@ponytail
  say "ponytail updated"
}
ponytail_state() {
  if has_claude; then plugin_state ponytail@ponytail
  elif ls -d "${CODEX_HOME:-$HOME/.codex}"/plugins/cache/*/ponytail >/dev/null 2>&1; then echo latest  # Codex updates it from /plugins
  else echo missing; fi
}

main() {
  if ! has_claude && ! has_codex; then
    echo "genie: neither claude nor codex found on PATH. Install one first, or pass claude / codex." >&2
    exit 1
  fi
  if has_claude; then do_claude_genie; fi
  # Add-ons before Codex: its install.sh links wheel only if the clone is already there.
  handle wheel "$(wheel_state)" "finds existing tools before building, used by \$wheel" wheel_install wheel_update
  handle fixindex "$(fixindex_state)" "a personal fix log, looked up when something breaks" fixindex_install fixindex_update
  handle ponytail "$(ponytail_state)" "keeps the code the model writes minimal" ponytail_install ponytail_update
  if has_codex; then do_codex_genie; fi
}

# Run only after the whole script is read (curl | bash), with stdin off the pipe.
# fd 3 is the answer source for ask(): the terminal, or GENIE_TTY in tests.
if { exec 3<"$TTY"; } 2>/dev/null; then :; fi
main </dev/null
