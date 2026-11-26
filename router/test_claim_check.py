#!/usr/bin/env python3
"""Self-check for claim_check.py. Run: python3 router/test_claim_check.py

What must hold:
  * MUST CATCH -- a reply claiming a commit or path that does not verify exits
    1 and names it MISSING; that is the whole point of the check.
  * MUST PASS -- real shas, existing paths, URLs and claim-free prose exit 0;
    pure words that happen to be hex-shaped (deadbeef) and bare numbers are
    not treated as claims.

Run as a subprocess in a throwaway git repo: the contract is
stdin -> stdout -> exit code.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "claim_check.py")


def run(text, repo):
    p = subprocess.run([sys.executable, SCRIPT, "--repo", repo],
                       input=text, capture_output=True, text=True, timeout=30)
    return p.stdout, p.returncode


def git(repo, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    p = subprocess.run(["git", "-C", repo] + list(args),
                       capture_output=True, text=True, env=env, timeout=20)
    assert p.returncode == 0, (args, p.stderr)
    return p.stdout.strip()


def main():
    fails = []
    repo = tempfile.mkdtemp(prefix="cc-")
    git(repo, "init", "-q")
    os.makedirs(os.path.join(repo, "dir"))
    with open(os.path.join(repo, "dir", "f.txt"), "w") as fh:
        fh.write("x")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    sha = git(repo, "rev-parse", "HEAD")

    out, rc = run("committed as %s, done." % sha, repo)
    if rc != 0 or "OK sha" not in out:
        fails.append("FAIL 1: real sha rejected: rc=%d out=%s" % (rc, out[:120]))

    out, rc = run("committed as 1234abc9.", repo)
    if rc != 1 or "MISSING sha 1234abc9" not in out:
        fails.append("FAIL 2: invented sha not caught: rc=%d out=%s" % (rc, out[:120]))

    out, rc = run("see dir/f.txt for details", repo)
    if rc != 0 or "OK path dir/f.txt" not in out:
        fails.append("FAIL 3: existing relative path rejected: rc=%d out=%s"
                     % (rc, out[:120]))

    out, rc = run("see dir/nope.py for details", repo)
    if rc != 1 or "MISSING path dir/nope.py" not in out:
        fails.append("FAIL 4: missing path not caught: rc=%d out=%s" % (rc, out[:120]))

    out, rc = run("per https://github.com/a/b/commit/1234abc9 and deadbeef", repo)
    if "MISSING path" in out:
        fails.append("FAIL 5: URL tail treated as a path claim: %s" % out[:160])
    if "deadbeef" in out:
        fails.append("FAIL 5b: digitless hex word treated as a sha claim")

    out, rc = run("no claims here, issue 1234567 is a number", repo)
    if rc != 0 or "nothing to verify" not in out:
        fails.append("FAIL 6: claim-free text should exit 0: rc=%d out=%s"
                     % (rc, out[:120]))

    out, rc = run("fixed in router/fake9.py at bcd1234ef", tempfile.mkdtemp(prefix="cc-empty-"))
    if rc != 1:
        fails.append("FAIL 7: claims against an empty non-git dir must fail: rc=%d" % rc)

    if fails:
        print("FAIL (%d):" % len(fails))
        for f in fails:
            print("  " + f)
        sys.exit(1)
    print("PASS  all cases: real sha ok, invented sha caught, path checks, "
          "URL ignored, digitless hex ignored, claim-free clean")


if __name__ == "__main__":
    main()
