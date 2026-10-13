#!/usr/bin/env python3
"""Upsert Genie's AGENTS.md block into a host instructions file (Codex ~/.codex/AGENTS.md).

Old install.sh appended the block once and skipped when the marker existed, so
AGENTS.md updates never reached existing Codex users. The block is now fenced by
BEGIN/END markers and replaced in place on every install/update; text outside the
fence (the user's own rules) is kept. A legacy file with only BEGIN is treated as
"block runs to EOF", which is how the old installer wrote it.

usage: agents_block.py <target> <genie AGENTS.md>   (prints what it did)
"""
import os
import sys

BEGIN = "<!-- genie-harness -->"
END = "<!-- /genie-harness -->"


def upsert(target_text, block):
    fenced = "%s\n%s\n%s\n" % (BEGIN, block.rstrip("\n"), END)
    i = target_text.find(BEGIN)
    if i < 0:
        sep = "" if not target_text else ("\n" if target_text.endswith("\n") else "\n\n")
        return target_text + sep + fenced, "appended"
    j = target_text.find(END, i)
    tail = "" if j < 0 else target_text[j + len(END):].lstrip("\n")
    new = target_text[:i] + fenced + (("\n" + tail) if tail else "")
    return new, ("unchanged" if new == target_text else "replaced")


def main(argv):
    target, src = argv[1], argv[2]
    old = open(target, encoding="utf-8").read() if os.path.exists(target) else ""
    new, what = upsert(old, open(src, encoding="utf-8").read())
    if what != "unchanged":
        if old and not os.path.exists(target + ".bak-genie"):
            with open(target + ".bak-genie", "w", encoding="utf-8") as f:
                f.write(old)
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new)
        os.replace(tmp, target)
    print("AGENTS.md %s -> %s" % (what, target))


if __name__ == "__main__":
    main(sys.argv)
