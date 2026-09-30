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

Never fails loudly: any error -> default intent with conf=low.
CLI: `genie_router.py "some text"`  or  `echo text | genie_router.py --text`.
"""
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.environ.get("GENIE_MODEL_DIR", os.path.join(HERE, "model"))
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


def main():
    argv = sys.argv[1:]
    if argv and argv[0] != "--text":
        text = " ".join(argv)
    elif argv:
        text = sys.stdin.read()
    else:
        raw = sys.stdin.read()
        try:
            data = json.loads(raw)
            text = data.get("prompt") or data.get("user_prompt") or data.get("message") or ""
        except Exception:
            text = raw
    intent, score, why = classify(text)
    conf = confidence(intent, score, why)
    if os.environ.get("GENIE_DEBUG"):
        sys.stderr.write("genie: %s score=%.2f conf=%s via=%s\n" % (intent, score, conf, why))
    print("genie: intent=%s conf=%s" % (intent, conf))


if __name__ == "__main__":
    main()
