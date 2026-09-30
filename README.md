# Genie Harness

> `## English` · `## 繁體中文`

---

## English

Make [Codex CLI](https://github.com/openai/codex) beginner-friendly. Free, local, CPU-only, no paid services, no GPU.

```
You type  →  Tiny Semantic Router (0.07s, 58 MB RAM)  →  Codex  →  plain-language short answers
                 │
                 └─ pastes one tag: genie: intent=ambiguous_request
                    AGENTS.md reads the tag: just do it / ask one question / read official docs first / simpler words / one step at a time / warn first
```

### Why a Router

Codex guessing "what does the user actually want" on every turn wastes inference, and it guesses wrong a lot for beginners (over-asks or under-asks). The router classifies locally in 0.07s using a tiny static embedding model; Codex just follows the tag.

Six intent labels:

| Intent | Meaning |
|---|---|
| `clear_request` | straightforward request, just do it |
| `ambiguous_request` | could go several ways — ask one question |
| `research_needed` | answer requires looking things up — official docs first |
| `user_confused` | user sounds lost — simpler words, fewer terms |
| `execute_request` | multi-step task — one step at a time, verify each |
| `risky_action` | destructive/irreversible — warn before acting |

### Quick Start (one-line install)

```bash
git clone https://github.com/royalskynet/genie-harness ~/genie-harness && bash ~/genie-harness/install.sh
```

Requirements: Codex CLI (hooks are stable), Python 3.9+, numpy. First run downloads ~512 MB of model data; after processing, ~35 MB on disk (58 MB RSS at runtime). If pip reports `externally-managed-environment` for Homebrew Python, install numpy in the user site with `python3 -m pip install --user --break-system-packages numpy`.

**What install.sh touches (re-runs preserve the first `*.bak-genie` backup):**

| Touch point | Change | Restore |
|---|---|---|
| `~/.agents/skills/genie-*` | 4 symlinks to this repo's `skills/`; existing same-name paths are moved to `.bak-genie` | Remove the four Genie symlinks listed below; restore any matching backup |
| `~/.codex/hooks.json` | one `UserPromptSubmit` entry added or refreshed; other hooks are kept | `mv ~/.codex/hooks.json.bak-genie ~/.codex/hooks.json` |
| `~/.codex/config.toml` | the matching hook `trusted_hash` is added or refreshed | `mv ~/.codex/config.toml.bak-genie ~/.codex/config.toml` |
| `~/.codex/AGENTS.md` | this repo's AGENTS.md appended once, marker-guarded | `mv ~/.codex/AGENTS.md.bak-genie ~/.codex/AGENTS.md` |

An existing backup is never overwritten. If a same-name skill already has a `.bak-genie` path, installation stops before replacing any skill link; review or move that backup before retrying.

Remove the installed Genie skill links, then restore any paths the installer backed up:

```bash
for name in genie-execute genie-explain genie-humanizer genie-research; do
  link="$HOME/.agents/skills/$name"
  backup="$link.bak-genie"
  if [ -L "$link" ] && [[ "$(readlink "$link")" == */genie-harness/skills/"$name" ]]; then rm "$link"; fi
  if { [ -e "$backup" ] || [ -L "$backup" ]; } && [ ! -e "$link" ] && [ ! -L "$link" ]; then mv "$backup" "$link"; fi
done
```

On a repeated install, the installer refreshes the hook and symlinks if the repository moved, while preserving the first backups.

### Layout

```
AGENTS.md                  core behavior: speaking rules + tag table (~40 lines)
router/
  genie_router.py          hook entry. regex fast path → embedding cosine. numpy only
  intents.json             keywords & example sentences for the 6 intent (zh/en), thresholds here
  setup_model.py           one-time: download potion-multilingual-128M → trim vocab → int8
  test_router.py           self-check (python3 router/test_router.py)
skills/
  genie-research/          official → GitHub high-star active → community; at most 3 options
  genie-explain/           user says "don't get it": shorter, fewer terms, add an analogy
  genie-execute/           one step at a time, verify before the next
  genie-humanizer/         optional: remove bot-speak
hooks.json                 hook template
install.sh
```

### Why this stack

| Need | Choice | Rejected |
|---|---|---|
| Classification model | [model2vec](https://github.com/MinishLab/model2vec) `potion-multilingual-128M` (MIT, static embeddings, zh+en) | sentence-transformers (needs torch, hundreds of MB), local LLM (RAM / startup time) |
| Runtime | no model2vec/tokenizers, numpy only: vocab trimmed to 110k + greedy longest-match + int8 rows mmap | full `tokenizers` with 500k vocab = 770 MB RAM, 0.4s |
| Codex integration | official `UserPromptSubmit` hook, one stdout line becomes developer context | a CLI wrapper (one more thing to learn) |
| Behavior rules | AGENTS.md + Skills (Codex's official mechanism) | hand-rolled prompt injection |

Measured (M4, Python 3.9): full hook path 0.07s, RSS 58 MB, 15/15 tests pass; trimmed-vocab vs official full tokenizer classify identically 10/10.

### Tuning

- Wrong classification: add a keyword (free, highest priority) or example sentence in `router/intents.json`, then `python3 router/test_router.py`.
- See what class something lands in: `GENIE_DEBUG=1 python3 router/genie_router.py "your sentence"`.
- Model missing/corrupt: router falls back to `clear_request`, Codex keeps working.

### Deliberately not done (MVP scope)

- Conversation state (e.g. remembering the user was confused): left to AGENTS.md rules, no stored state.
- Trained classifier: centroids + cosine is enough; reach for `model2vec[train]` only if accuracy demands.
- Multi-language UI: AGENTS.md is Traditional Chinese; swap one file to change the language.

### License

MIT — see [LICENSE](LICENSE). Copyright 2026 royalskynet.

---

## 繁體中文

把 [Codex CLI](https://github.com/openai/codex) 變成對技術小白友善的 AI coding assistant。
免費、本地、CPU-only、不加任何付費服務。

```
你打字  →  Tiny Semantic Router (0.07s, 58 MB RAM)  →  Codex  →  白話短句的回答
                 │
                 └─ 只貼一個標籤：genie: intent=ambiguous_request
                    AGENTS.md 看標籤決定：直接做／只問一題／先查官方文件／講簡單一點／一次一步／先警告
```

### 為什麼要 Router

Codex 每次都自己猜「使用者到底想幹嘛」很浪費推理，而且對小白常猜錯（不是多問就是少問）。
Router 用一個極小的靜態 embedding 模型在本地 0.07 秒分好類，Codex 只要照標籤做。

六個標籤：

| Intent | 意義 |
|---|---|
| `clear_request` | 需求明確，直接做 |
| `ambiguous_request` | 可能有多種做法 — 只問一題 |
| `research_needed` | 答案需要查找 — 先查官方文件 |
| `user_confused` | 使用者聽不懂 — 更短、更少術語 |
| `execute_request` | 多步驟任務 — 一次一步，逐步驗證 |
| `risky_action` | 破壞性／不可逆 — 先警告 |

### 一鍵安裝（Quick Start）

```bash
git clone https://github.com/royalskynet/genie-harness ~/genie-harness && bash ~/genie-harness/install.sh
```

需要：Codex CLI（hooks 已是 stable）、Python 3.9+、numpy。第一次會下載 ~512 MB 模型，處理後只留 ~35 MB（執行期 RSS 58 MB）。若 Homebrew Python 的 pip 顯示 `externally-managed-environment`，可用 `python3 -m pip install --user --break-system-packages numpy` 把 numpy 裝到使用者套件目錄。

**install.sh 會動四處（重跑時保留第一次建立的 `*.bak-genie` 備份）：**

| 動什麼 | 改法 | 如何復原 |
|---|---|---|
| `~/.agents/skills/genie-*` | 4 個 symlink 指回本 repo 的 `skills/`；同名舊路徑先移到 `.bak-genie` | 移除下方列出的四個 Genie symlink，再還原同名備份 |
| `~/.codex/hooks.json` | 新增或更新 `UserPromptSubmit`；保留其他 hooks | `mv ~/.codex/hooks.json.bak-genie ~/.codex/hooks.json` |
| `~/.codex/config.toml` | 新增或更新 hook 對應的 `trusted_hash` | `mv ~/.codex/config.toml.bak-genie ~/.codex/config.toml` |
| `~/.codex/AGENTS.md` | 尾端加上本專案的 AGENTS.md（一次，marker 防重複） | `mv ~/.codex/AGENTS.md.bak-genie ~/.codex/AGENTS.md` |

既有備份不會被覆蓋。若同名技能的 `.bak-genie` 已存在，安裝器會在替換任何技能連結前停止；請先檢查或移走該備份再重試。

移除已安裝的 Genie 技能連結，並還原安裝器備份的舊路徑：

```bash
for name in genie-execute genie-explain genie-humanizer genie-research; do
  link="$HOME/.agents/skills/$name"
  backup="$link.bak-genie"
  if [ -L "$link" ] && [[ "$(readlink "$link")" == */genie-harness/skills/"$name" ]]; then rm "$link"; fi
  if { [ -e "$backup" ] || [ -L "$backup" ]; } && [ ! -e "$link" ] && [ ! -L "$link" ]; then mv "$backup" "$link"; fi
done
```

重新執行安裝器時，若倉庫搬了位置，它會更新 hook 與技能連結，同時保留第一次的備份。

### 目錄

```
AGENTS.md                  核心行為：說話規則 + 標籤對照表（≈40 行）
router/
  genie_router.py          hook 入口。regex 快路徑 → embedding cosine。只依賴 numpy
  intents.json             六類的關鍵字與範例句（中英），threshold 在這裡調
  setup_model.py           一次性：下載 potion-multilingual-128M → 修剪詞表 → int8
  test_router.py           自檢（python3 router/test_router.py）
skills/
  genie-research/          先官方 → GitHub 高星活躍 → 社群；最多 3 方案
  genie-explain/           使用者說看不懂：更短、更少術語、加比喻
  genie-execute/           一次一步，做完驗證才下一步
  genie-humanizer/         可選：去機器腔
hooks.json                 hook 範本
install.sh
```

### 技術選型（為什麼是這樣）

| 需求 | 選擇 | 淘汰了什麼 |
|---|---|---|
| 分類模型 | [model2vec](https://github.com/MinishLab/model2vec) 的 `potion-multilingual-128M`（MIT，靜態 embedding，中英皆可） | sentence-transformers（要 torch，數百 MB）、本地 LLM（RAM／啟動時間） |
| 執行期 | 不裝 model2vec／tokenizers，只用 numpy：詞表修剪到 11 萬 + 貪婪最長匹配 + int8 rows mmap | 完整 `tokenizers` 載 50 萬詞表要 770 MB RAM、0.4s |
| 接入 Codex | 官方 `UserPromptSubmit` hook，stdout 一行變 developer context | 包一層 CLI wrapper（多一個指令要學） |
| 行為規則 | AGENTS.md + Skills（Codex 官方機制） | 自寫 prompt 注入 |

實測（M4，Python 3.9）：hook 整條路 0.07s、RSS 58 MB、15/15 測試通過；修剪詞表版與官方完整 tokenizer 分類結果 10/10 一致。

### 調整

- 分類不準：在 `router/intents.json` 加關鍵字（零成本、優先級最高）或範例句，跑 `python3 router/test_router.py`。
- 想看分到哪一類：`GENIE_DEBUG=1 python3 router/genie_router.py "你的句子"`。
- 模型缺檔或壞掉：router 自動退回 `clear_request`，Codex 照常可用。

### 沒做的（MVP 刻意省略）

- 對話狀態（例如記住使用者說過看不懂）：交給 AGENTS.md 的規則，不另存狀態。
- 訓練分類器：質心 + cosine 夠用；準確度不夠再上 `model2vec[train]`。
- 多語系 UI：AGENTS.md 是繁體中文，改一份即可換語言。

### License

MIT — 見 [LICENSE](LICENSE)。Copyright 2026 royalskynet。
