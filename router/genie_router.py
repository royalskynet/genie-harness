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

Below-threshold emits `intent=unsure` instead of asserting the default. A
cosine classifier that guesses confidently is worse than one that abstains:
the guess silently steers the model, while `unsure` hands the decision back to
the model's own judgement (the three-tier waterfall pattern: heuristics ->
embedding -> defer).

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
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
# install.sh puts the model in the checkout; the Claude Code plugin puts it in
# ~/.genie/model, because the plugin directory is replaced on every update.
MODEL_DIR = os.environ.get("GENIE_MODEL_DIR") or next(
    (d for d in (os.path.join(HERE, "model"), os.path.expanduser("~/.genie/model"))
     if os.path.isfile(os.path.join(d, "vocab.json"))), os.path.join(HERE, "model"))
INTENTS = json.load(open(os.path.join(HERE, "intents.json"), encoding="utf-8"))
UNSURE = "unsure"


def regex_tier(text):
    low = text.lower()
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
    """regex hit = certain; embedding needs to clear high_threshold."""
    if why.startswith("regex:"):
        return "high"
    if intent == UNSURE or why.startswith(("fallback:", "empty")):
        return "low"
    return "high" if score >= INTENTS.get("high_threshold", 0.55) else "low"


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
    "clear_request": "just do it, run it, then say in one line what changed.",
    "teach_me": "use {genie-explain} ({genie-terms} for the one key term); end by checking "
                "they understood.",
    "user_confused": "use {genie-explain}: shorter, fewer terms, one analogy at their level; "
                     "stay at that level for the rest of the conversation.",
    "risky_action": "say in one plain sentence what this does and whether it can be undone, "
                    "then wait for a yes.",
    "ambiguous_request": "their goal is not clear yet. Ask ONE question as a pick-list of at "
                         "most 3 concrete readings. Once the goal is clear, run {wheel} "
                         "before proposing how.",
    "continue": "they are answering your last message (a yes or a pick). Carry on with that "
                "plan; do not ask again.",
    UNSURE: "you cannot tell what they want. Say so and ask one short question; do not guess.",
    # model missing (e.g. still downloading): the label is a placeholder, so
    # hand the judgment back instead of dispatching "just do it".
    "degraded": "the intent router could not classify this message (model unavailable). "
                "Judge it yourself: if they want something built or a tool chosen, your "
                "FIRST action MUST be {wheel}; if it is irreversible, confirm first.",
}
WHEEL_INTENTS = ("build_request", "research_needed")
# The user turned research off: same flow, no prior-art search.
DO_NO_WHEEL = {
    "build_request": "the user wants something that does a job (research is off, so no "
                     "prior-art search). Give at most 3 options (simplest -> balanced -> "
                     "freest), recommend one, and wait for their pick before building.",
    "research_needed": "answer from official docs (research is off, so no wider search); "
                       "say how current your source is.",
    "execute_request": "use {genie-execute}: do every reversible step in one go, stop only "
                       "before an irreversible one.",
    "ambiguous_request": "their goal is not clear yet. Ask ONE question as a pick-list of "
                         "at most 3 concrete readings.",
    "degraded": "the intent router could not classify this message (model unavailable). "
                "Judge it yourself; if it is irreversible, confirm first.",
}


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
    names = ("genie-execute", "genie-explain", "genie-terms")
    return "DO: " + do.format(wheel=wheel, **{n: ref % n for n in names})


def hook(raw, host="codex"):
    """UserPromptSubmit: one injection = tag + DO + prefs. Fails open per part."""
    try:
        data = json.loads(raw)
        text = data.get("prompt") or data.get("user_prompt") or data.get("message") or ""
    except Exception:
        text = raw
    if not isinstance(text, str) or not text.strip():
        return ""
    intent, score, why = classify(text)
    conf = confidence(intent, score, why)
    if os.environ.get("GENIE_DEBUG"):
        sys.stderr.write("genie: %s score=%.2f conf=%s via=%s\n" % (intent, score, conf, why))
    lines = ["genie: intent=%s conf=%s" % (intent, conf)]
    try:
        sys.path.insert(0, HERE)
        import prefs
        res = prefs.resolve(text)
        lines.append(dispatch("degraded" if why.startswith("fallback:") else intent, res, host))
        lines.append(prefs.render_context(res, host))
    except Exception as e:  # prefs broken: still route
        sys.stderr.write("genie-router: prefs unavailable (%s)\n" % e)
        lines.append(dispatch(intent, {}, host))
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
