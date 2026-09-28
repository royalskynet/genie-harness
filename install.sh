#!/usr/bin/env bash
# Genie Harness installer. Idempotent. Everything it touches is backed up first.
#   1. numpy present?            (only runtime dep)
#   2. router model              (one-time ~512 MB download -> ~35 MB on disk)
#   3. skills  -> ~/.agents/skills/genie-*   (symlinks)
#   4. hook    -> ~/.codex/hooks.json        (merged, existing hooks kept)
#   5. AGENTS.md -> ~/.codex/AGENTS.md       (appended once, marker-guarded)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEX="${CODEX_HOME:-$HOME/.codex}"
SKILLS="$HOME/.agents/skills"
MARK="<!-- genie-harness -->"

python3 -c "import numpy" 2>/dev/null || { echo "need numpy: python3 -m pip install --user numpy"; exit 1; }

[ -f "$HERE/router/model/vocab.json" ] || python3 "$HERE/router/setup_model.py"
python3 "$HERE/router/test_router.py" >/dev/null && echo "router self-check: PASS"

mkdir -p "$SKILLS" "$CODEX"
for d in "$HERE"/skills/genie-*; do ln -sfn "$d" "$SKILLS/$(basename "$d")"; done
echo "skills linked -> $SKILLS"

# merge hook (python stdlib json; no jq dependency)
python3 - "$HERE" "$CODEX/hooks.json" <<'EOF'
import json, os, shutil, sys
here, path = sys.argv[1], sys.argv[2]
cmd = "python3 %s/router/genie_router.py" % here
entry = {"hooks": [{"type": "command", "command": cmd, "timeout": 5}]}
data = {"hooks": {}}
if os.path.exists(path):
    shutil.copy(path, path + ".bak-genie")
    data = json.load(open(path))
lst = data.setdefault("hooks", {}).setdefault("UserPromptSubmit", [])
if not any("genie_router.py" in h.get("command", "") for e in lst for h in e.get("hooks", [])):
    lst.append(entry)
    json.dump(data, open(path, "w"), indent=2, ensure_ascii=False)
    print("hook added ->", path)
else:
    print("hook already present")
EOF

A="$CODEX/AGENTS.md"
if ! grep -qF "$MARK" "$A" 2>/dev/null; then
  [ -f "$A" ] && cp "$A" "$A.bak-genie"
  { echo; echo "$MARK"; cat "$HERE/AGENTS.md"; } >> "$A"
  echo "AGENTS.md appended -> $A"
else
  echo "AGENTS.md already present"
fi
echo "done. try:  codex 'React 還是 Vue 比較好'"
