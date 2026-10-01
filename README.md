# Genie Harness

> `## English` · `## 繁體中文`

---

## English

Make [Codex CLI](https://github.com/openai/codex) beginner-friendly. Free, local, CPU-only, no paid services, no GPU.

```
You type  →  Router (0.07s, 58 MB RAM)  →  Codex  →  plain-language short answers
                 │
                 ├─ pastes one tag: genie: intent=ambiguous_request
                 └─ pastes this turn's blocks: [genie prefs] level=beginner ...
```

### Why a Router

Codex guessing "what does the user actually want" on every turn wastes inference, and it guesses wrong a lot for beginners (over-asks or under-asks). The router classifies locally in 0.07s using a tiny static embedding model; Codex just follows the tag.

Eight intent labels:

| Intent | Meaning |
|---|---|
| `clear_request` | straightforward request, just do it |
| `execute_request` | multi-step task — do the reversible steps, stop before the irreversible one |
| `teach_me` | user wants to learn — explain, then check they understood |
| `user_confused` | user sounds lost — simpler words, fewer terms |
| `research_needed` | choosing a tool, about to hand-roll, or answer depends on version — `$wheel`: official docs + community consensus + mature repos, then a verdict |
| `risky_action` | destructive/irreversible — warn before acting |
| `ambiguous_request` | could go several ways — ask one question |
| `unsure` | router abstained — ask one short question instead of guessing |

### Blocks: graded verbosity, per-call opt-out

Six independent blocks, each `on` / `auto` (only when needed) / `off`. `auto` is the default — the model judges whether a block earns its place.

| Block | What it is |
|---|---|
| `terms` | plain-language glossary, one term max |
| `examples` | a concrete analogy when abstraction loses them |
| `steps` | numbered steps before multi-step work |
| `research` | run `$wheel`: find an existing tool/package before hand-rolling. Auto-on for the turn when you ask to build something |
| `confirm` | state what is irreversible and confirm before doing it |
| `humanize` | natural conversational tone, continuity, no robotic scaffolding |

**Per-call opt-out:** "不用百科" / "直接給我程式碼" / `!terms off` — that turn only.
**Durable:** "不要再給我百科了" / `!terms off` — persists until changed.
**CLI:** `python3 router/prefs.py` (or `genie prefs`).

**Levels** set the defaults and the analogy register (same length, different source of analogy). Switch with `!level <name>` in chat or `set level <name>`; pinned blocks survive.

| Level | Glossary | Analogies | Steps | Analogies drawn from |
|---|---|---|---|---|
| `beginner` (default) | every new term | on | on | daily life |
| `intermediate` | auto | auto | auto | tools they use (spreadsheets, folders) |
| `advanced` | off | auto | off | adjacent tech (index, queue, lockfile) |
| `expert` | off | off | off | none: mechanism, trade-off, source |

**Not blocks, and no preference can turn them off:** the catastrophic-command gate (`router/guard_dangerous.py`), Codex's sandbox and approval policy, and "say when you don't know". Turning off the nagging does not turn off the protection.

### Quick Start (one-line install)

```bash
d=~/genie-harness; if [ -d "$d/.git" ]; then git -C "$d" pull --ff-only; else git clone https://github.com/royalskynet/genie-harness "$d"; fi && bash "$d/install.sh"
```

Requirements: Codex CLI (hooks are stable), Python 3.9+, numpy. First run downloads ~512 MB of model data; after processing, ~35 MB on disk (58 MB RSS at runtime). If pip reports `externally-managed-environment` for Homebrew Python, install numpy in the user site with `python3 -m pip install --user --break-system-packages numpy`.

**What install.sh touches (re-runs preserve the first `*.bak-genie` backup):**

| Touch point | Change | Restore |
|---|---|---|
| `~/.agents/skills/{genie-*,wheel}` | 5 symlinks to this repo's `skills/`; existing same-name paths are moved to `.bak-genie` | Remove the five Genie symlinks listed below; restore any matching backup |
| `~/.codex/hooks.json` | `UserPromptSubmit` (router + prefs) and `PreToolUse` (guard) entries added or refreshed; other hooks are kept | `mv ~/.codex/hooks.json.bak-genie ~/.codex/hooks.json` |
| `~/.codex/config.toml` | the matching hook `trusted_hash` entries are added or refreshed | `mv ~/.codex/config.toml.bak-genie ~/.codex/config.toml` |
| `~/.codex/AGENTS.md` | this repo's AGENTS.md appended once, marker-guarded | `mv ~/.codex/AGENTS.md.bak-genie ~/.codex/AGENTS.md` |

An existing backup is never overwritten. If a same-name skill already has a `.bak-genie` path, installation stops before replacing any skill link; review or move that backup before retrying.

Remove the installed Genie skill links, then restore any paths the installer backed up:

```bash
for name in genie-execute genie-explain genie-humanizer genie-terms wheel; do
  link="$HOME/.agents/skills/$name"
  backup="$link.bak-genie"
  if [ -L "$link" ] && [[ "$(readlink "$link")" == */genie-harness/skills/"$name" ]]; then rm "$link"; fi
  if { [ -e "$backup" ] || [ -L "$backup" ]; } && [ ! -e "$link" ] && [ ! -L "$link" ]; then mv "$backup" "$link"; fi
done
```

On a repeated install, the installer refreshes the hook and symlinks if the repository moved, while preserving the first backups.

The one-liner is safe to re-run: if `~/genie-harness` is already a clone it pulls instead of cloning, then re-runs install.sh. Already installed and only want the update:

```bash
bash ~/genie-harness/update.sh
```

install.sh also runs three smoke tests before declaring done: the guard must deny `rm -rf /`, the router must emit an intent, and the prefs hook must force `terms` on when the user asks what something is. A hook that silently does nothing is worse than no hook.

### Layout

```
AGENTS.md                  core behavior: speaking rules + tag table + block table
router/
  genie_router.py          hook entry. regex fast path → embedding cosine. numpy only
  intents.json             keywords & example sentences for the 8 intents (zh/en), thresholds here
  prefs.py                 block resolution: level defaults, pins, per-call overrides
  prefs_hook.py            UserPromptSubmit hook: injects this turn's [genie prefs]
  guard_dangerous.py       PreToolUse hook: deny catastrophic commands, warn on ambiguous ones
  eval_set.json            74 hand-written dev cases (NOT a benchmark)
  test_router.py           self-check: boundary cases + dev set, per-class, safe=100%
  test_prefs.py            self-check: 13 tests incl. blocks-cannot-disable-enforcement
  test_guard.py            self-check: 41 deny + 4 warn rules, 33 must-pass, write scan
  test_repo.py             self-check: size budget, no hardcoded paths, hooks resolve, no drift
  setup_model.py           one-time: download potion-multilingual-128M → trim vocab → int8
skills/
  wheel/                   prior-art before building: official docs + community consensus + mature repos → 7-level verdict
  genie-explain/           user says "don't get it": shorter, fewer terms, add an analogy
  genie-execute/           do the reversible steps in one go, stop before the irreversible one
  genie-humanizer/         conversational tone, continuity, no fake-human decoration
  genie-terms/             one term, plain language, a concrete analogy
hooks.json                 hook template
install.sh
update.sh                  git pull --ff-only 後重跑 install.sh
update.sh                  git pull --ff-only, then re-run install.sh
```

### Why this stack

| Need | Choice | Rejected |
|---|---|---|
| Classification model | [model2vec](https://github.com/MinishLab/model2vec) `potion-multilingual-128M` (MIT, static embeddings, zh+en) | sentence-transformers (needs torch, hundreds of MB), local LLM (RAM / startup time) |
| Runtime | no model2vec/tokenizers, numpy only: vocab trimmed to 110k + greedy longest-match + int8 rows mmap | full `tokenizers` with 500k vocab = 770 MB RAM, 0.4s |
| Codex integration | official `UserPromptSubmit` + `PreToolUse` hooks | a CLI wrapper (one more thing to learn) |
| Behavior rules | AGENTS.md + Skills (Codex's official mechanism) | hand-rolled prompt injection |
| Safety | regex gate as a speed bump + Codex sandbox/approval as the boundary | trusting a 7-way classifier to be the boundary |

Measured (M4, Python 3.9): full hook path 0.07s, RSS 58 MB, 15/15 tests pass; trimmed-vocab vs official full tokenizer classify identically 10/10.

### Measured accuracy (honest)

`router/eval_set.json` is **74 hand-written cases, not a benchmark**. The labels are hand-judged, not derived from user logs. The score is a regression baseline for this repo, not evidence of generalisation.

| Metric | Value |
|---|---|
| strict accuracy | 72/74 = 97% |
| safe accuracy (correct or abstained) | 74/74 = 100% |
| abstained | 2 |

Per-class: `ambiguous_request` 8/8, `clear_request` 11/12, `execute_request` 11/11, `research_needed` 10/11, `risky_action` 9/9, `teach_me` 16/16, `user_confused` 7/7.

The class that must never be wrong is `risky_action` — a wrong label there means the model proceeds instead of asking. That is why the safe-accuracy number is the one that matters.

### Tuning

- Wrong classification: add a keyword (free, highest priority) or example sentence in `router/intents.json`, then `python3 router/test_router.py`.
- See what class something lands in: `GENIE_DEBUG=1 python3 router/genie_router.py "your sentence"`.
- Model missing/corrupt: router falls back to `clear_request` with a stderr warning, Codex keeps working.
- Block behaviour: `python3 router/prefs.py` to see current settings, `set level <l>` / `set <block> <state>` / `clear <block>` / `reset`.

### Deliberately not done (MVP scope)

- Conversation state (e.g. remembering the user was confused): left to AGENTS.md rules, no stored state.
- Trained classifier: centroids + cosine is enough; reach for `model2vec[train]` only if accuracy demands.
- Multi-language UI: AGENTS.md is Traditional Chinese; swap one file to change the language.
- Project-level prefs: `~/.genie/prefs.json` is user-level only. A project override is a reasonable future addition.

### Known gaps

- `rm -rf ~/Documents` is warned, not denied. There is no reliable way to tell a project checkout from personal data, and inventing a fuzzy heuristic would block real work. Codex's sandbox and approval are the boundary here.
- The guard is a regex speed bump, not a security boundary. It catches the obvious catastrophic commands; it does not catch everything. The boundary is Codex's sandbox + approval.
- `PREMORTEM.md` lists 30 predicted failure modes and the countermeasure for each.

### License

MIT — see [LICENSE](LICENSE). Copyright 2026 royalskynet.

---

## 繁體中文

把 [Codex CLI](https://github.com/openai/codex) 變成對技術小白友善的 AI coding assistant。
免費、本地、CPU-only、不加任何付費服務。

```
你打字  →  Router (0.07s, 58 MB RAM)  →  Codex  →  白話短句的回答
                 │
                 ├─ 貼一個標籤：genie: intent=ambiguous_request
                 └─ 貼這一輪的區塊：[genie prefs] level=beginner ...
```

### 為什麼要 Router

Codex 每次都自己猜「使用者到底想幹嘛」很浪費推理，而且對小白常猜錯（不是多問就是少問）。
Router 用一個極小的靜態 embedding 模型在本地 0.07 秒分好類，Codex 只要照標籤做。

八個標籤：

| Intent | 意義 |
|---|---|
| `clear_request` | 需求明確，直接做 |
| `execute_request` | 多步驟任務 — 可逆的做完，只停在不可逆那一步前面 |
| `teach_me` | 他想學 — 講解，然後確認他懂了 |
| `user_confused` | 使用者聽不懂 — 更短、更少術語 |
| `research_needed` | 要選方案、要自己寫、或答案看版本 — `$wheel`：官方文件＋社群共識＋成熟輪子，再出裁決 |
| `risky_action` | 破壞性／不可逆 — 先警告 |
| `ambiguous_request` | 可能有多種做法 — 只問一題 |
| `unsure` | router 放棄判斷 — 問一句最短的問題，不要硬猜 |

### 區塊：分級詳細度，可單次關閉

六個獨立區塊，各自 `on` / `auto`（只在需要時出現）/ `off`。`auto` 是預設——**由模型判斷這輪值不值得加**，不是每輪都加。

| 區塊 | 是什麼 |
|---|---|
| `terms` | 白話小百科，一次最多一個詞 |
| `examples` | 抽象講不過去時，給一個具體比喻 |
| `steps` | 多步驟的事，先給路徑 |
| `research` | 跑 `$wheel`：自己寫之前先找現成工具／套件。偵測到「幫我寫一個…」時這一輪自動打開 |
| `confirm` | 碰到不可逆的事，先講清楚再問 |
| `humanize` | 自然對話語氣、上下文連貫、不假人味 |

**單次關閉：**「不用百科」／「直接給我程式碼」／`!terms off` — 只影響這一輪。
**永久關閉：**「不要再給我百科了」／`!terms off` — 會記住並持續生效。
**CLI：** `python3 router/prefs.py`（或 `genie prefs`）。

**等級**決定預設值與比喻來源（長度差不多，換的是比喻從哪來）。對話中打 `!level <名稱>` 或 `set level <名稱>` 切換；單獨設過的區塊不會被蓋掉。

| 等級 | 小百科 | 比喻 | 步驟 | 比喻從哪來 |
|---|---|---|---|---|
| `beginner`（預設） | 每個新詞 | 開 | 開 | 生活 |
| `intermediate` | 自動 | 自動 | 自動 | 用過的工具（Excel、資料夾） |
| `advanced` | 關 | 自動 | 關 | 相鄰技術（索引、佇列、lockfile） |
| `expert` | 關 | 關 | 關 | 不比喻：機制、取捨、來源 |

**不是區塊，任何偏好設定都關不掉：** 災難指令閘門（`router/guard_dangerous.py`）、Codex 的 sandbox 與 approval、以及「不確定就說不確定」。關掉提醒不等於關掉保護。

### 一鍵安裝（Quick Start）

```bash
d=~/genie-harness; if [ -d "$d/.git" ]; then git -C "$d" pull --ff-only; else git clone https://github.com/royalskynet/genie-harness "$d"; fi && bash "$d/install.sh"
```

需要：Codex CLI（hooks 已是 stable）、Python 3.9+、numpy。第一次會下載 ~512 MB 模型，處理後只留 ~35 MB（執行期 RSS 58 MB）。若 Homebrew Python 的 pip 顯示 `externally-managed-environment`，可用 `python3 -m pip install --user --break-system-packages numpy` 把 numpy 裝到使用者套件目錄。

一鍵安裝可重複執行：`~/genie-harness` 已是 clone 時改為 pull 更新，再重跑 install.sh。已安裝、只想更新：

```bash
bash ~/genie-harness/update.sh
```

**install.sh 會動四處（重跑時保留第一次建立的 `*.bak-genie` 備份）：**

| 動什麼 | 改法 | 如何復原 |
|---|---|---|
| `~/.agents/skills/{genie-*,wheel}` | 5 個 symlink 指回本 repo 的 `skills/`；同名舊路徑先移到 `.bak-genie` | 移除下方列出的五個 Genie symlink，再還原同名備份 |
| `~/.codex/hooks.json` | 新增或更新 `UserPromptSubmit`（router + prefs）與 `PreToolUse`（guard）；保留其他 hooks | `mv ~/.codex/hooks.json.bak-genie ~/.codex/hooks.json` |
| `~/.codex/config.toml` | 新增或更新 hook 對應的 `trusted_hash` | `mv ~/.codex/config.toml.bak-genie ~/.codex/config.toml` |
| `~/.codex/AGENTS.md` | 尾端加上本專案的 AGENTS.md（一次，marker 防重複） | `mv ~/.codex/AGENTS.md.bak-genie ~/.codex/AGENTS.md` |

既有備份不會被覆蓋。若同名技能的 `.bak-genie` 已存在，安裝器會在替換任何技能連結前停止；請先檢查或移走該備份再重試。

移除已安裝的 Genie 技能連結，並還原安裝器備份的舊路徑：

```bash
for name in genie-execute genie-explain genie-humanizer genie-terms wheel; do
  link="$HOME/.agents/skills/$name"
  backup="$link.bak-genie"
  if [ -L "$link" ] && [[ "$(readlink "$link")" == */genie-harness/skills/"$name" ]]; then rm "$link"; fi
  if { [ -e "$backup" ] || [ -L "$backup" ]; } && [ ! -e "$link" ] && [ ! -L "$link" ]; then mv "$backup" "$link"; fi
done
```

重新執行安裝器時，若倉庫搬了位置，它會更新 hook 與技能連結，同時保留第一次的備份。

安裝完會跑三個 smoke test 才宣告完成：閘門必須擋下 `rm -rf /`、router 必須吐出 intent、prefs hook 必須在對方問「什麼是 X」時強制打開 `terms`。一個靜默不作動的 hook 比沒有 hook 更糟。

### 目錄

```
AGENTS.md                  核心行為：說話規則 + 標籤表 + 區塊表
router/
  genie_router.py          hook 入口。regex 快路徑 → embedding cosine。只依賴 numpy
  intents.json             八類的關鍵字與範例句（中英），threshold 在這裡調
  prefs.py                 區塊解析：level 預設、pin、單次覆寫
  prefs_hook.py            UserPromptSubmit hook：注入這一輪的 [genie prefs]
  guard_dangerous.py       PreToolUse hook：擋災難指令，模糊的先警告
  eval_set.json            74 句手寫 dev 語料（不是 benchmark）
  test_router.py           自檢：邊界案例 + dev 語料，per-class，safe=100%
  test_prefs.py            自檢：13 項，含「關區塊不能關安全」
  test_guard.py            自檢：41 deny + 4 warn、33 must-pass、寫入掃描
  test_repo.py             自檢：大小預算、無絕對路徑、hook 指向存在、不漂移
  setup_model.py           一次性：下載 potion-multilingual-128M → 修剪詞表 → int8
skills/
  wheel/                   動手前查 prior-art：官方文件＋社群共識＋成熟輪子 → 7 級裁決
  genie-explain/           使用者說看不懂：更短、更少術語、加比喻
  genie-execute/           可逆的一步做完，只停在不可逆那一步前面
  genie-humanizer/         對話語氣、上下文連貫、不假人味
  genie-terms/             一次一個詞、白話、具體比喻
hooks.json                 hook 範本
install.sh
```

### 技術選型（為什麼是這樣）

| 需求 | 選擇 | 淘汰了什麼 |
|---|---|---|
| 分類模型 | [model2vec](https://github.com/MinishLab/model2vec) 的 `potion-multilingual-128M`（MIT，靜態 embedding，中英皆可） | sentence-transformers（要 torch，數百 MB）、本地 LLM（RAM／啟動時間） |
| 執行期 | 不裝 model2vec／tokenizers，只用 numpy：詞表修剪到 11 萬 + 貪婪最長匹配 + int8 rows mmap | 完整 `tokenizers` 載 50 萬詞表要 770 MB RAM、0.4s |
| 接入 Codex | 官方 `UserPromptSubmit` + `PreToolUse` hook | 包一層 CLI wrapper（多一個指令要學） |
| 行為規則 | AGENTS.md + Skills（Codex 官方機制） | 自寫 prompt 注入 |
| 安全 | 正則閘門當減速帶 + Codex sandbox/approval 當邊界 | 拿一個 7 分類器當邊界 |

實測（M4，Python 3.9）：hook 整條路 0.07s、RSS 58 MB、15/15 測試通過；修剪詞表版與官方完整 tokenizer 分類結果 10/10 一致。

### 實測準確度（誠實版）

`router/eval_set.json` 是 **74 句手寫語料，不是 benchmark**。標籤是人工判斷的，不是從真實 log 抽的。這個分數是本 repo 的回歸基準，不是一般化能力的證據。

| 指標 | 數值 |
|---|---|
| 嚴格準確率 | 72/74 = 97% |
| 安全準確率（正確或 abstain） | 74/74 = 100% |
| abstain | 2 |

Per-class：`ambiguous_request` 8/8、`clear_request` 11/12、`execute_request` 11/11、`research_needed` 10/11、`risky_action` 9/9、`teach_me` 16/16、`user_confused` 7/7。

絕對不能錯的是 `risky_action`——那裡判錯，模型就會直接做而不是先問。所以真正重要的是安全準確率那個數字。

### 調整

- 分類不準：在 `router/intents.json` 加關鍵字（零成本、優先級最高）或範例句，跑 `python3 router/test_router.py`。
- 想看分到哪一類：`GENIE_DEBUG=1 python3 router/genie_router.py "你的句子"`。
- 模型缺檔或壞掉：router 退回 `clear_request` 並印 stderr 警告，Codex 照常可用。
- 區塊行為：`python3 router/prefs.py` 看目前設定，`set level <l>` / `set <block> <state>` / `clear <block>` / `reset`。

### 沒做的（MVP 刻意省略）

- 對話狀態（例如記住使用者說過看不懂）：交給 AGENTS.md 的規則，不另存狀態。
- 訓練分類器：質心 + cosine 夠用；準確度不夠再上 `model2vec[train]`。
- 多語系 UI：AGENTS.md 是繁體中文，改一份即可換語言。
- 專案層級 prefs：`~/.genie/prefs.json` 目前只有使用者層級。專案覆寫是合理的未來擴充。

### 已知缺口

- `rm -rf ~/Documents` 是警告，不是擋下。無法可靠區分專案資料夾和個人資料，硬猜會擋掉真正的工作。這裡的邊界是 Codex 的 sandbox 與 approval。
- 閘門是正則減速帶，不是安全邊界。它抓明顯的災難指令，但不是全部。邊界是 Codex 的 sandbox + approval。
- `PREMORTEM.md` 列出 30 條預測失效模式與各自的預防設計。

### License

MIT — 見 [LICENSE](LICENSE)。Copyright 2026 royalskynet。
