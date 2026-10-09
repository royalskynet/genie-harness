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

  Reading is not denied. Printing a credential's *value* is (`secret-readout`):
  once it is on stdout it is in the transcript, and the transcript is sent to the
  model provider. `cut -d= -f1 .env` and `test -n "$X"` stay allowed.

Deliberately allowed: ordinary destructive-but-recoverable work
(`rm -rf node_modules`, `rm -rf dist`, `git reset --hard` on a feature branch).
Over-blocking a beginner's normal work is its own failure mode.

Known gap, on purpose: `rm -rf ~/Documents` is WARN-tier, not denied. There is
no reliable way to tell a project checkout from personal data, and inventing a
fuzzy heuristic would block real work. Codex's own sandbox mode and approval
policy are the boundary here; this complements them, it does not replace them.

Known gap, narrowed but not closed: variable indirection. `_resolve_local_vars`
expands literal `NAME=VALUE` assignments (command start or after `;`/`&&`/
newline, optional `export`) before matching, so `X=/; rm -rf $X` is caught.
It is still not a shell parser: pipes, subshells and arithmetic are untouched,
expanded text is never re-expanded, and a name assigned two different values is
left alone. The literal, hardcoded forms (`$HOME`, `${HOME}`, `~`) are still
recognized directly.

Failure policy: fail OPEN. Any internal error allows the call, because a guard
that breaks your terminal is worse than one that misses a phrase.

Escape hatch: GENIE_ALLOW_DANGEROUS=1 skips every rule.

Handoff: Genie is not a security suite. If the user picked another command guard
(`!owner guard=<tool>`) and that tool is a PreToolUse hook in Codex right now,
this gate stands down. Both conditions are required, so a prefs file alone can
never leave the machine unguarded, and uninstalling the other tool brings this
gate back on its own.
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
     "This force-pushes over a shared branch. Commits other people already pulled can disappear permanently. 改做：`git push --force-with-lease`，或先開一個新分支再推上去。"),
    ("delete-remote-branch",
     r"\bgit\s+push\b[^|;&]*(?:--delete\b|\s:)",
     "This deletes a remote branch for everyone. 改做：改 `git push origin <branch>:<branch>` 先保留一份，或改成封存（archive）而不是刪。"),
    ("rewrite-all-refs",
     r"\bgit\b[^|;&]*\b(?:filter-branch|filter-repo)\b",
     "This rewrites every commit in this repository's history. 改做：改用 `git rebase -i` 只改最近幾個 commit，或另開一個分支改寫、原分支留著當備份。"),
    ("drop-database",  # sql
     r"(?:^|[;&|]\s*|\b(?:mysql|mysqldump|psql|sqlite3?|mariadb|sqlcmd)\b[^|;&]*['\"]?\s*)(?:DROP\s+(?:DATABASE|SCHEMA)|\bdropdb\b)",
     "This drops a database and every row in it. 改做：先 `mysqldump --all-databases > backup.sql` 匯出備份，再在測試資料庫上試。"),
    ("drop-table",  # sql
     r"(?:^|[;&|]\s*|\b(?:mysql|mysqldump|psql|sqlite3?|mariadb|sqlcmd)\b[^|;&]*['\"]?\s*)DROP\s+TABLE\b",
     "This drops a table and every row in it. 改做：先 `mysqldump 表名 > 表名.sql` 匯出備份，再拿測試資料庫練一次。"),
    ("truncate-table",  # sql
     r"(?:^|[;&|]\s*|\b(?:mysql|mysqldump|psql|sqlite3?|mariadb|sqlcmd)\b[^|;&]*['\"]?\s*)TRUNCATE\b",
     "This empties a table irreversibly. 改做：改 `DELETE FROM 表名 WHERE ...`（可加 `LIMIT` 分批跑），或先匯出備份。"),
    ("db-reset",
     r"\b(?:prisma\s+migrate\s+reset|drizzle-kit\s+push\s+--force|rails\s+db:(?:reset|drop)|alembic\s+downgrade\s+base|flyway\s+clean|sequelize\s+db:(?:drop|reset))\b",
     "This resets the database to an empty state and drops all data. 改做：先 `pg_dump` 匯出備份，或改在測試資料庫跑一次 migrate。"),
    ("curl-pipe-shell",
     r"\b(?:curl|wget|fetch)\b[^|;&]*\|\s*(?:sudo\s+)?(?:ba|z|k|fi)?sh\b",
     "This downloads code from the internet and runs it immediately. Read it before running it. 改做：先 `curl -o install.sh <網址>` 存成檔案，讀過內容再 `bash install.sh`。"),
    ("pipe-into-shell",
     r"\|\s*(?:sudo\s+)?(?:ba|z|k|fi)?sh\b",
     "This pipes command output straight into a shell (decoded, generated, or otherwise). Read what it would run before running it. 改做：先存成檔案（`... > out.sh`），讀過內容再執行。"),
    ("publish-artifact",
     r"\b(?:npm\s+publish|yarn\s+publish|pnpm\s+publish|twine\s+upload|cargo\s+publish|gem\s+push|nuget\s+push|gh\s+release\s+create|docker\s+push)\b",
     "This publishes an artifact that other people and machines can pull. It cannot be pulled back. 改做：先 `npm publish --dry-run` 演練一次，或發到測試版（`npm publish --tag beta`）。"),
    ("write-credential",
     r"\b(?:gh\s+(?:secret|variable)\s+set|aws\s+configure\s+store\s+credentials|gcloud\s+auth\s+application-default\s+set)\b",
     "This writes credentials. Make sure you know exactly where they are going. 改做：改用環境變數（`export TOKEN=...`）或 macOS Keychain，不要把值寫進檔案。"),
    ("sudo-privileged",
     r"(?:^|[|;&]\s*|\s)sudo\s+(?!-h\b|--help\b|-v\b)",
     "This asks for administrator rights. I'd rather we not need them — tell me what you are trying to reach and I'll find a user-level way. 改做：改用使用者層級安裝，例如 `brew install`、`pip install --user`、`npm install`，或先說明你想解決什麼。"),
    ("terraform-destroy",
     r"\bterraform\s+(?:destroy\b|apply\b[^|;&]*-(?:destroy|replace)\b)",
     "This destroys or replaces cloud infrastructure, which usually means deleting real running services. 改做：先 `terraform plan -destroy` 看清會動到什麼，或只動單一資源 `terraform destroy -target=...`。"),
    ("s3-remove-bucket",
     r"\baws\s+s3\s+(?:rb|rm)\b[^|;&]*--recursive",
     "This deletes an entire S3 bucket and everything inside it. 改做：先 `aws s3 sync s3://bucket ./backup` 備份，或只刪一部分前綴 `aws s3 rm s3://bucket/prefix --recursive`。"),
    ("cloud-delete",
     r"\b(?:gcloud|az)\b[^|;&]*\sdelete\b",
     "This deletes cloud resources. 改做：先 `gcloud compute instances list` 列出資源並加上 `--dry-run` 演練，確認後再刪。"),
    ("kubectl-cluster-delete",
     r"\bkubectl\s+delete\b[^|;&]*\b(?:namespace|node|pvc|persistentvolumeclaim|pv|all)\b",
     "This deletes cluster-wide resources and may not be recoverable. 改做：改 `kubectl delete pod <名稱>` 只刪單一資源，或先 `kubectl get ns <名稱> -o yaml > backup.yaml` 備份。"),
    # `load` is the legacy form: bare path, no domain target, and it silently
    # loads an entire directory when handed one. `bootstrap gui/<uid> <plist>`
    # registers exactly one job and `bootout gui/<uid>/<label>` takes it back,
    # so that form stays allowed -- otherwise the reason text names a remedy
    # this very rule denies, and the model can never comply (fix: dead-end
    # advice loop hit by the Mythos bot, 2026-10-09).
    ("launch-agent-register",
     r"\blaunchctl\s+(?:load\b|bootstrap\s+(?!(?:gui|user)/))",
     "This registers a program that will run automatically on this machine from now on. 改做：改用 `launchctl bootstrap gui/$(id -u) <plist 路徑>` 帶完整 domain target（要收回用 `launchctl bootout gui/$(id -u)/<label>`），或放在專案裡用啟動腳本管理。"),
    # `bootout <domain>` with no label tears down every job in that domain, not
    # one service. `bootout gui/501/com.x.y` or a trailing plist path targets a
    # single job, so the lookahead only fires when a bare domain is followed by
    # the end of the line or a `;`/`&`/`|` separator.
    ("launchctl-domain-bootout",
     r"\blaunchctl\s+bootout\s+(?:(?:gui|user|login)/(?:\d+|\$\(\s*id\s+-u\s*\)|\$\{?UID\}?)|system)(?=\s*(?:[;&|]|\Z))",
     "This boots out a whole launchd domain: every background program on this machine stops and the login window comes back, and you cannot undo it from a remote session. 改做：改用 `launchctl bootout gui/$(id -u)/<label>` 只停那一個服務。"),
    ("shell-profile-write",
     r"[<>]{1,2}\s*~?/?\.(?:bashrc|zshrc|bash_profile|profile|zprofile|zshenv)\b",
     "This edits a shell startup file, which silently changes how every future terminal behaves. 改做：改寫專案內的 `.env` 或 Makefile，或先 `cp ~/.zshrc ~/.zshrc.bak` 留備份再改。"),
    ("git-clean-force",
     r"\bgit\s+clean\b(?=[^|;&]*-[a-zA-Z]*f)(?![^|;&]*-[a-zA-Z]*n)",
     "This deletes untracked and/or ignored files across the tree. `-n` first if you want to see the list. 改做：先 `git clean -nd` 看清楚清單，確認後才加 `-f`（或 `-x`）。"),
    ("python-rmtree-root",
     r"\b(?:shutil\.rmtree|fs\.rmSync|fs\.rmdirSync|os\.removedirs)\s*\(\s*['\"]?(?:/|~)(?:['\")\s,]|\Z)",
     "This deletes a whole directory tree from inside Python, and the filesystem root is not a normal target. 改做：在 Python 裡寫出完整路徑，例如 `shutil.rmtree('/Users/你/專案/build')`。"),
    ("os-remove-device",
     r"\bos\.(?:remove|unlink)\s*\(\s*['\"]?/dev/",
     "This removes a device node from inside Python. 改做：不要動 `/dev` 底下的節點；改用 `diskutil unmount /dev/diskN` 卸載磁碟區。"),
    ("mv-root-to-devnull",
     r"\bmv\b[^|;&]*\s(?:/|~|/\*|\$HOME)\s+/dev/null\b",
     "This moves a top-level path to /dev/null, which destroys it. 改做：改用 `rm -rf` 指定確切路徑，或先 `tar czf backup.tgz <路徑>` 備份再刪。"),
    ("truncate-device",
     r"\btruncate\b[^|;&]*/dev/",
     "This zeroes a raw device. 改做：改寫一般檔案，例如 `truncate -s 0 app.log`，不要對 `/dev` 底下的裝置。"),
    ("find-root-delete",
     r"\bfind\s+(?:/|~|\$HOME|\*)(?:\s|$)[^|;&]*-(?:delete|exec\s+rm|ok\s)",
     "This searches from the filesystem root and deletes. Narrow the search path first. 改做：把搜尋根改成專案路徑，例如 `find ~/project -name '*.log' -delete`。"),
    ("unlink-device",
     r"\bunlink\b[^|;&]*/dev/",
     "This removes a device node. 改做：不要刪 `/dev` 底下的節點；改用 `diskutil unmount /dev/diskN`。"),
    ("shell-history-wipe",
     r"(?:\bhistory\s+-c\b|\brm\b[^|;&]*~?/?\.(?:bash_history|zsh_history|local/share/fish/fish_history))",
     "This erases your shell history, which is usually the only record of what a command did. 改做：先 `history | grep 關鍵字 > ~/history-backup.txt` 留一份，或用 `history -d 行號` 只刪一筆。"),
    ("filesystem-wipe",
     r"(?:^|[;&|]\s*)\s*\b(?:mkfs(?:\.\w+)?|fdisk|parted|diskutil\s+\w*\b(?:erase|reformat|partition)\w*|shred|wipefs)\b",
     "This reformats or wipes a drive. Everything on it is gone. 改做：先 `diskutil list` 確認是哪一顆，格式化隨身碟時寫明確的 `/dev/diskN`。"),
]

# --- target-dependent deny rules ------------------------------------------
# The danger is the *path*, not the verb. `(name, command regex with one capture
# group for the path, path predicate, reason)`.
ROOTISH = re.compile(r"^(?:/|/\*|~+|~/+$|~/\*|\$HOME|\$\{HOME\}|/home/[^/]+|\*|\.\.|~/\.\w*)$")
TARGET_DENY = [
    ("rm-rootish",
     r"\brm\b(?=[^|;&]*(?:-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r|-[a-z]*r\b))([^|;&]+?)\s*(?:$|[;&|])",
     lambda p: bool(ROOTISH.match(p)),
     "This points `rm` at the filesystem root or your whole home folder. If you really mean it, say so and I'll narrow the path to the exact directory first. 改做：寫出要刪的資料夾完整路徑，例如 `rm -rf ~/project/build`。"),
    ("rm-no-preserve-root", r"\brm\b([^|;&]*?)--no-preserve-root",
     lambda p: True,
     "This deletes from the filesystem root and cannot be undone. 改做：改用確切路徑，例如 `rm -rf ~/project/build`；真的非刪根目錄不可，跟我說明原因再說。"),
    ("rm-recursive-system",
     r"\brm\b(?=[^|;&]*(?:-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r|-[a-z]*r\b))([^|;&]+?)\s*(?:$|[;&|])",
     lambda p: bool(re.match(r"^/(?:etc|System|usr|bin|sbin|private/etc|var|opt|home)(?:/|$)", p)),
     "This recursively deletes a system directory. 改做：改用套件自己的移除方式（`brew uninstall`、`npm uninstall`），或交給管理員處理，不要自己動系統資料夾。"),
    ("rm-device",
     r"\brm\b(?=[^|;&]*(?:-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r|-[a-z]*r\b))([^|;&]+?)\s*(?:$|[;&|])",
     lambda p: bool(re.match(r"^(?:/dev/|/dev/\w|/Volumes/\w*\s*$|/System/Volumes/Data/?$)", p)),
     "This recursively deletes a disk or a mounted volume. 改做：改 `diskutil unmount /dev/diskN` 卸載，或只刪磁碟區裡明確的檔案路徑。"),
    ("chmod-777-system",
     r"\bchmod\b(?=[^|;&]*\s-R\b)(?=[^|;&]*\b777\b)([^|;&]+?)\s*(?:$|[;&|])",
     lambda p: bool(re.match(r"^/(?:etc|System|usr|bin|sbin|private/etc|var|opt)?/?$|^\s*$", p)) or bool(re.match(r"^/(?:etc|System|usr|bin|sbin|private/etc|var|opt)(?:/|$)", p)),
     "This makes a system directory world-writable. 改做：只對專案目錄 chmod，或改用 `sudo chown` 指定擁有者。"),
    ("dd-to-device", r"\bdd\b[^|;&]*\bof=(\S+)",
     lambda p: p.startswith("/dev/"),
     "This writes raw bytes straight onto a device and destroys whatever is there. 改做：改寫到一般檔案，例如 `dd if=... of=./disk.img`，或先 `diskutil unmountDisk /dev/diskN`。"),
    ("disk-device-write", r"\b(?:diskutil\s+\w+|(?:cat|cp|mv|tee)\b[^|;&]*)(\s+)?(/dev/disk\d\S*)",
     lambda p: True,
     "This writes directly to a raw disk device. 改做：改寫到一般檔案，或先卸載磁碟區（`diskutil unmount /dev/diskN`）。"),
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
     "This writes into a system directory that macOS protects. It usually needs admin rights, which we should avoid. 改做：改寫到專案內的路徑，系統設定用專案自己的設定檔。"),
    ("launch-daemon", r"^/(?:Library/Launch(?:Daemons|Agents)|System/Library/LaunchDaemons)(?:/|$)",
     "This installs a program that will run automatically on this machine. 改做：plist 放在專案裡、用專案腳本管理啟動，不要寫進 /Library。"),
    ("private-key", r"^~?/?\.ssh/(?:id_|authorized_keys)",
     "This is an SSH private key. Writing to it can lock you out of your servers. 改做：不要動 `~/.ssh` 底下的金鑰，改在專案內用測試金鑰。"),
    ("cloud-credentials", r"^~?/?\.(?:aws/(?:credentials|config)|config/gcloud/credentials\.db|kube/config|docker/config\.json)$",
     "This is a credential file for a cloud or container tool. 改做：用環境變數，或走工具自己的登入流程（`aws configure`、`gcloud auth login`、`docker login`）。"),
    ("agent-credentials", r"^~?/?\.(?:codex/auth\.json|claude\.json|npmrc|pypirc|gem/credentials)$",
     "This is a credential or token file. Writing here can leak or destroy your access. 改做：改用環境變數（`export NPM_TOKEN=...`），不要手寫 token 檔。"),
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


# Literal `NAME=VALUE` assignments: command start, or after `;`/`&&`/newline,
# optional `export` prefix. This exists so `X=/; rm -rf $X` is seen as what it
# is. Not a shell parser: pipes, subshells and arithmetic are untouched.
ASSIGN_RE = re.compile(
    r"(?:^|[;&\n])\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(\"[^\"]*\"|'[^']*'|[^\s;&|]+)"
)


def _resolve_local_vars(cmd):
    """Expand literal `NAME=VALUE` assignments so `$NAME` can be matched.

    Only assignments at the command start or after `;`/`&&`/newline count, the
    value is taken literally (quotes stripped), and only `$NAME`/`${NAME}`
    occurrences *after* the assignment are replaced. A name assigned two
    different values is left alone -- guessing which one the shell would use is
    how false denies happen.
    """
    found = []
    values = {}
    for m in ASSIGN_RE.finditer(cmd):
        name, raw = m.group(1), m.group(2)
        if raw[0] == raw[-1] and raw[0] in "\"'":
            raw = raw[1:-1]
        found.append((name, raw, m.end()))
        values.setdefault(name, set()).add(raw)
    ambiguous = {n for n, vs in values.items() if len(vs) > 1}
    out = cmd
    # Backward order: each replacement only rewrites text at or after its own
    # assignment, so earlier assignments' positions stay valid.
    for name, value, end in sorted(found, key=lambda a: -a[2]):
        if name in ambiguous:
            continue
        tail = re.sub(r"\$\{%s\}|\$%s\b" % (re.escape(name), re.escape(name)),
                      lambda _: value, out[end:])
        out = out[:end] + tail
    return out


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
    stripped = _resolve_local_vars(stripped)

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

    # Printing a secret is its own catastrophe, and it is a function of the
    # command rather than of a keyword, so it lives next to the tables above
    # rather than inside one of them.
    hits = inspect_secret_readout(stripped)
    if hits:
        return hits

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


# --- beginner footguns that depend on the repo's state ---------------------
# Warn only: each is fine in the right state, and a beginner cannot tell the
# states apart. `dirty` rules stay quiet on a clean tree, so the common
# `git reset --hard` on a feature branch costs nothing.
GIT_WARN = [
    ("git-discard-changes", "dirty",
     r"\bgit\s+(?:reset\b[^|;&]*--hard|checkout\b[^|;&]*\s--(?:\s|$)|checkout\s+\.(?:\s|$)"
     r"|restore\b(?![^|;&]*--staged))",
     "This throws away changes that were never saved in git, and git cannot bring them "
     "back. Tell the user which files have unsaved changes and get a yes first, or "
     "`git stash` them."),
    ("git-stash-destroy", None, r"\bgit\s+stash\s+(?:clear|drop)\b",
     "This permanently deletes saved-aside work (stashes). Check `git stash list` with "
     "the user first."),
    ("git-branch-force-delete", None, r"\bgit\s+branch\s+[^|;&]*(?:-D\b|--delete\s+--force|-df\b)",
     "This deletes a branch even if its work was never merged anywhere. Use `-d` (lower "
     "case), which refuses when work would be lost."),
    ("secret-staged", "secret", r"\bgit\s+(?:add\b|commit\b[^|;&]*\s-[a-zA-Z]*a)",
     "A file that looks like passwords or API keys (.env, *.pem, *.key, credentials) "
     "is about to go into git. Once pushed, the keys are public and must be replaced. "
     "Add it to .gitignore first and tell the user."),
    ("repo-public", None,
     r"\bgh\s+repo\s+(?:create\b[^|;&]*--public|edit\b[^|;&]*--visibility[=\s]+public)",
     "This makes the repository visible to everyone on the internet. Confirm with the "
     "user, and check it holds no keys or personal data first."),
]
GIT_WARN_C = [(n, cond, re.compile(p), r) for n, cond, p, r in GIT_WARN]
SECRET_FILE = re.compile(
    r"(?:^|/)(?:\.env(?!\.(?:example|sample|template)\b)(?:\.[\w.-]+)?|[^/]+\.(?:pem|key|p12)"
    r"|id_(?:rsa|ed25519|ecdsa)|credentials(?:\.json)?|secrets?\.(?:json|ya?ml|env))$")


# --- secret-readout ----------------------------------------------------------
# A credential's *value* is the one thing this gate cannot let through quietly:
# once it is printed it is in the transcript, and the transcript goes to the
# model provider and stays in the user's scrollback. `rm -rf /` is a disaster you
# can undo by not running it; this one is done the moment it prints.
#
# Reading is still allowed. Only the value is denied: `cut -d= -f1 .env`,
# `grep -c`, `wc -l` and `test -f` hand over a name or a number, which is exactly
# what you need to answer "is this set?" without handing over the secret.
SECRET_READOUT_REASON = (
    "The value would be copied into this conversation and sent to the model provider. "
    "改做：只看變數名用 `cut -d= -f1 .env`；確認有沒有設用 `test -n \"$X\" && echo set`。"
)
# Commands whose whole job is to put a file's bytes on stdout.
READER_RE = re.compile(r"\b(?:cat|less|more|head|tail|bat|nl|strings|xxd|od)\b([^|;&]*)")
# `printenv`/`env`/`set` with no argument dump every variable in the environment.
ENV_DUMP_RE = re.compile(r"\s*(?:printenv|env|set)\s*")
# `$NAME` / `${NAME}` in an echo/printf argument.
VAR_REF = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
# A variable whose *name* says it holds a credential.
SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD", re.IGNORECASE)


def _is_secret_path(tok):
    """True when an argument names a credential file. `SECRET_FILE` is the one
    definition of "looks like a secret file" in this file -- reused, not copied."""
    return bool(SECRET_FILE.search(tok.strip().strip("\"'")))


def inspect_secret_readout(cmd):
    """-> [] or [("deny", "secret-readout", reason)] for a command that would
    print a credential's value.

    Three shapes, all of them a deliberate move rather than an accident:
    a file reader aimed at a secret file, a whole-environment dump, or an
    echo/printf interpolating a variable named like a credential.
    """
    if not cmd or not isinstance(cmd, str):
        return []
    live = _blank_quotes("\n".join(l.split("#", 1)[0] for l in cmd.splitlines()))
    deny = [("deny", "secret-readout", SECRET_READOUT_REASON)]

    for m in READER_RE.finditer(live):
        if any(_is_secret_path(tok) for tok in m.group(1).split()):
            return deny
    # Bare `printenv`/`env`/`set` is the whole environment, keys included --
    # also as the head of a pipeline (`env | grep TOKEN`). With arguments, `env`
    # runs a command and `set` sets shell options (`gh secret set API_KEY`,
    # `env API_KEY=x node app` print nothing), so only `printenv NAME` -- whose
    # arguments are names to print -- is a lookup worth denying.
    if any(ENV_DUMP_RE.fullmatch(seg) for seg in re.split(r"[|;&]", live)):
        return deny
    for m in re.finditer(r"(?<![\w.-])printenv\b([^|;&]*)", live):
        if any(SECRET_NAME.search(a) for a in m.group(1).split()):
            return deny
    for m in re.finditer(r"\b(?:echo|printf)\b([^|;&]*)", live):
        if any(SECRET_NAME.search(v.group(1)) for v in VAR_REF.finditer(m.group(1))):
            return deny
    return []


def inspect_read_path(path):
    """The `Read` tool only ever gets the value-leak rule.

    The write-target rules below are about *writing* into a system or credential
    file, which is a different mistake from reading one, and applying them to
    `Read` would block ordinary debugging. So: does the filename look like a
    secret file, and nothing else.
    """
    if not path or not isinstance(path, str):
        return []
    base = os.path.basename(os.path.expanduser(path.strip()))
    if _is_secret_path(base):
        return [("deny", "secret-readout", SECRET_READOUT_REASON)]
    return []


def _git_changes(cwd):
    """-> changed/untracked paths git would see, or None when unknown."""
    import subprocess
    try:
        out = subprocess.run(["git", "-C", cwd or ".", "status", "--porcelain",
                              "--untracked-files=all"], capture_output=True, text=True,
                             timeout=2).stdout
    except Exception:
        return None
    return [l[3:].split(" -> ")[-1].strip('"') for l in out.splitlines() if len(l) > 3]


def inspect_git(cmd, cwd=None):
    """State-aware warn tier. Runs `git status` only when a rule's text matched."""
    if not cmd or not isinstance(cmd, str):
        return []
    live = _blank_quotes("\n".join(l.split("#", 1)[0] for l in cmd.splitlines()))
    for name, cond, rx, reason in GIT_WARN_C:
        if not rx.search(live):
            continue
        if cond == "dirty":
            if _git_changes(cwd) == []:
                continue  # clean tree: nothing to lose; unknown state still warns
        elif cond == "secret":
            named = any(SECRET_FILE.search(t) for t in cmd.split())
            if not named and not any(SECRET_FILE.search(c) for c in _git_changes(cwd) or []):
                continue
        return [("warn", name, reason)]
    return []


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
    # ensure_ascii=False plus an explicit utf-8 write: the deny reason carries
    # its `改做：` line, and json.dump's default escaping would ship it as
    # \\uXXXX -- unreadable to the person the message is for.
    text = json.dumps(payload, ensure_ascii=False)
    buf = getattr(sys.stdout, "buffer", None)
    if buf is None:
        sys.stdout.write(text)
    else:
        buf.write(text.encode("utf-8"))


def _handed_off():
    """True when the user gave this job to another installed command guard.

    Two gates, both required: the user chose it (`!owner guard=<tool>`), and that
    tool is a PreToolUse hook in Codex right now. A prefs file alone, hostile or
    stale, can never leave the machine with no guard at all.
    """
    try:
        import prefs
        data = prefs.load()
        if not data.get("owners", {}).get("guard"):
            return False
        import overlap
        return bool(prefs.owner_of("guard", data, overlap.scan()))
    except Exception:
        return False


def _allowed_rules():
    """Rule names this environment has whitelisted via `GENIE_GUARD_ALLOW`.

    Why per-rule and not just `GENIE_ALLOW_DANGEROUS=1`: an unattended bot that
    legitimately maintains its own launchd jobs needs exactly one rule to stand
    down, and turning off all 60-odd of them to get it is the worse trade. Comma
    separated, rule names as they appear in the tables above.
    """
    raw = os.environ.get("GENIE_GUARD_ALLOW", "")
    return {n.strip() for n in raw.split(",") if n.strip()}


def _log_bypass(what):
    # Premortem A7: a bypass that leaves no trace gets discovered months later,
    # by which point nobody remembers turning it on. Make it loud.
    try:
        log = os.path.expanduser("~/.claude/logs/genie-guard-bypass.log")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "a") as fh:
            fh.write("%s\n" % what)
    except Exception:
        pass


def main():
    if os.environ.get("GENIE_ALLOW_DANGEROUS") == "1":
        _log_bypass("GENIE_ALLOW_DANGEROUS=1 bypass active")
        return
    if _handed_off():
        return
    try:
        data = json.loads(sys.stdin.read() or "{}")
        tool_input = data.get("tool_input")
        if not isinstance(tool_input, dict):
            return
        hits = []
        if data.get("tool_name") == "Read":
            # A read has no write target, so the write-path rules below are the
            # wrong instrument for it. Only the value-leak rule applies.
            hits = inspect_read_path(tool_input.get("file_path"))
        else:
            hits = inspect_command(tool_input.get("command"))
            if not hits:
                hits = inspect_git(tool_input.get("command"), data.get("cwd"))
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
        allowed = _allowed_rules()
        if allowed:
            for _, name, _r in hits:
                if name in allowed:
                    _log_bypass("GENIE_GUARD_ALLOW bypass: rule %s" % name)
            hits = [h for h in hits if h[1] not in allowed]
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
