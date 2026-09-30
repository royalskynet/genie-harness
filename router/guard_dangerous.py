#!/usr/bin/env python3
"""Genie Guard — Codex `PreToolUse` hard gate for catastrophic commands.

Why this exists: Genie's `risky_action` intent is a 7-way cosine classifier. It is
good enough to make the model *say* "this cannot be undone". It is nowhere near
good enough to be the thing that actually stops `rm -rf ~`. Published work on
bypassing LLM guardrails reports evasion success rates up to 100% against
classifier-style defences, and the worst-case recall of a 7-way centroid
classifier on unseen phrasing is simply unknown. So the intent tag stays a hint
and this script becomes the gate.

Two tiers, because `PreToolUse` supports both:

  DENY  -> `permissionDecision: "deny"` with a plain-language reason.
  WARN  -> `additionalContext` only. The call proceeds, but the model is told the
           command is heavier than it looks. This is what keeps the gate honest
           about its own limits: some things are genuinely ambiguous, and
           guessing wrong either way is worse than saying so.

  DENY is for catastrophe: self-destruction, lost history, lost data, leaked
  credentials, invisible published artifacts, privilege escalation.
  WARN is for "this might be fine, or might be the end of your project".

Deliberately allowed: ordinary destructive-but-recoverable work
(`rm -rf node_modules`, `rm -rf dist`, `git reset --hard` on a feature branch).
Over-blocking a beginner's normal work is its own failure mode.

Known gap, on purpose: `rm -rf ~/Documents` is WARN-tier, not denied. There is
no reliable way to tell a project checkout from personal data, and inventing a
fuzzy heuristic would block real work. Codex's own sandbox mode and approval
policy are the boundary here; this complements them, it does not replace them.

Known gap, not on purpose (no fix, tracked here so it stays visible): variable
indirection, e.g. `X=/; rm -rf $X`. This is a regex gate, not a shell parser,
so it cannot resolve an arbitrary variable to its value before matching. Only
the literal, hardcoded forms (`$HOME`, `${HOME}`, `~`) are recognized.

Failure policy: fail OPEN. Any internal error allows the call, because a guard
that breaks your terminal is worse than one that misses a phrase.

Escape hatch: GENIE_ALLOW_DANGEROUS=1 skips every rule.
"""
import json
import os
import re
import sys

# --- command-level deny rules ---------------------------------------------
# Regexes are applied to the command with quoted string literals blanked out, so
# prose that merely mentions a scary word ("echo 'how do I wipe the disk?'")
# cannot trip the gate.
BASH_DENY = [
    ("force-push-protected",
     r"\bgit\s+push\b(?=[^|;&]*(?:\s--force\b|\s--force-with-lease\b|\s-f\b))(?=[^|;&]*\b(?:main|master|develop|development|production|prod|release)\b)",
     "This force-pushes over a shared branch. Commits other people already pulled can disappear permanently."),
    ("delete-remote-branch",
     r"\bgit\s+push\b[^|;&]*(?:--delete\b|\s:)",
     "This deletes a remote branch for everyone."),
    ("rewrite-all-refs",
     r"\bgit\b[^|;&]*\b(?:filter-branch|filter-repo)\b",
     "This rewrites every commit in this repository's history."),
    ("drop-database",  # sql
     r"(?:^|[;&|]\s*|\b(?:mysql|mysqldump|psql|sqlite3?|mariadb|sqlcmd)\b[^|;&]*['\"]?\s*)(?:DROP\s+(?:DATABASE|SCHEMA)|\bdropdb\b)",
     "This drops a database and every row in it."),
    ("drop-table",  # sql
     r"(?:^|[;&|]\s*|\b(?:mysql|mysqldump|psql|sqlite3?|mariadb|sqlcmd)\b[^|;&]*['\"]?\s*)DROP\s+TABLE\b",
     "This drops a table and every row in it."),
    ("truncate-table",  # sql
     r"(?:^|[;&|]\s*|\b(?:mysql|mysqldump|psql|sqlite3?|mariadb|sqlcmd)\b[^|;&]*['\"]?\s*)TRUNCATE\b",
     "This empties a table irreversibly."),
    ("db-reset",
     r"\b(?:prisma\s+migrate\s+reset|drizzle-kit\s+push\s+--force|rails\s+db:(?:reset|drop)|alembic\s+downgrade\s+base|flyway\s+clean|sequelize\s+db:(?:drop|reset))\b",
     "This resets the database to an empty state and drops all data."),
    ("curl-pipe-shell",
     r"\b(?:curl|wget|fetch)\b[^|;&]*\|\s*(?:sudo\s+)?(?:ba|z|k|fi)?sh\b",
     "This downloads code from the internet and runs it immediately. Read it before running it."),
    ("pipe-into-shell",
     r"\|\s*(?:sudo\s+)?(?:ba|z|k|fi)?sh\b",
     "This pipes command output straight into a shell (decoded, generated, or otherwise). Read what it would run before running it."),
    ("publish-artifact",
     r"\b(?:npm\s+publish|yarn\s+publish|pnpm\s+publish|twine\s+upload|cargo\s+publish|gem\s+push|nuget\s+push|gh\s+release\s+create|docker\s+push)\b",
     "This publishes an artifact that other people and machines can pull. It cannot be pulled back."),
    ("write-credential",
     r"\b(?:gh\s+(?:secret|variable)\s+set|aws\s+configure\s+store\s+credentials|gcloud\s+auth\s+application-default\s+set)\b",
     "This writes credentials. Make sure you know exactly where they are going."),
    ("sudo-privileged",
     r"(?:^|[|;&]\s*|\s)sudo\s+(?!-h\b|--help\b|-v\b)",
     "This asks for administrator rights. I'd rather we not need them — tell me what you are trying to reach and I'll find a user-level way."),
    ("terraform-destroy",
     r"\bterraform\s+(?:destroy\b|apply\b[^|;&]*-(?:destroy|replace)\b)",
     "This destroys or replaces cloud infrastructure, which usually means deleting real running services."),
    ("s3-remove-bucket",
     r"\baws\s+s3\s+(?:rb|rm)\b[^|;&]*--recursive",
     "This deletes an entire S3 bucket and everything inside it."),
    ("cloud-delete",
     r"\b(?:gcloud|az)\b[^|;&]*\sdelete\b",
     "This deletes cloud resources."),
    ("kubectl-cluster-delete",
     r"\bkubectl\s+delete\b[^|;&]*\b(?:namespace|node|pvc|persistentvolumeclaim|pv|all)\b",
     "This deletes cluster-wide resources and may not be recoverable."),
    ("launch-agent-register",
     r"\blaunchctl\s+(?:load|bootstrap)\b",
     "This registers a program that will run automatically on this machine from now on."),
    ("shell-profile-write",
     r"[<>]{1,2}\s*~?/?\.(?:bashrc|zshrc|bash_profile|profile|zprofile|zshenv)\b",
     "This edits a shell startup file, which silently changes how every future terminal behaves."),
    ("git-clean-force",
     r"\bgit\s+clean\b(?=[^|;&]*-[a-zA-Z]*f)(?![^|;&]*-[a-zA-Z]*n)",
     "This deletes untracked and/or ignored files across the tree. `-n` first if you want to see the list."),
    ("python-rmtree-root",
     r"\b(?:shutil\.rmtree|fs\.rmSync|fs\.rmdirSync|os\.removedirs)\s*\(\s*['\"]?(?:/|~)(?:['\")\s,]|\Z)",
     "This deletes a whole directory tree from inside Python, and the filesystem root is not a normal target."),
    ("os-remove-device",
     r"\bos\.(?:remove|unlink)\s*\(\s*['\"]?/dev/",
     "This removes a device node from inside Python."),
    ("mv-root-to-devnull",
     r"\bmv\b[^|;&]*\s(?:/|~|/\*|\$HOME)\s+/dev/null\b",
     "This moves a top-level path to /dev/null, which destroys it."),
    ("truncate-device",
     r"\btruncate\b[^|;&]*/dev/",
     "This zeroes a raw device."),
    ("find-root-delete",
     r"\bfind\s+(?:/|~|\$HOME|\*)(?:\s|$)[^|;&]*-(?:delete|exec\s+rm|ok\s)",
     "This searches from the filesystem root and deletes. Narrow the search path first."),
    ("unlink-device",
     r"\bunlink\b[^|;&]*/dev/",
     "This removes a device node."),
    ("shell-history-wipe",
     r"(?:\bhistory\s+-c\b|\brm\b[^|;&]*~?/?\.(?:bash_history|zsh_history|local/share/fish/fish_history))",
     "This erases your shell history, which is usually the only record of what a command did."),
    ("filesystem-wipe",
     r"(?:^|[;&|]\s*)\s*\b(?:mkfs(?:\.\w+)?|fdisk|parted|diskutil\s+\w*\b(?:erase|reformat|partition)\w*|shred|wipefs)\b",
     "This reformats or wipes a drive. Everything on it is gone."),
]

# --- target-dependent deny rules ------------------------------------------
# The danger is the *path*, not the verb. `(name, command regex with one capture
# group for the path, path predicate, reason)`.
ROOTISH = re.compile(r"^(?:/|/\*|~+|~/+$|~/\*|\$HOME|\$\{HOME\}|/home/[^/]+|\*|\.\.|~/\.\w*)$")
TARGET_DENY = [
    ("rm-rootish",
     r"\brm\b(?=[^|;&]*(?:-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r|-[a-z]*r\b))([^|;&]+?)\s*(?:$|[;&|])",
     lambda p: bool(ROOTISH.match(p)),
     "This points `rm` at the filesystem root or your whole home folder. If you really mean it, say so and I'll narrow the path to the exact directory first."),
    ("rm-no-preserve-root", r"\brm\b([^|;&]*?)--no-preserve-root",
     lambda p: True,
     "This deletes from the filesystem root and cannot be undone."),
    ("rm-recursive-system",
     r"\brm\b(?=[^|;&]*(?:-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r|-[a-z]*r\b))([^|;&]+?)\s*(?:$|[;&|])",
     lambda p: bool(re.match(r"^/(?:etc|System|usr|bin|sbin|private/etc|var|opt|home)(?:/|$)", p)),
     "This recursively deletes a system directory."),
    ("rm-device",
     r"\brm\b(?=[^|;&]*(?:-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r|-[a-z]*r\b))([^|;&]+?)\s*(?:$|[;&|])",
     lambda p: bool(re.match(r"^(?:/dev/|/dev/\w|/Volumes/\w*\s*$|/System/Volumes/Data/?$)", p)),
     "This recursively deletes a disk or a mounted volume."),
    ("chmod-777-system",
     r"\bchmod\b(?=[^|;&]*\s-R\b)(?=[^|;&]*\b777\b)([^|;&]+?)\s*(?:$|[;&|])",
     lambda p: bool(re.match(r"^/(?:etc|System|usr|bin|sbin|private/etc|var|opt)?/?$|^\s*$", p)) or bool(re.match(r"^/(?:etc|System|usr|bin|sbin|private/etc|var|opt)(?:/|$)", p)),
     "This makes a system directory world-writable."),
    ("dd-to-device", r"\bdd\b[^|;&]*\bof=(\S+)",
     lambda p: p.startswith("/dev/"),
     "This writes raw bytes straight onto a device and destroys whatever is there."),
    ("disk-device-write", r"\b(?:diskutil\s+\w+|(?:cat|cp|mv|tee)\b[^|;&]*)(\s+)?(/dev/disk\d\S*)",
     lambda p: True,
     "This writes directly to a raw disk device."),
]

# --- target-dependent warn rules ------------------------------------------
TARGET_WARN = [
    ("rm-home-tree",
     r"\brm\b(?=[^|;&]*(?:-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r|-[a-z]*r\b))([^|;&]+?)\s*(?:$|[;&|])",
     "This recursively deletes from your home folder. Before running it, say out loud which directory you expect to disappear, so we can confirm it is a project folder and not something else."),
    ("dd-raw",
     r"\bdd\b[^|;&]*\bif=\S+",
     "`dd` writes to the target device directly and cannot be undone. Check `of=` before running."),
]

# --- write-target rules (apply_patch / Write / Edit file_path) ------------
PATH_DENY = [
    ("system-dir", r"^/(?:etc|System|usr|bin|sbin|private/etc|var/db|private/var/db|private/tmp/launchd)(?:/|$)",
     "This writes into a system directory that macOS protects. It usually needs admin rights, which we should avoid."),
    ("launch-daemon", r"^/(?:Library/Launch(?:Daemons|Agents)|System/Library/LaunchDaemons)(?:/|$)",
     "This installs a program that will run automatically on this machine."),
    ("private-key", r"^~?/?\.ssh/(?:id_|authorized_keys)",
     "This is an SSH private key. Writing to it can lock you out of your servers."),
    ("cloud-credentials", r"^~?/?\.(?:aws/(?:credentials|config)|config/gcloud/credentials\.db|kube/config|docker/config\.json)$",
     "This is a credential file for a cloud or container tool."),
    ("agent-credentials", r"^~?/?\.(?:codex/auth\.json|claude\.json|npmrc|pypirc|gem/credentials)$",
     "This is a credential or token file. Writing here can leak or destroy your access."),
]

# Content scan (premortem A1): the easiest way past a `command`-only gate is to
# write a script and then run it. So writes to anything script-shaped get their
# body scanned too. Narrower rule set than the command gate on purpose --
# `rm -rf build` in a Makefile clean target is normal work.
SCRIPT_PATH = re.compile(r"(?:\.sh|\.bash|\.zsh|\.ksh|\.py|\.rb|\.pl|\.ps1|\.bat|\.cmd|\.mk|\.service|\.plist|\.fish|\.zshrc|\.bashrc|\.profile|Makefile|makefile|Dockerfile|Containerfile|GNUmakefile)$", re.IGNORECASE)
CONTENT_RULE_NAMES = frozenset((
    "force-push-protected", "delete-remote-branch", "rewrite-all-refs",
    "drop-database", "drop-table", "truncate-table", "db-reset",
    "curl-pipe-shell", "sudo-privileged", "terraform-destroy",
    "s3-remove-bucket", "cloud-delete", "filesystem-wipe",
    "launch-agent-register", "git-clean-force", "mv-root-to-devnull",
    "find-root-delete", "python-rmtree-root", "shell-history-wipe",
))
CONTENT_ALLOW = re.compile(r"genie-guard:\s*allow")
CONTENT_KEYS = ("content", "new_string", "new_str", "text", "patch", "input", "body", "script")

PATH_WARN = [
    ("home-dotfile", r"^~?/?\.(?:config|local/share|gitconfig|netrc|ssh/config|nvmrc|bashrc|zshrc)",
     "This edits a personal configuration file. It affects every project on this machine, so let's make sure the change is what you want."),
]

# Rules whose target is *inside* a string literal (SQL statements, Python string
# args) must read the quotes-stripped variant. Everything else reads the
# quotes-blanked variant so prose mentioning a scary word cannot trip the gate.
LITERAL_RULES = frozenset((
    "drop-database", "drop-table", "truncate-table",
    "python-rmtree-root", "os-remove-device",
))
SQL_OR_QUOTE = re.compile(r"'[^']*'|\"[^\"]*\"")


def _blank_quotes(cmd):
    """Replace quoted literals with spaces so prose can't trip a rule.

    Exception: a quoted literal with no whitespace inside it (`"$HOME"`, `"~"`,
    `"/etc/passwd"`) is a path or token, not prose, so it is unquoted and kept
    live instead of blanked. Without this, `rm -rf "$HOME"` loses its target
    entirely and neither denies nor warns.
    """
    def repl(m):
        inner = m.group(0)[1:-1]
        if inner and not re.search(r"\s", inner):
            return inner
        return " " * len(m.group(0))
    return SQL_OR_QUOTE.sub(repl, cmd)


# Interpreters that run a quoted string as code (`sh -c "..."`, `eval "..."`,
# `python -c "..."`). Their payload sits inside quotes that `_blank_quotes`
# would otherwise erase as prose -- so it has to be inspected before blanking.
WRAPPER_RE = re.compile(
    r"\b(?:(?:bash|sh|zsh|ksh|dash|ash)\s+(?:-\S+\s+)*-c"
    r"|eval"
    r"|(?:python[23]?|node|ruby|perl)\s+(?:-\S+\s+)*-[ce])\s*",
    re.IGNORECASE)


def _wrapped_scripts(cmd):
    """Return the quoted payload of any indirect-execution wrapper in `cmd`."""
    out = []
    for m in WRAPPER_RE.finditer(cmd):
        rest = cmd[m.end():]
        qm = re.match(r"(['\"])(.*?)(?<!\\)\1", rest, re.DOTALL)
        if qm:
            out.append(qm.group(2))
    return out


def _clean_path(s):
    """Strip non-path tokens from a captured argument tail.

    `chmod -R 777 /` captures "-R 777 /"; only the path is interesting, so drop
    flags, octal modes and symbolic mode specs.
    """
    junk = re.compile(r"^-|[0-7]{3,4}$|^(?:[ugoa]*[+=-])+$")
    toks = [t for t in s.strip().strip("'\"").split() if not junk.match(t)]
    return " ".join(toks)


BASH_DENY_C = [(n, re.compile(p, re.IGNORECASE), r) for n, p, r in BASH_DENY]
TARGET_DENY_C = [(n, re.compile(p, re.IGNORECASE), pred, r) for n, p, pred, r in TARGET_DENY]
TARGET_WARN_C = [(n, re.compile(p, re.IGNORECASE), r) for n, p, r in TARGET_WARN]
PATH_DENY_C = [(n, re.compile(p), r) for n, p, r in PATH_DENY]
PATH_WARN_C = [(n, re.compile(p), r) for n, p, r in PATH_WARN]


def inspect_command(cmd, _depth=0):
    """-> list of (severity, rule, reason). severity in {'deny','warn'}."""
    if not cmd or not isinstance(cmd, str):
        return []
    hits = []
    stripped = "\n".join(l.split("#", 1)[0] for l in cmd.splitlines())

    # Indirect execution (`sh -c "..."`, `eval "..."`, `python -c "..."`) hides
    # its payload inside quotes that the prose-safe blanking below is designed
    # to erase. Inspect the unwrapped payload first; a bounded depth stops
    # pathological self-nesting from recursing forever.
    if _depth < 4:
        for inner in _wrapped_scripts(stripped):
            hits.extend(inspect_command(inner, _depth + 1))
    if any(h[0] == "deny" for h in hits):
        return [h for h in hits if h[0] == "deny"][:1]

    live = _blank_quotes(stripped)              # prose-safe: literals become spaces
    sql_live = re.sub(r"[\"']", "", stripped)  # literals rules need the statement text

    for name, rx, reason in BASH_DENY_C:
        hay = sql_live if name in LITERAL_RULES else live
        if rx.search(hay):
            hits.append(("deny", name, reason))
    if any(h[0] == "deny" for h in hits):
        return [h for h in hits if h[0] == "deny"]

    for name, rx, pred, reason in TARGET_DENY_C:
        for m in rx.finditer(live):
            try:
                if pred(_clean_path(m.group(1))):
                    hits.append(("deny", name, reason))
                    return hits
            except Exception:
                continue

    # warn tier: only when nothing was denied. Kept narrow on purpose -- a warn on
    # every `rm -rf node_modules` would train the user to ignore the tier.
    for name, rx, reason in TARGET_WARN_C:
        m = rx.search(live)
        if not m:
            continue
        try:
            path = _clean_path(m.group(1))
        except Exception:
            path = ""
        if name == "rm-home-tree" and not re.match(r"^(?:~/|/home/)[^\s]", path):
            continue
        hits.append(("warn", name, reason))
        break
    return hits


def inspect_path(path):
    if not path or not isinstance(path, str):
        return []
    p = os.path.expanduser(path.strip())
    if not os.path.isabs(p):
        return []  # relative -> inside the project; not our business
    home = os.path.expanduser("~")
    forms = [p]
    if home and p.startswith(home):
        forms.append("~" + p[len(home):])   # so `~/.ssh/id_rsa` rules match absolute paths
    for name, rx, reason in PATH_DENY_C:
        if any(rx.match(f) for f in forms):
            return [("deny", name, reason)]
    for name, rx, reason in PATH_WARN_C:
        if any(rx.match(f) for f in forms):
            return [("warn", name, reason)]
    return []


def inspect_text(path, text):
    """Scan the body of a script-shaped write for catastrophic commands.

    Returns [] unless `path` is script-shaped. A `# genie-guard: allow` comment
    on the offending line suppresses it -- a deliberately narrow opt-out, for
    the script that genuinely has to `sudo` or `rm -rf` a build directory.
    """
    if not text or not isinstance(text, str) or not path:
        return []
    base = os.path.basename(str(path))
    if not (SCRIPT_PATH.search(base) or text.lstrip().startswith("#!")):
        return []
    hits = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("+"):
            line = line[1:].strip()          # apply_patch diff body
        if not line or CONTENT_ALLOW.search(line):
            continue
        for severity, name, reason in inspect_command(line):
            if name in CONTENT_RULE_NAMES:
                hits.append((severity, "content:" + name,
                             "This script would run: " + reason))
                break
        else:
            for name, rx, pred, reason in TARGET_DENY_C:
                m = rx.search(_blank_quotes(line))
                if m and pred(_clean_path(m.group(1))):
                    hits.append(("deny", "content:" + name,
                                 "This script would run: " + reason))
                    break
        if hits:
            return hits[:1]
    return []


def _out(payload):
    json.dump(payload, sys.stdout)


def main():
    if os.environ.get("GENIE_ALLOW_DANGEROUS") == "1":
        # Premortem A7: a bypass that leaves no trace gets discovered months later,
        # by which point nobody remembers turning it on. Make it loud.
        try:
            log = os.path.expanduser("~/.claude/logs/genie-guard-bypass.log")
            os.makedirs(os.path.dirname(log), exist_ok=True)
            with open(log, "a") as fh:
                fh.write("GENIE_ALLOW_DANGEROUS=1 bypass active\n")
        except Exception:
            pass
        return
    try:
        data = json.loads(sys.stdin.read() or "{}")
        tool_input = data.get("tool_input")
        if not isinstance(tool_input, dict):
            return
        hits = inspect_command(tool_input.get("command"))
        if not hits:
            for key in ("file_path", "path", "notebook_path"):
                if tool_input.get(key):
                    hits = inspect_path(tool_input[key])
                    if hits:
                        break
        if not hits:
            target = next((tool_input.get(k) for k in ("file_path", "path") if tool_input.get(k)), None)
            if target:
                for key in CONTENT_KEYS:
                    if tool_input.get(key):
                        hits = inspect_text(target, tool_input[key])
                        if hits:
                            break
        if not hits:
            return
        severity, name, reason = hits[0]
        sys.stderr.write("genie-guard: %s by rule %s\n" % (severity, name))
        if severity == "deny":
            _out({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }})
        else:
            _out({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": reason,
            }})
    except Exception:
        return  # fail open


if __name__ == "__main__":
    main()
