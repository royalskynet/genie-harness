#!/usr/bin/env python3
"""agents_block.upsert: Genie rule updates must reach existing Codex installs
(the old append-once installer froze them), without touching the user's own text."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agents_block as ab  # noqa: E402

fails = []
B, E = ab.BEGIN, ab.END

new, what = ab.upsert("", "v1")
if what != "appended" or new != "%s\nv1\n%s\n" % (B, E):
    fails.append("empty file: %r %r" % (what, new))

mine = "# my rules\nkeep me\n"
v1, _ = ab.upsert(mine, "v1")
v2, what = ab.upsert(v1, "v2")
if what != "replaced" or "v1" in v2 or "v2" not in v2 or not v2.startswith(mine):
    fails.append("update must replace the block and keep user text: %r" % v2)
if ab.upsert(v2, "v2") != (v2, "unchanged"):
    fails.append("same block must be a no-op")

after = v1 + "\n# added after genie\n"
v3, _ = ab.upsert(after, "v3")
if "# added after genie" not in v3 or "v1" in v3:
    fails.append("text after END must survive: %r" % v3)

legacy = mine + "\n" + B + "\nold genie rules\n"
v4, what = ab.upsert(legacy, "v4")
if what != "replaced" or "old genie rules" in v4 or not v4.startswith(mine) or v4.count(B) != 1:
    fails.append("legacy BEGIN-only block must be replaced to EOF: %r" % v4)

if fails:
    print("FAIL test_agents_block\n  " + "\n  ".join(fails))
    sys.exit(1)
print("PASS test_agents_block")
