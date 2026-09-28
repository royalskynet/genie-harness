#!/usr/bin/env python3
"""One-time model setup (free, CPU only, no torch, no GPU).

Downloads potion-multilingual-128M (MIT) from Hugging Face with plain HTTPS, then:
  * keeps the top-K unigram pieces by score + every single-character piece
    (K=100k -> ~111k pieces; classification agrees 10/10 with the full model)
  * quantizes their embedding rows to int8 with a per-row scale
Writes router/model/{vocab.json, emb_int8.npy, scale.npy}  (~35 MB total).
The 512 MB float32 download and the 19 MB tokenizer.json are deleted afterwards.
Runtime dep: numpy only.
"""
import json
import os
import struct
import sys
import urllib.request

import numpy as np

REPO = "minishlab/potion-multilingual-128M"
BASE = "https://huggingface.co/%s/resolve/main/" % REPO
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("GENIE_MODEL_DIR", os.path.join(HERE, "model"))
K = int(os.environ.get("GENIE_VOCAB_K", "100000"))


def fetch(name, dst):
    if os.path.exists(dst):
        return
    print("downloading", name, "...", flush=True)
    urllib.request.urlretrieve(BASE + name, dst)


def main():
    os.makedirs(OUT, exist_ok=True)
    tok_path = os.path.join(OUT, "tokenizer.json")
    st = os.path.join(OUT, "model.safetensors")
    fetch("tokenizer.json", tok_path)
    fetch("model.safetensors", st)

    tj = json.load(open(tok_path, encoding="utf-8"))
    assert tj["model"]["type"] == "Unigram", tj["model"]["type"]
    vocab = tj["model"]["vocab"]  # [[piece, score], ...]
    by_score = sorted(range(len(vocab)), key=lambda i: -vocab[i][1])
    single = [i for i, (p, _) in enumerate(vocab) if len(p.replace("▁", "")) <= 1]
    keep = sorted(set(by_score[:K]) | set(single))

    with open(st, "rb") as fh:
        n = struct.unpack("<Q", fh.read(8))[0]
        hdr = json.loads(fh.read(n))
    meta = hdr["embeddings"]
    assert meta["dtype"] == "F32", meta
    emb = np.memmap(st, dtype=np.float32, mode="r", offset=8 + n + meta["data_offsets"][0], shape=tuple(meta["shape"]))
    sub = np.asarray(emb[keep])
    scale = np.abs(sub).max(1) / 127.0
    scale[scale == 0] = 1.0
    q = np.round(sub / scale[:, None]).astype(np.int8)

    np.save(os.path.join(OUT, "emb_int8.npy"), q)
    np.save(os.path.join(OUT, "scale.npy"), scale.astype(np.float32))
    with open(os.path.join(OUT, "vocab.json"), "w", encoding="utf-8") as f:
        json.dump([vocab[i][0] for i in keep], f, ensure_ascii=False)
    del emb
    os.remove(st)
    os.remove(tok_path)
    print("model ready:", OUT, "pieces=%d dim=%d" % q.shape)


if __name__ == "__main__":
    sys.exit(main())
