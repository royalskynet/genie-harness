#!/usr/bin/env python3
"""Tiny Semantic Router for Genie Harness.

Codex `UserPromptSubmit` hook. Reads the hook JSON on stdin, prints ONE line
of developer context: `genie: intent=<label> conf=<high|low>`. AGENTS.md decides
what to do with the label, so Codex never spends reasoning on intent detection.

Two tiers, cheapest first:
  1. regex keywords            (0 ms, zero deps)
  2. static embeddings + cosine to intent centroids
     (~0.1 s, CPU only, dep: numpy; model = pruned potion-multilingual-128M,
      greedy longest-match tokenizer, int8 rows -> ~35 MB disk, ~60 MB RAM)

Below threshold the router stays silent: no `intent=` tag and no `DO:` line,
only the turn's prefs. An earlier version emitted `intent=unsure` with a DO
line telling the model to ask which of two readings was meant. 282 logged
routes say that was the wrong trade: 55% of real user turns land below the
threshold, and on those the host model already understands the message better
than a 128M cosine classifier does. A label it cannot stand behind overrides
that understanding -- the model asked a clarifying question instead of just
answering. Abstaining means abstaining: heuristics -> embedding -> say nothing.

Then it dispatches. The label alone made the model look up what to do in a
table; a beginner never types `$wheel`, so the hook says it outright: one `DO:`
line naming the skill to use this turn, followed by the turn's prefs. This is
the only UserPromptSubmit hook; prefs live in prefs.py.

Never fails loudly: any error -> default intent with conf=low.
CLI: `genie_router.py "some text"`  or  `echo text | genie_router.py --text`.
Hook: `genie_router.py [--host codex|claude]` with the hook JSON on stdin.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
# install.sh puts the model in the checkout; the Claude Code plugin puts it in
# ~/.genie/model, because the plugin directory is replaced on every update.
MODEL_DIR = os.environ.get("GENIE_MODEL_DIR") or next(
    (d for d in (os.path.join(HERE, "model"), os.path.expanduser("~/.genie/model"))
     if os.path.isfile(os.path.join(d, "vocab.json"))), os.path.join(HERE, "model"))
INTENTS = json.load(open(os.path.join(HERE, "intents.json"), encoding="utf-8"))
UNSURE = "unsure"

# Long session reminder
LONG_SESSION_DEFAULT_MIN = 150
LONG_SESSION_THROTTLE_SEC = 30 * 60  # 30 minutes


def _check_long_session(data):
    """Check if session has run long enough to warrant a reminder.
    Returns reminder string or None.
    Reads at most first 20 lines of transcript JSONL for first timestamp.
    Throttles via a mark file in $GENIE_STATE_DIR/long-<session_id>.
    """
    try:
        threshold = int(os.environ.get("GENIE_LONG_SESSION_MIN", str(LONG_SESSION_DEFAULT_MIN)))
    except Exception:
        threshold = LONG_SESSION_DEFAULT_MIN
    if threshold == 0:
        return None

    transcript_path = data.get("transcript_path")
    session_id = data.get("session_id")
    if not transcript_path or not session_id:
        return None

    # Sanitize session_id for filesystem
    safe_sid = re.sub(r"[^A-Za-z0-9_-]", "", session_id)
    if not safe_sid:
        return None

    # Read first timestamp from transcript (max 20 lines)
    ts = None
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 20:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if "timestamp" in rec:
                        ts_str = rec["timestamp"]
                        # Parse ISO8601, handle Z suffix
                        if ts_str.endswith("Z"):
                            ts_str = ts_str[:-1] + "+00:00"
                        ts = datetime.fromisoformat(ts_str)
                        break
                except Exception:
                    continue
    except Exception:
        return None

    if ts is None:
        return None

    # Ensure ts is timezone-aware
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    elapsed_min = int((now - ts).total_seconds() // 60)
    if elapsed_min < threshold:
        return None

    # Throttle: check mark file
    state_dir = os.environ.get("GENIE_STATE_DIR", os.path.expanduser("~/.genie/state"))
    mark_path = os.path.join(state_dir, f"long-{safe_sid}")
    try:
        os.makedirs(state_dir, exist_ok=True)
        if os.path.exists(mark_path):
            with open(mark_path, "r", encoding="utf-8") as f:
                last = int(f.read().strip() or "0")
            if time.time() - last < LONG_SESSION_THROTTLE_SEC:
                return None
        # Write new mark
        with open(mark_path, "w", encoding="utf-8") as f:
            f.write(str(int(time.time())))
    except Exception:
        pass  # throttle is best-effort

    return (
        f"LONG SESSION: this conversation has run {elapsed_min} minutes. "
        f"Long sessions get slower and can crash. Before the next big step, "
        f"write a short progress summary, then suggest starting a fresh conversation "
        f"with /clear (/compact does not free memory)."
    )


# Route extension imports
try:
    sys.path.insert(0, HERE)
    import route_ext as rx
except Exception:
    rx = None


def regex_tier(text):
    low = text.lower()
    # Asking for other people's solutions is research at any length; only a
    # stop case outranks it.
    for kw in INTENTS["intents"]["risky_action"].get("keywords", []):
        if re.search(kw, low):
            return "risky_action", "regex:" + kw
    for kw in INTENTS.get("wheel_sure", []):
        if re.search(kw, low):
            return "research_needed", "regex-wheel:" + kw
    # ponytail: first matching intent wins, order in intents.json = priority
    for name, spec in INTENTS["intents"].items():
        for kw in spec.get("keywords", []):
            if re.search(kw, low):
                return name, "regex:" + kw
    return None, None


_cache = {}
_warned = set()


def _warn_once(msg):
    """Print to stderr at most once per process. A hook runs one process per
    prompt, so this is once per prompt -- enough to be visible, not enough to
    be noise. C3: a silently degraded router is worse than a loud one."""
    if msg not in _warned:
        _warned.add(msg)
        sys.stderr.write(msg + "\n")


def _load_model():
    if "m" in _cache:
        return _cache["m"]
    import numpy as np

    pieces = json.load(open(os.path.join(MODEL_DIR, "vocab.json"), encoding="utf-8"))
    idx = {p: i for i, p in enumerate(pieces)}
    emb = np.load(os.path.join(MODEL_DIR, "emb_int8.npy"), mmap_mode="r")
    scale = np.load(os.path.join(MODEL_DIR, "scale.npy"))
    _cache["m"] = (idx, max(len(p) for p in pieces), emb, scale, np)
    return _cache["m"]


def tokenize(text):
    """Metaspace + greedy longest match. ponytail: greedy not Viterbi; agreed 10/10
    with the official tokenizer on router labels, swap in `tokenizers` if it drifts."""
    idx, maxlen, _, _, _ = _load_model()
    s = "▁" + unicodedata.normalize("NFKC", text).replace(" ", "▁")
    out, i, n = [], 0, len(s)
    while i < n:
        for L in range(min(maxlen, n - i), 0, -1):
            j = idx.get(s[i:i + L])
            if j is not None:
                out.append(j)
                i += L
                break
        else:
            i += 1  # unknown char: skip
    return out


def embed(text):
    _, _, emb, scale, np = _load_model()
    ids = tokenize(text)
    if not ids:
        return None
    v = (emb[ids].astype(np.float32) * scale[ids][:, None]).mean(0)
    n = np.linalg.norm(v)
    return v / n if n else None


def _centroids():
    if "c" in _cache:
        return _cache["c"]
    np = _load_model()[4]
    cents = {}
    for name, spec in INTENTS["intents"].items():
        vs = [v for v in (embed(e) for e in spec["examples"]) if v is not None]
        if vs:
            c = np.mean(vs, 0)
            cents[name] = c / np.linalg.norm(c)
    _cache["c"] = cents
    return cents


def embedding_tier(text):
    v = embed(text)
    if v is None:
        return None, 0.0
    best, score = None, -1.0
    for name, c in _centroids().items():
        s = float(v @ c)
        if s > score:
            best, score = name, s
    return best, score


def classify(text):
    """-> (intent, score, why). `intent` is UNSURE when the router abstains."""
    text = (text or "").strip()
    if not text:
        return UNSURE, 0.0, "empty"
    name, why = regex_tier(text)
    if name:
        # A keyword in a long message is usually incidental ("...commit 是什麼
        # 是否有必要" is not a teach_me). Past the cap the hit is a guess: tag
        # it, score it below high_threshold so it gets no DO line. risky_action
        # stays sure at any length -- the stop case must not soften.
        # ponytail: char count, so English gets the same cap as CJK; measure
        # per-script from route.log if English long-hits show up.
        prose = SECRET_RUN.sub("", text)  # a pasted key or path is not wording
        if len(prose) > INTENTS.get("regex_sure_len", 40) and name != "risky_action" \
                and not why.startswith("regex-wheel:"):
            return name, 0.5, "regex-long:" + why[len("regex:"):]
        return name, 1.0, why
    try:
        name, score = embedding_tier(text)
    except Exception as e:  # model missing / broken -> stay useful
        _warn_once("genie-router: embedding model unavailable at %s (%s: %s); "
                   "falling back to the default intent. Accuracy is degraded."
                   % (MODEL_DIR, type(e).__name__, e))
        return INTENTS["default"], 0.0, "fallback:" + type(e).__name__
    if name is None or score < INTENTS["threshold"]:
        return UNSURE, score, "below-threshold"
    return name, score, "embedding"


def confidence(intent, score, why):
    """short regex hit = certain; the rest needs to clear high_threshold."""
    if why.startswith(("regex:", "regex-wheel:")):
        return "high"
    if intent == UNSURE or why.startswith(("fallback:", "empty")):
        return "low"
    # "Broken" is a fact about the world, not a tone: embeddings put praise,
    # medical questions and design asks here (10-04..07 log: 48 embedding-only
    # fix_request at conf=high; the sampled ones were none of them broken
    # things). Keywords only.
    if intent in INTENTS.get("embed_never_high", ()):
        return "low"
    return "high" if score >= INTENTS.get("high_threshold", 0.55) else "low"


# Calibration log: one JSONL line per classified prompt, so "the router gets
# this label wrong" is a claim you can check instead of argue about. Purely
# local, opt-out, redacted, and fail-open -- a broken log must never cost the
# user their routing line.
LOG_MAX_BYTES = 1024 * 1024
# API keys, tokens, long paths: any run of 24+ url-safe chars is opaque, not prose.
SECRET_RUN = re.compile(r"[A-Za-z0-9_\-]{24,}")

# High-confidence secret shapes with known prefixes. Only these trigger the
# SECRET: injection line -- the generic SECRET_RUN is too noisy for that.
SECRET_SHAPES = [
    re.compile(r"(?<![A-Za-z0-9])sk-ant-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"(?<![A-Za-z0-9])github_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}"),
    re.compile(r"(?<![A-Za-z0-9])xox[abpr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"(?<![A-Za-z0-9])-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


def log_path():
    """`GENIE_LOG` wins (a path, or "0" to opt out); default under the real home
    dir, resolved late so a test or the hook's HOME override is honoured."""
    env = os.environ.get("GENIE_LOG")
    if env == "0":
        return None
    if env:
        return os.path.expanduser(env)
    return os.path.join(os.path.expanduser("~/.genie"), "route.log")


def _append_line(path, line):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    # Rotate before appending so a full file is never the one we add to: the
    # previous file stays whole as route.log.1 and the new one starts empty.
    if os.path.exists(path) and os.path.getsize(path) > LOG_MAX_BYTES:
        os.replace(path, path + ".1")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def log_route(text, intent, score, via, conf, ext=None):
    """Append one redacted JSONL record. Every error is swallowed: the hook's
    job is to route, and a permission error in $HOME is not the user's problem
    to solve mid-prompt.

    `GENIE_REPLAY=1` marks the record `"replay": true`. Replaying the log
    through the router to measure a change is the obvious way to test one, and
    it writes every input back as a fresh route: a few hundred of those bury
    the real traffic, and afterwards nothing tells them apart except a guess at
    write density. Set it when feeding the router anything but a live prompt.
    `GENIE_LOG=0` still drops the record entirely.
    `ext` is written only when the route extension ran (non-None)."""
    try:
        path = log_path()
        if not path:
            return
        clean = SECRET_RUN.sub("[REDACTED]", (text or "")[:200])
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "intent": intent, "score": round(float(score), 2),
               "via": via, "conf": conf, "text": clean}
        if ext is not None:
            rec["ext"] = ext
        if os.environ.get("GENIE_REPLAY") not in (None, "", "0"):
            rec["replay"] = True
        _append_line(path, json.dumps(rec, ensure_ascii=False))
    except Exception:
        pass


# How each host names a skill. Codex: `$wheel`. Claude Code loads Genie as a
# plugin, so its skills are namespaced and invoked through the Skill tool.
SKILL_REF = {"codex": "$%s", "claude": "the genie-harness:%s skill"}

# intent -> what to do this turn. `{wheel}` etc. become host skill references.
# Wheel-first is the point: once the user's goal is known, find what already
# does it before proposing how. A beginner cannot judge a hand-rolled plan.
DO = {
    # "MUST ... first" is deliberate: a soft "run X" was skipped ~1 in 4 turns
    # in headless Claude Code runs, because the model already "knew" an answer.
    "build_request": "the user wants something that does a job. Your FIRST action this "
                     "turn MUST be {wheel} (Quick), before writing any reply, even if you "
                     "think you know the answer: apps, services, built-in features, "
                     "packages or templates that already do it. Then the verdict in plain "
                     "words and at most 3 options (simplest -> balanced -> freest), "
                     "recommend one, and wait for their pick before building.",
    "research_needed": "your FIRST action this turn MUST be {wheel}, before answering: "
                       "official docs, community consensus, mature repos. Versions and "
                       "prices from official pages, not memory.",
    "execute_request": "use {genie-execute}: do every reversible step in one go, stop only "
                       "before an irreversible one. A new dependency with 2+ candidates -> "
                       "{wheel} first.",
    "fix_request": "something that used to work is broken. Reproduce it and read the exact "
                   "error first. If the cause is not obvious, search the exact error text "
                   "with {wheel}. Fix the cause, not the symptom, then rerun and paste the "
                   "real output. Two failed fixes -> stop and run {wheel}; do not try a third "
                   "variant.",
    "clear_request": "just do it, run it, then say in one line what changed.",
    "teach_me": "use {genie-explain} ({genie-terms} for the one key term); end by checking "
                "they understood.",
    "user_confused": "use {genie-explain}: shorter, fewer terms, one analogy at their level; "
                     "stay at that level for the rest of the conversation.",
    "risky_action": "say in one plain sentence what this does and whether it can be undone, "
                    "then wait for a yes.",
    "ambiguous_request": "their goal is not clear yet. Never answer only that you cannot. "
                         "Ask ONE question that offers at most 3 concrete readings of what "
                         "you CAN do toward it here (tools on this machine, a free app, a "
                         "script), phrased like 'Do you mean A or B? I can ...'. Say in one "
                         "plain sentence any part you physically cannot do (e.g. hold a "
                         "camera). Once the goal is clear, run {wheel} before proposing how.",
    "continue": "they are answering your last message (a yes or a pick). Carry on with that "
                "plan; do not ask again.",
    # No entry for UNSURE on purpose: hook() returns prefs only and never calls
    # dispatch() for it. See the module docstring.
    # model missing (e.g. still downloading): the label is a placeholder, so
    # hand the judgment back instead of dispatching "just do it".
    "degraded": "the intent router could not classify this message (model unavailable). "
                "Judge it yourself: if they want something built or a tool chosen, your "
                "FIRST action MUST be {wheel}; if it is irreversible, confirm first.",
}
WHEEL_INTENTS = ("build_request", "research_needed")
# Intents where doing something beats describing it, so a senior user should be
# pointed at what is already installed rather than at a fresh design.
LOCAL_TOOL_INTENTS = ("build_request", "research_needed", "execute_request",
                      "clear_request", "fix_request")
LOCAL_TOOL_LEVELS = ("advanced", "expert")
# Wheel answers "does a wheel exist?". This asks the narrower question that only
# someone senior should be told: what can I run right now, here. Beginner and
# intermediate users get it as noise -- they cannot read `--help`, and a list of
# tools to try is another thing to fail at.
LOCAL_TOOLS = " Prefer what is already on this machine (skills, CLIs via `--help`, repo scripts)."
# The user turned research off: same flow, no prior-art search.
DO_NO_WHEEL = {
    "build_request": "the user wants something that does a job (research is off, so no "
                     "prior-art search). Give at most 3 options (simplest -> balanced -> "
                     "freest), recommend one, and wait for their pick before building.",
    "research_needed": "answer from official docs (research is off, so no wider search); "
                       "say how current your source is.",
    "execute_request": "use {genie-execute}: do every reversible step in one go, stop only "
                       "before an irreversible one.",
    "fix_request": "something that used to work is broken. Reproduce it and read the exact "
                   "error first (research is off, so no wider search). Fix the cause, not "
                   "the symptom, then rerun and paste the real output. Two failed fixes -> "
                   "stop and report that instead of trying a third variant.",
    "ambiguous_request": "their goal is not clear yet. Never answer only that you cannot. "
                         "Ask ONE question that offers at most 3 concrete readings of what "
                         "you CAN do toward it here (tools on this machine, a free app, a "
                         "script), phrased like 'Do you mean A or B? I can ...'. Say in one "
                         "plain sentence any part you physically cannot do (e.g. hold a "
                         "camera).",
    "degraded": "the intent router could not classify this message (model unavailable). "
                "Judge it yourself; if it is irreversible, confirm first.",
}


FIXINDEX_FIRST = (" Before anything else run `fixindex find \"<exact error>\"` (their fix log); "
                  "follow a matching entry. After the fix, record it with `fixindex fi`.")

# UserPromptSubmit is a shared pipe: the host also sends turns nobody typed --
# a finished background task, the stdout of a slash command, a pasted block.
# 23 of 282 logged routes were those, and 14 came back `fix_request`, because a
# task report quotes the error it already handled. A label on a machine turn is
# worse than no label: it dispatches skills for work the user never asked for.
# So drop the turn here rather than tighten the classifier -- when a classifier
# misfires, first check its input is the thing it should be classifying.
NOT_USER_TURN = re.compile(
    r"\s*(?:<\s*(?:task-notification|local-command-stdout|local-command-stderr|"
    r"command-message|command-name|command-args|system-reminder|pasted_content|"
    r"function_results|user-prompt-submit-hook)\b"
    r"|\[(?:Artifact comment sent to Claude|Request interrupted)\b)", re.I)


def dispatch(intent, res, host="codex"):
    """-> the `DO:` line. `res` is prefs.resolve(); research off or handed to
    another tool changes who looks for prior art, never whether we ask first."""
    ref = SKILL_REF.get(host, SKILL_REF["codex"])
    do = DO.get(intent, DO["clear_request"])
    blocks, handed = res.get("blocks", {}), res.get("handed_off", {})
    # prefs.BUILD saw "about to build" even though the label is something else
    if intent not in WHEEL_INTENTS + ("risky_action", "continue") and \
            blocks.get("research") == "on" and "research" in res.get("turn_overrides", {}):
        do = DO["build_request"]
    if handed.get("research"):
        wheel = "%s (the user's prior-art tool)" % handed["research"]
    elif blocks.get("research") == "off":
        wheel = ""
        do = DO_NO_WHEEL.get(intent, do)
    else:
        wheel = ref % "wheel"
    # A DO line that names a block the user switched off is an order the model
    # has to disobey; it learns to skip DO lines. Name only what is on.
    if intent == "teach_me":
        if blocks.get("terms") == "off":
            do = do.replace(" ({genie-terms} for the one key term)", "")
        if blocks.get("examples") == "off":
            do = do.replace("use {genie-explain}", "answer directly, no examples or analogies")
    names = ("genie-execute", "genie-explain", "genie-terms")
    line = "DO: " + do.format(wheel=wheel, **{n: ref % n for n in names})
    # The user's own fix log knows this machine's past breakages; ask it before the web.
    if intent == "fix_request" and shutil.which("fixindex"):
        line += FIXINDEX_FIRST
    if res.get("level") in LOCAL_TOOL_LEVELS and intent in LOCAL_TOOL_INTENTS:
        line += LOCAL_TOOLS
    return line


def _run_ext(cmd, payload, timeout):
    """Run a configured extension command; stdout on rc=0, else "". Never raises."""
    try:
        p = subprocess.run(cmd, input=json.dumps(payload, ensure_ascii=False),
                           capture_output=True, text=True, timeout=timeout)
        return p.stdout.strip() if p.returncode == 0 else ""
    except Exception:
        return ""


def route_ext(data, text, host, intent, conf):
    """User routing table + tier + optional escalate/turn commands, all
    configured in route_ext.json (see route_ext.load_config). Returns (lines, ext_log); ([], None)
    when no config. Shadow mode logs the decision but injects nothing and
    skips turn_cmd, so the L1 gate stays with whoever owns it today."""
    cfg = rx.load_config(host)
    if cfg is None or not rx.eligible(text):
        return [], None
    table = os.path.expanduser(cfg.get("table") or "")
    md = open(table, encoding="utf-8").read() if table and os.path.isfile(table) else ""
    routes = rx.parse_routes(md, cfg.get("heading") or "任務路由表")
    hit, _m, strong = rx.match(routes, text)
    shadow = bool(cfg.get("shadow"))
    route, tier, ask, esc, phase = hit, None, False, None, None
    # Strong local hit is decided for free; everything else (weak hit or no
    # hit at all) is the grey band the escalate command exists for.
    if not strong and cfg.get("escalate_cmd"):
        cmd = list(cfg["escalate_cmd"]) + (["--dry"] if shadow else [])
        out = _run_ext(cmd, {"prompt": text, "transcript_path": data.get("transcript_path", ""),
                             "cwd": data.get("cwd") or os.getcwd(), "session_id": data.get("session_id", ""),
                             "routes": [{"when": r["when"], "action": r["action"]} for r in routes]}, 4)
        try:
            res = json.loads(out.splitlines()[-1]) if out else {}
        except ValueError:
            res = {}
        esc = res.get("status") or "fail"
        if esc == "ok":
            tier = res.get("tier") if res.get("tier") in ("L0", "L1", "L2") else None
            idx = res.get("route")
            # The judge saw the prompt and abstained: that is a verdict, so
            # the weak hit is dropped rather than patched back in.
            route = routes[idx - 1] if isinstance(idx, int) and 1 <= idx <= len(routes) else None
            ask = bool(res.get("ask_first"))
            phase = res.get("phase")
    if tier is None and conf == "high":
        tier = {"risky_action": "L2", "fix_request": "L1"}.get(intent)
    fix = tier == "L1" or phase == "debugging" or (route is not None and rx.is_fix_row(route))
    lines = []
    if not shadow:
        parts = []
        if route:
            parts.append("路由：%s → %s" % (route["when"], route["action"]))
        if tier:
            parts.append("級別 %s" % tier)
        if parts:
            line = "[genie route] " + "｜".join(parts)
            if tier == "L2" and not (route and "wheel" in route["action"]):
                line += "｜動手前先跑 `/wheel` 找最好解法"
            if ask:
                line += "｜有歧義且錯了要重來：先查檔確認，查不到再問使用者"
            lines.append(line + "。照此路由直接執行，不再自行重判；與鐵則衝突以鐵則為準。")
        # Every live eligible turn: turn_cmd clears the previous L1 gate even
        # when this turn opens none.
        if cfg.get("turn_cmd"):
            out = _run_ext(list(cfg["turn_cmd"]), {"prompt": text, "session_id": data.get("session_id", ""), "fix": fix}, 3)
            if out:
                lines.append(out)
    ext = {"len": len(text.strip()), "hit_kw": hit["kw"] if hit else None, "strong": bool(hit and strong),
           "esc": esc, "tier": tier, "route_when": route["when"] if route else None, "fix": fix, "shadow": shadow}
    return lines, ext


def hook(raw, host="codex"):
    """UserPromptSubmit: tag + DO + prefs, or prefs alone when the router
    abstains, or nothing at all when the turn is not the user talking.
    Fails open per part."""
    try:
        data = json.loads(raw)
    except Exception:
        # stdin on this path is always the host's hook JSON. Treating an
        # unparseable payload as the prompt classifies the envelope itself.
        return ""
    if not isinstance(data, dict):
        return ""
    text = data.get("prompt") or data.get("user_prompt") or data.get("message") or ""
    if not isinstance(text, str) or not text.strip():
        return ""
    if NOT_USER_TURN.match(text):
        return ""
    # Secret detection: if the prompt contains a high-confidence secret shape,
    # inject a one-line warning into additionalContext. This runs even when the
    # router abstains (no intent tag, no DO line).
    secret_hit = any(p.search(text) for p in SECRET_SHAPES)
    intent, score, why = classify(text)
    conf = confidence(intent, score, why)
    if os.environ.get("GENIE_DEBUG"):
        sys.stderr.write("genie: %s score=%.2f conf=%s via=%s\n" % (intent, score, conf, why))
    # Abstaining: prefs are knowledge (language, the 4 stop cases, clarity) and
    # hold every turn. The intent tag is a judgment, so it is only stated when
    # the router has one.
    abstain = intent == UNSURE
    degraded = why.startswith("fallback:")
    # A DO line is an order. Only give one when the router is sure; at
    # conf=low the tag stays as a hint and the host model judges the rest.
    # degraded keeps its DO: it says the router is broken, not a guess.
    order = not abstain and (conf == "high" or degraded)
    lines = [] if abstain else ["genie: intent=%s conf=%s" % (intent, conf)]
    if secret_hit:
        lines.append(
            "SECRET: the user just pasted what looks like a credential. "
            "Do not repeat its value, do not write it into any file or commit. "
            "In one plain sentence, suggest keeping it in an environment variable or the macOS Keychain instead."
        )

    # Long session reminder: runs even when router abstains
    long_session_reminder = _check_long_session(data)
    if long_session_reminder:
        lines.append(long_session_reminder)

    ext_log = None
    if rx is not None:
        try:
            ext_lines, ext_log = route_ext(data, text, host, intent, conf)
            lines.extend(ext_lines)
        except Exception as e:  # extension broken: plain genie output
            sys.stderr.write("genie-router: route_ext failed (%s)\n" % e)

    try:
        sys.path.insert(0, HERE)
        import prefs
        res = prefs.resolve(text)
        if order:
            lines.append(dispatch("degraded" if degraded else intent, res, host))
        # Claude gets the static prefs once from SessionStart; Codex has no such hook.
        ctx = prefs.render_context(res, host, "turn" if host == "claude" else "all")
        if ctx:
            lines.append(ctx)
    except Exception as e:  # prefs broken: still route
        sys.stderr.write("genie-router: prefs unavailable (%s)\n" % e)
        if order:
            lines.append(dispatch("degraded" if degraded else intent, {}, host))

    log_route(text, intent, score, why, conf, ext_log)
    return "\n".join(lines)


def main():
    argv = sys.argv[1:]
    host = "codex"
    if argv[:1] == ["--host"] and len(argv) > 1:
        host, argv = argv[1], argv[2:]
    if not argv:
        ctx = hook(sys.stdin.read(), host)
        if ctx:
            json.dump({"hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": ctx,
            }}, sys.stdout)
        return
    text = sys.stdin.read() if argv[0] == "--text" else " ".join(argv)
    intent, score, why = classify(text)
    conf = confidence(intent, score, why)
    if os.environ.get("GENIE_DEBUG"):
        sys.stderr.write("genie: %s score=%.2f conf=%s via=%s\n" % (intent, score, conf, why))
    print("genie: intent=%s conf=%s" % (intent, conf))


if __name__ == "__main__":
    main()
