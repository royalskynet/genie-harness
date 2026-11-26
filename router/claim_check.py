#!/usr/bin/env python3
"""Genie Claim Check — zero-token verification of commit shas and file paths
a reply claims exist, before the reply goes out.

The failure this catches (issue #49, proposal 1's mechanical half): a reply
announces `committed as abc1234` or `fixed in router/foo.py`, and neither
exists. Self-critique without external evidence does not help, so the check
goes to the evidence: `git cat-file -e <sha>^{commit}` for shas, the
filesystem for paths. What cannot be verified is listed MISSING so the reply
can be rewritten to say "unverified" instead of claiming.

Reads the reply on stdin or `--file PATH`. `--repo DIR` (default cwd) is the
repo shas are checked in and relative paths resolve against.

Exit: 0 = every extracted claim verifies (or there is nothing to check),
1 = at least one claim could not be verified, 2 = bad usage.
Never calls a model; never blocks -- it prints a verdict list.

ponytail: URLs are not checked -- matching them against the turn's tool
output needs the transcript, which is claim_gate's job once adopted.
"""
import os
import re
import subprocess
import sys

SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
URL_RE = re.compile(r"[a-zA-Z][\w+.-]*://\S+")
# A claim-shaped path: absolute, ~/..., ./..., ../..., or dir/file.ext.
PATH_TOKEN_RE = re.compile(r"[\w.~+-]*[/][\w./+-]*")


def extract(text):
    """-> (shas, paths), each deduped in first-seen order. URLs are stripped
    first: a commit URL is evidence, not a claim."""
    body = URL_RE.sub(" ", text)
    shas, seen_sha = [], set()
    for m in SHA_RE.finditer(body):
        tok = m.group(0)
        if not any(c.isdigit() for c in tok):
            continue  # all-letter hex word (deadbeef, facade): prose, not a sha
        if len(tok) < 40 and tok.isdigit():
            continue  # pure digits: a number, not a sha
        if tok not in seen_sha:
            seen_sha.add(tok)
            shas.append(tok)
    paths, seen_path = [], set()
    for m in PATH_TOKEN_RE.finditer(body):
        tok = m.group(0).strip("`'\"()[]{}<>,;:")
        if "://" in tok or tok.startswith(("www.", "ftp.")):
            continue  # URL, not a path claim
        # A trailing period is almost always the sentence's full stop, not
        # part of the name: strip it (and trailing slashes) and verify what
        # remains. Prose like "and/or." then fails the anchor/extension test
        # below as before, but a real path ending a sentence still gets
        # checked instead of being skipped unverified.
        tok = tok.rstrip("/.")
        if not (tok.startswith(("/", "~/", "./", "../")) or "." in tok):
            continue  # bare a/b with no anchor or extension: not a path claim
        if tok and tok not in seen_path:
            seen_path.add(tok)
            paths.append(tok)
    return shas, paths


def check_sha(repo, sha):
    try:
        p = subprocess.run(
            ["git", "-C", repo, "cat-file", "-e", "%s^{commit}" % sha],
            capture_output=True, timeout=10)
        return p.returncode == 0
    except Exception:
        return False


def check_path(repo, tok):
    p = os.path.expanduser(tok)
    if not os.path.isabs(p):
        p = os.path.join(repo, p)
    return os.path.exists(p)


def main(argv):
    repo, path = os.getcwd(), None
    i = 1
    while i < len(argv):
        if argv[i] == "--repo" and i + 1 < len(argv):
            repo = argv[i + 1]
            i += 2
        elif argv[i] == "--file" and i + 1 < len(argv):
            path = argv[i + 1]
            i += 2
        else:
            sys.stderr.write("usage: claim_check.py [--repo DIR] [--file PATH] < reply\n")
            return 2
    try:
        text = open(path, encoding="utf-8", errors="replace").read() if path \
            else sys.stdin.buffer.read().decode("utf-8", "replace")
    except OSError as e:
        sys.stderr.write("claim_check: %s\n" % e)
        return 2

    shas, paths = extract(text)
    missing = 0
    for sha in shas:
        ok = check_sha(repo, sha)
        missing += 0 if ok else 1
        print("%s sha %s" % ("OK" if ok else "MISSING", sha))
    for tok in paths:
        ok = check_path(repo, tok)
        missing += 0 if ok else 1
        print("%s path %s" % ("OK" if ok else "MISSING", tok))
    if missing:
        print("claim_check: %d unverifiable claim(s); mark them unverified "
              "or cite the source" % missing)
    elif shas or paths:
        print("claim_check: all %d claim(s) verify" % (len(shas) + len(paths)))
    else:
        print("claim_check: nothing to verify")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
