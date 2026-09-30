#!/usr/bin/env python3
"""Repo hygiene tests, each one guarding a specific predicted failure.

These are boring on purpose. None of them test behaviour; they test that the
things which silently rot across machines and across time have not rotted yet:

  D1  AGENTS.md silently truncated once it grows (openai/codex#43075, 32 KiB)
  D2  a rule body copied into both AGENTS.md and a skill, then the two drift
  E4  an absolute path from one developer's machine ends up committed
  A5  hooks.json points at a script that was renamed or never added
  --  shell and python that do not even parse

`PREMORTEM.md` names the failure each of these prevents. If you add a check here,
say which one, so the next person knows what they are protecting.
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# D1: Codex truncates around 32 KiB. Fail well under it, warn well under that.
AGENTS_WARN = 16 * 1024
AGENTS_FAIL = 24 * 1024

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "router/model"}
TEXT_EXT = {".py", ".sh", ".md", ".json", ".js", ".mjs", ".txt", ".toml", ".yml", ".yaml"}


def tracked_files():
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if os.path.splitext(fn)[1] in TEXT_EXT:
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def rel(path):
    return os.path.relpath(path, ROOT)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_agents_md_fits(fails, notes):
    p = os.path.join(ROOT, "AGENTS.md")
    n = len(read(p).encode("utf-8"))
    if n > AGENTS_FAIL:
        fails.append("D1: AGENTS.md is %d bytes, over the %d budget. Codex truncates "
                     "around 32 KiB, so the tail would vanish silently. Move detail "
                     "into skills/." % (n, AGENTS_FAIL))
    elif n > AGENTS_WARN:
        notes.append("D1: AGENTS.md is %d bytes, approaching the budget" % n)


def test_no_absolute_home_paths(fails):
    pat = re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+/")
    for f in tracked_files():
        for i, line in enumerate(read(f).splitlines(), 1):
            if pat.search(line):
                fails.append("E4: %s:%d hardcodes a home path: %s"
                             % (rel(f), i, line.strip()[:70]))


def test_hooks_point_at_real_scripts(fails):
    p = os.path.join(ROOT, "hooks.json")
    try:
        data = json.loads(read(p))
    except Exception as e:
        fails.append("hooks.json is not valid JSON: %r" % e)
        return
    cmds = []
    for event, entries in (data.get("hooks") or {}).items():
        for entry in entries:
            for h in entry.get("hooks", []):
                cmds.append((event, h.get("command", ""), h.get("timeout")))
    if not cmds:
        fails.append("A5: hooks.json registers no hooks at all")
    for event, cmd, timeout in cmds:
        if not cmd:
            fails.append("A5: %s hook has an empty command" % event)
            continue
        if not timeout:
            fails.append("A5: %s hook %r has no timeout; a hung hook stalls the prompt"
                         % (event, cmd))
        for script in re.findall(r"[\w./-]+\.(?:py|sh|js|mjs)", cmd):
            local = script.split("__GENIE_DIR__/")[-1].lstrip("./")
            if not os.path.exists(os.path.join(ROOT, local)):
                fails.append("A5: %s hook references %s which does not exist in the repo"
                             % (event, local))


def test_python_parses(fails):
    for f in tracked_files():
        if not f.endswith(".py"):
            continue
        p = subprocess.run([sys.executable, "-m", "py_compile", f],
                           capture_output=True, text=True)
        if p.returncode != 0:
            fails.append("%s does not compile: %s" % (rel(f), p.stderr.strip()[:140]))


def test_shell_parses(fails):
    for f in tracked_files():
        if not (f.endswith(".sh") or f.endswith(".bash")):
            continue
        p = subprocess.run(["bash", "-n", f], capture_output=True, text=True)
        if p.returncode != 0:
            fails.append("%s is not valid bash: %s" % (rel(f), p.stderr.strip()[:140]))


def test_skills_wellformed(fails):
    skills_dir = os.path.join(ROOT, "skills")
    if not os.path.isdir(skills_dir):
        fails.append("skills/ directory is missing")
        return
    found = []
    for name in sorted(os.listdir(skills_dir)):
        if not name.startswith("genie-"):
            continue
        found.append(name)
        md = os.path.join(skills_dir, name, "SKILL.md")
        if not os.path.exists(md):
            fails.append("skill %s has no SKILL.md" % name)
            continue
        body = read(md)
        if not body.lstrip().startswith("---"):
            fails.append("skill %s: SKILL.md has no YAML frontmatter" % name)
        for field in ("name:", "description:"):
            if field not in body.split("---")[1 if body.startswith("---") else 0]:
                fails.append("skill %s: frontmatter is missing %s" % (name, field))
    if not found:
        fails.append("no genie-* skills found")

    # D2: every skill must have a description that says when to use it. A skill
    # nobody can route to is dead weight the model has to read and ignore.
    for name in found:
        md = os.path.join(skills_dir, name, "SKILL.md")
        if not os.path.exists(md):
            continue
        head = read(md)[:600]
        m = re.search(r"description:\s*(.+)", head, re.S)
        if m and len(m.group(1).strip()) < 40:
            fails.append("D2: skill %s has a description too short to route on" % name)


def test_agents_points_at_real_skills(fails):
    body = read(os.path.join(ROOT, "AGENTS.md"))
    skills_dir = os.path.join(ROOT, "skills")
    have = set(os.listdir(skills_dir)) if os.path.isdir(skills_dir) else set()
    for ref in set(re.findall(r"\$genie-[a-z-]+", body)):
        name = ref.lstrip("$")
        if name not in have:
            fails.append("AGENTS.md references $%s but skills/%s does not exist"
                         % (name, name))
    for name in have:
        if name.startswith("genie-") and name not in body:
            notes.append("D2: skills/%s exists but AGENTS.md never points at it" % name)


def test_agents_does_not_duplicate_skill_bodies(fails):
    """D2: the actual drift. A long, distinctive line must live in one place only."""
    body = read(os.path.join(ROOT, "AGENTS.md"))
    agent_lines = {l.strip() for l in body.splitlines() if len(l.strip()) > 40}
    skills_dir = os.path.join(ROOT, "skills")
    if not os.path.isdir(skills_dir):
        return
    for name in os.listdir(skills_dir):
        md = os.path.join(skills_dir, name, "SKILL.md")
        if not os.path.exists(md):
            continue
        for line in read(md).splitlines():
            s = line.strip()
            if len(s) > 40 and s in agent_lines:
                fails.append("D2: this line is in both AGENTS.md and skills/%s/SKILL.md: "
                             "%s. Keep the full text in one place and point to it "
                             "from the other." % (name, s[:70]))


def test_eval_set_is_labelled_honestly(fails):
    """C1: 74 hand-written cases must never be presented as a benchmark."""
    p = os.path.join(ROOT, "router", "eval_set.json")
    if not os.path.exists(p):
        return
    with open(p, encoding="utf-8") as fh:
        head = fh.read(400)
    low = head.lower()
    if "dev set" not in low and "not a benchmark" not in low:
        fails.append("C1: router/eval_set.json does not say it is a hand-written dev "
                     "set. These cases are self-authored, so an accuracy number from "
                     "them is a regression baseline, not evidence of generalisation.")


def main():
    fails, notes = [], []
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(fails) if fn.__code__.co_argcount == 1 else fn(fails, notes)
    for n in notes:
        print("note: " + n)
    if fails:
        print("FAIL (%d):" % len(fails))
        for f in fails:
            print("  " + f)
        sys.exit(1)
    print("PASS  %d files checked: size budget, no hardcoded home paths, hooks resolve, "
          "python/shell parse, skills wellformed, no drift (D1 D2 E4 A5 C1)" % len(tracked_files()))


if __name__ == "__main__":
    main()
