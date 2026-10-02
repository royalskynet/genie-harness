#!/usr/bin/env bash
# Genie Harness installer. Re-runnable with first-run backups preserved.
#   1. numpy present?            (only runtime dep)
#   2. router model              (one-time ~512 MB download -> ~35 MB on disk)
#   3. skills  -> ~/.agents/skills/{genie-*,wheel}   (symlinks)
#   4. hook    -> ~/.codex/hooks.json        (merged, existing hooks kept)
#   5. AGENTS.md -> ~/.codex/AGENTS.md       (appended once, marker-guarded)
#   6. hook trust -> ~/.codex/config.toml
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEX="${CODEX_HOME:-$HOME/.codex}"
SKILLS="$HOME/.agents/skills"
MARK="<!-- genie-harness -->"

if grep -qsF genie_router.py "$CODEX/hooks.json"; then
  echo "genie-harness already installed -> refreshing (update mode)"
else
  echo "genie-harness not installed yet -> fresh install"
fi

if ! python3 -c "import numpy" 2>/dev/null; then
  echo "numpy is required by the router." >&2
  echo "Install it for this Python with: python3 -m pip install --user numpy" >&2
  echo "If pip reports externally-managed-environment (for example, Homebrew Python), use:" >&2
  echo "  python3 -m pip install --user --break-system-packages numpy" >&2
  echo "The --user option keeps numpy in your user site-packages." >&2
  exit 1
fi

[ -f "$HERE/router/model/vocab.json" ] || python3 "$HERE/router/setup_model.py"
python3 "$HERE/router/test_router.py" >/dev/null && echo "router self-check: PASS"

mkdir -p "$SKILLS" "$CODEX"

is_genie_link() {
  local dest="$1" name="$2" target
  [ -L "$dest" ] || return 1
  target="$(readlink "$dest")"
  case "$target" in
    */genie-harness/skills/"$name") return 0 ;;
    *) return 1 ;;
  esac
}

# Check every destination before replacing any, so an occupied backup path
# cannot leave the links half-installed.
for d in "$HERE"/skills/*; do
  name="$(basename "$d")"
  dest="$SKILLS/$name"
  backup="$dest.bak-genie"
  if [ -L "$dest" ] && [ "$(readlink "$dest")" = "$d" ]; then
    continue
  fi
  if is_genie_link "$dest" "$name"; then
    continue
  fi
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    if [ -e "$backup" ] || [ -L "$backup" ]; then
      echo "cannot replace $dest: backup already exists at $backup" >&2
      exit 1
    fi
  fi
done

A="$CODEX/AGENTS.md"
if ! grep -qF "$MARK" "$A" 2>/dev/null && [ -f "$A" ] &&
   { [ -e "$A.bak-genie" ] || [ -L "$A.bak-genie" ]; }; then
  echo "cannot append to $A: backup already exists at $A.bak-genie" >&2
  exit 1
fi

for d in "$HERE"/skills/*; do
  name="$(basename "$d")"
  dest="$SKILLS/$name"
  backup="$dest.bak-genie"
  if [ -L "$dest" ] && [ "$(readlink "$dest")" = "$d" ]; then
    continue
  elif is_genie_link "$dest" "$name"; then
    ln -sfn "$d" "$dest"
  else
    if [ -e "$dest" ] || [ -L "$dest" ]; then
      mv "$dest" "$backup"
    fi
    ln -s "$d" "$dest"
  fi
done
echo "skills linked -> $SKILLS"

# merge hook + trust it (python stdlib only; no jq).
# Codex refuses to run an untrusted hook and normally wants you to press
# "trust" in the TUI (/hooks). We write the same trust record it would write:
# hooks.state."<hooks.json>:user_prompt_submit:<i>:0".trusted_hash = sha256 of the
# canonical JSON identity (see codex-rs hooks/src/engine/discovery.rs hook_hash).
python3 - "$HERE" "$CODEX" <<'EOF'
import hashlib, json, os, re, shlex, shutil, sys
here, codex = sys.argv[1], sys.argv[2]
path, cfg = os.path.join(codex, "hooks.json"), os.path.join(codex, "config.toml")
PY = shlex.quote(sys.executable)
def _cmd(script):
    return "%s %s" % (PY, shlex.quote(os.path.join(here, "router", script)))
HOOKS = [
    ("UserPromptSubmit", None, "genie_router.py", 5),
    ("PreToolUse", "Bash|Write|Edit|apply_patch|MultiEdit", "guard_dangerous.py", 5),
]
data = {"hooks": {}}
already_installed = False
changed = False
if os.path.exists(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
# Scripts older versions registered that no longer exist (prefs_hook.py folded
# into genie_router.py). Drop them, or Codex runs a missing file every prompt.
RETIRED = ("prefs_hook.py",)
for _lst in data.get("hooks", {}).values():
    for _e in _lst:
        _keep = [hh for hh in _e.get("hooks", [])
                 if not any(r in hh.get("command", "") and "genie" in hh.get("command", "")
                            for r in RETIRED)]
        if len(_keep) != len(_e.get("hooks", [])):
            _e["hooks"] = _keep
            changed = True
            print("  removed retired genie hook")
# One registration entry per event, several hooks objects inside it (Codex
# hooks.json schema). Match entries/hooks by script filename, not by the last
# token of the quoted command (which breaks when the checkout path has spaces).
for _event in ("UserPromptSubmit", "PreToolUse"):
    _ev_hooks = [h for h in HOOKS if h[0] == _event]
    _scripts = [h[2] for h in _ev_hooks]
    _lst = data.setdefault("hooks", {}).setdefault(_event, [])
    _idx = next((i for i, e in enumerate(_lst)
                 if any(any(_s in hh.get("command", "") for _s in _scripts)
                        for hh in e.get("hooks", []))), None)
    if _idx is None:
        _entry = {"hooks": []}
        if _ev_hooks[0][1]:
            _entry["matcher"] = _ev_hooks[0][1]
        _lst.append(_entry)
        _idx = len(_lst) - 1
    else:
        already_installed = True
    for _m, _s, _t in [(h[1], h[2], h[3]) for h in _ev_hooks]:
        _c = _cmd(_s)
        _hooks = _lst[_idx].setdefault("hooks", [])
        _hidx = next((i for i, hh in enumerate(_hooks) if _s in hh.get("command", "")), None)
        if _hidx is None:
            _hooks.append({"type": "command", "command": _c, "timeout": _t})
            changed = True
            print("  added %s -> %s" % (_event, _s))
        elif _hooks[_hidx]["command"] != _c:
            _hooks[_hidx] = {"type": "command", "command": _c, "timeout": _t}
            changed = True
            print("  updated %s -> %s" % (_event, _s))
        else:
            print("  already present: %s" % _s)

def backup_once(filename):
    backup = filename + ".bak-genie"
    if os.path.lexists(filename) and not os.path.lexists(backup):
        shutil.copy2(filename, backup, follow_symlinks=False)

# trust entries for every hook we manage; identities must match Codex's
# hook_hash (see codex-rs hooks/src/engine/discovery.rs).
_sections = []
for _event, _matcher, _script, _timeout in HOOKS:
    _key = "UserPromptSubmit" if _event == "UserPromptSubmit" else "PreToolUse"
    _tkey = "user_prompt_submit" if _event == "UserPromptSubmit" else "pre_tool_use"
    _lst = data["hooks"][_key]
    _idx = next((i for i, e in enumerate(_lst)
                 if any(_script in h.get("command", "") for h in e.get("hooks", []))), None)
    if _idx is None:
        continue
    _hooks = _lst[_idx]["hooks"]
    _hidx = next(i for i, h in enumerate(_hooks) if _script in h.get("command", ""))
    ident = {"event_name": _tkey,
             "hooks": [{"type": "command", "command": _hooks[_hidx]["command"],
                        "timeout": _timeout, "async": False}]}
    _m = _lst[_idx].get("matcher")
    if _m is not None:
        ident["matcher"] = _m
    digest = "sha256:" + hashlib.sha256(
        json.dumps(ident, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    _sections.append(('[hooks.state.%s]' % json.dumps(
        "%s:%s:%d:%d" % (path, _tkey, _idx, _hidx)), digest))
old = open(cfg, encoding="utf-8").read() if os.path.exists(cfg) else ""
new_lines = list(old.splitlines())
for key, digest in _sections:
    try:
        start = next(i for i, line in enumerate(new_lines) if line.strip() == key)
    except StopIteration:
        new_lines.extend([""] if new_lines and new_lines[-1].strip() else [])
        new_lines.extend([key, 'trusted_hash = "%s"' % digest])
    else:
        end = next((i for i in range(start + 1, len(new_lines))
                    if new_lines[i].lstrip().startswith("[")
                    and new_lines[i].rstrip().endswith("]")), len(new_lines))
        hash_line = next((i for i in range(start + 1, end)
                          if re.match(r"^\s*trusted_hash\s*=", new_lines[i])), None)
        if hash_line is None:
            new_lines.insert(end, 'trusted_hash = "%s"' % digest)
        elif re.fullmatch(r'\s*trusted_hash\s*=\s*"%s"\s*' % re.escape(digest),
                          new_lines[hash_line]) is None:
            indent = re.match(r"^\s*", new_lines[hash_line]).group(0)
            new_lines[hash_line] = indent + 'trusted_hash = "%s"' % digest
new = "\n".join(new_lines) + ("\n" if old.endswith("\n") or new_lines else "")
hook_text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
hook_changed = changed and hook_text != (open(path, encoding="utf-8").read() if os.path.exists(path) else "")
config_changed = new != old
for filename, will_change in ((path, hook_changed), (cfg, config_changed)):
    backup = filename + ".bak-genie"
    if will_change and not already_installed and os.path.lexists(filename) and os.path.lexists(backup):
        raise SystemExit("cannot update %s: backup already exists at %s" % (filename, backup))
if hook_changed:
    backup_once(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(hook_text)
    print("hook updated ->", path)
else:
    print("hook already current")
if config_changed:
    backup_once(cfg)
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(new)
    print("hook trust updated ->", cfg)
else:
    print("hook trust already current")
EOF

if ! grep -qF "$MARK" "$A" 2>/dev/null; then
  if [ -f "$A" ] && [ ! -e "$A.bak-genie" ] && [ ! -L "$A.bak-genie" ]; then
    cp -p "$A" "$A.bak-genie"
  fi
  { echo; echo "$MARK"; cat "$HERE/AGENTS.md"; } >> "$A"
  echo "AGENTS.md appended -> $A"
else
  echo "AGENTS.md already present"
fi
# --- smoke tests (A4/E3) ---
PY="$(command -v python3)"
_GUARD="$("$PY" -c 'import os,sys; print(os.path.join(sys.argv[1],"router","guard_dangerous.py"))' "$HERE")"
_ROUTER="$("$PY" -c 'import os,sys; print(os.path.join(sys.argv[1],"router","genie_router.py"))' "$HERE")"
if [ -f "$_GUARD" ]; then
  echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf /"}}' | "$PY" "$_GUARD" \
    | grep -q '"permissionDecision": "deny"' \
    && echo "guard smoke test: PASS" \
    || { echo "guard smoke test: FAILED"; exit 1; }
fi
if [ -f "$_ROUTER" ]; then
  echo '{"prompt":"幫我把專案跑起來"}' | "$PY" "$_ROUTER" \
    | grep -q "genie: intent=" \
    && echo "router smoke test: PASS" \
    || { echo "router smoke test: FAILED"; exit 1; }
fi
if [ -f "$_ROUTER" ]; then
  echo '{"prompt":"什麼是 hook"}' \
    | GENIE_PREFS="$(mktemp -d)/prefs.json" "$PY" "$_ROUTER" \
    | grep -q "terms\[on\]" \
    && echo "prefs smoke test: PASS" \
    || { echo "prefs smoke test: FAILED"; exit 1; }
fi
# Other installed tools doing a Genie job: list now, ask on the first prompt.
"$PY" "$HERE/router/overlap.py" 2>/dev/null | "$PY" -c '
import json, sys
found = json.load(sys.stdin)
for job, tools in sorted(found.items()):
    print("overlap: %s also done by %s -> Genie will ask you who owns it" % (job, ", ".join(tools)))
' 2>/dev/null || true
echo "done. first codex prompt: Genie introduces itself and asks your level."
echo "done. try:  codex 'React 還是 Vue 比較好'"
