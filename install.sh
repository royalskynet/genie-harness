#!/usr/bin/env bash
# Genie Harness installer. Re-runnable with first-run backups preserved.
#   1. numpy present?            (only runtime dep)
#   2. router model              (one-time ~512 MB download -> ~35 MB on disk)
#   3. skills  -> ~/.agents/skills/genie-*   (symlinks)
#   4. hook    -> ~/.codex/hooks.json        (merged, existing hooks kept)
#   5. AGENTS.md -> ~/.codex/AGENTS.md       (appended once, marker-guarded)
#   6. hook trust -> ~/.codex/config.toml
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEX="${CODEX_HOME:-$HOME/.codex}"
SKILLS="$HOME/.agents/skills"
MARK="<!-- genie-harness -->"

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
# cannot leave the four links half-installed.
for d in "$HERE"/skills/genie-*; do
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

for d in "$HERE"/skills/genie-*; do
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
cmd = "%s %s" % (shlex.quote(sys.executable), shlex.quote(os.path.join(here, "router", "genie_router.py")))
timeout = 5
hook = {"type": "command", "command": cmd, "timeout": timeout}
data = {"hooks": {}}
original = None
already_installed = False
if os.path.exists(path):
    with open(path, encoding="utf-8") as f:
        original = json.load(f)
    data = original
lst = data.setdefault("hooks", {}).setdefault("UserPromptSubmit", [])
idx = next((i for i, e in enumerate(lst) if any("genie_router.py" in h.get("command", "") for h in e.get("hooks", []))), None)
already_installed = idx is not None
changed = False
hook_idx = 0
if idx is None:
    lst.append({"hooks": [hook]})
    idx = len(lst) - 1
    changed = True
else:
    hooks = lst[idx].setdefault("hooks", [])
    hook_idx = next(i for i, h in enumerate(hooks) if "genie_router.py" in h.get("command", ""))
    if hooks[hook_idx] != hook:
        hooks[hook_idx] = hook
        changed = True

def backup_once(filename):
    backup = filename + ".bak-genie"
    if os.path.lexists(filename) and not os.path.lexists(backup):
        shutil.copy2(filename, backup, follow_symlinks=False)

ident = {"event_name": "user_prompt_submit", "hooks": [{"type": "command", "command": cmd, "timeout": timeout, "async": False}]}
matcher = lst[idx].get("matcher")
if matcher is not None:
    ident["matcher"] = matcher
digest = "sha256:" + hashlib.sha256(json.dumps(ident, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
key = '[hooks.state.%s]' % json.dumps("%s:user_prompt_submit:%d:%d" % (path, idx, hook_idx))
old = open(cfg, encoding="utf-8").read() if os.path.exists(cfg) else ""
lines = old.splitlines()
new_lines = list(lines)
try:
    start = next(i for i, line in enumerate(lines) if line.strip() == key)
except StopIteration:
    new_lines.extend([""] if new_lines and new_lines[-1].strip() else [])
    new_lines.extend([key, 'trusted_hash = "%s"' % digest])
else:
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].lstrip().startswith("[") and lines[i].rstrip().endswith("]")), len(lines))
    hash_line = next((i for i in range(start + 1, end)
                      if re.match(r"^\s*trusted_hash\s*=", lines[i])), None)
    if hash_line is None:
        new_lines.insert(end, 'trusted_hash = "%s"' % digest)
    elif re.fullmatch(r'\s*trusted_hash\s*=\s*"%s"\s*' % re.escape(digest), lines[hash_line]) is None:
        indent = re.match(r"^\s*", lines[hash_line]).group(0)
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
echo "done. try:  codex 'React 還是 Vue 比較好'"
