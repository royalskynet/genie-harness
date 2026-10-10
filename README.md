# Genie Harness

> `## 繁體中文` · `## English`

---

## 繁體中文

把 [Codex CLI](https://github.com/openai/codex) 和 [Claude Code](https://claude.com/claude-code) 變成對技術小白友善的 AI coding assistant。
免費、本地、CPU-only、不加任何付費服務。

```
你打字  →  意圖路由 (0.03–0.12s, ≤63 MB RAM)  →  Codex / Claude Code  →  白話短句的回答
                 │
                 ├─ genie: intent=build_request conf=high
                 ├─ DO: 這一輪第一個動作必須是 $wheel ...   ← 直接點名這一輪要跑的 skill
                 └─ [genie prefs] level=beginner ...
```

### 為什麼要意圖路由

預設使用者是完全的小白：他不會打 `$wheel` 或斜線指令，也不知道有這些 skill。所以每則訊息先在本地用極小的靜態 embedding 模型判斷意圖（關鍵字只是快路徑），hook 用一行 `DO:` 直接告訴模型**這一輪要跑哪個 Genie skill**。模型自己調用，使用者只要講話。

最重要的派工：一旦確定他要做一個東西，模型**先跑 `wheel`** 找現成的 app、服務、內建功能、套件，之後才給最多 3 個做法選項，不用猜的。
無頭 Claude Code 實測（`claude -p --plugin-dir`）：DO 行寫成「第一個動作必須是」之後，要做東西的請求 7/7 次第一步就調用 `genie-harness:wheel`（Sonnet 5/5、Haiku 2/2）；寫得較軟（「run wheel」）時，4 次有 1 次被跳過。樣本小，不是 benchmark。

意圖標籤與 `DO:` 派工：

| Intent | 派工 |
|---|---|
| `build_request` | 想要一個能做某件事的東西 → **先跑 `$wheel`**，再給 ≤3 個選項，等他選 |
| `research_needed` | 要選方案，或答案看版本／價格 → **先跑 `$wheel`**：官方文件＋社群共識＋成熟輪子 |
| `execute_request` | 要把東西跑起來 → `$genie-execute`：可逆的做完，只停在不可逆那一步前面 |
| `clear_request` | 需求清楚的小改動 → 直接做 |
| `teach_me` | 他想學 → `$genie-explain`／`$genie-terms`，然後確認他懂了 |
| `user_confused` | 聽不懂 → `$genie-explain`：更短、一個比喻 |
| `risky_action` | 破壞性／不可逆 → 一句白話講清楚，等他說好 |
| `fix_request` | 原本能用的東西壞了／在報錯 → 先重現、讀懂錯誤訊息；原因不明就拿錯誤原文跑 `$wheel`；修原因不修症狀，修完重跑貼真的輸出；改兩次沒好就停手回報，不要試第三招 |
| `ambiguous_request` | 目標不清楚 → 問一題選擇題；目標清楚後先跑 `$wheel` |
| `continue` | 在回答你上一則（「好」「第二個」）→ 接著做，不要再問 |
| `unsure` | router 放棄判斷 → 問一句最短的問題，不要硬猜 |

### 區塊：分級詳細度，可單次關閉

六個獨立區塊，各自 `on` / `auto`（只在需要時出現）/ `off`。`auto` 是預設——**由模型判斷這輪值不值得加**，不是每輪都加。

| 區塊 | 是什麼 |
|---|---|
| `terms` | 白話小百科，一次最多一個詞 |
| `examples` | 抽象講不過去時，給一個具體比喻 |
| `steps` | 多步驟的事，先給路徑 |
| `research` | 跑 `$wheel`：自己寫之前先找現成工具／套件。每一級預設都開（專家也值得先知道別人怎麼做）；`!research off` 關閉 |
| `confirm` | 碰到不可逆的事，先講清楚再問 |
| `humanize` | 自然對話語氣、上下文連貫、不假人味、短句單義（借鏡 ASD-STE100） |

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

**第一次用：** 裝完後的第一則訊息，Genie 會用三行自我介紹，問你是哪一級。回 `!level <名稱>` 或直接用白話說都可以。

**跟其他套件撞功能：** Genie 是整個 agent 的 harness，不是專門的安全套件。另一個已裝工具也在做它的某件事時（`guard` 擋危險指令、`research` 找輪子、`style` 語氣詳略），安裝程式會列出來，下一則訊息問你一次交給誰，並附建議（`guard` 建議交給專門工具）。用 `!owner <事>=<genie|工具名>` 選。交出去的那件事 Genie 就不做；那個工具被移除，Genie 自動接回。之後才裝的工具也會被偵測、一樣問一次。

**不是區塊，任何偏好設定都關不掉：** 災難指令閘門（`router/guard_dangerous.py`）、宿主的權限層（Codex 的 sandbox 與 approval、Claude Code 的權限確認）、以及「不確定就說不確定」。關掉提醒不等於關掉保護。git 方面還會對新手常踩、要看 repo 狀態才算危險的操作發警告（只警告不擋）：丟掉還沒 commit 的改動、刪 stash、`branch -D`、把 `.env`／金鑰檔加進 git、把 repo 設成公開。只有出現這類指令才跑 `git status`，工作區乾淨就不吵。另外會擋兩件弄不回來的事：不帶 label 的 `launchctl bootout gui/<uid>`（整台機器的背景程式一起停）、把憑證的**值**印進對話（`cat .env`、`printenv`、`echo $API_KEY`、用 Read 讀 `.env`）；只看變數名的 `cut -d= -f1 .env`、`test -n "$X"` 照常放行。唯一例外是把 `guard` 交給另一個**真的裝成 PreToolUse hook** 的指令守門工具；只改設定檔做不到。

### Claude Code（plugin）

在 Claude Code 裡：

```
/plugin marketplace add royalskynet/genie-harness
/plugin install genie-harness@genie-harness
```

重開 Claude Code。plugin 會註冊六個 hook（SessionStart 載入 `AGENTS.md`、第一次時下載模型、跑自我檢查 `router/selftest.py`（正常時不出聲，閘門或 router 壞了才講一句）；UserPromptSubmit 跑意圖路由 `--host claude`，順便在使用者貼了金鑰時提醒別複述、session 超過 150 分鐘時提醒換新對話；PreToolUse 在 `Bash|Write|Edit|MultiEdit|NotebookEdit|Read` 上跑閘門；PostToolUse／PostToolUseFailure 跑 `router/fail_streak.py`，同一類指令連續失敗 2 次就叫它停下重讀錯誤；Stop 跑完成閘 `router/done_gate.py`，另在背景跑 `router/reply_audit.py` 記錄疑似假平衡的回覆，只記錄不擋），五個 skill 以 `genie-harness:<名稱>` 出現。完成閘只在 Claude Code 生效：改了 `.py`／`.js` 之類的程式檔、最後一次改完卻什麼都沒跑就停下時，它會擋一次，要你真的跑一次貼輸出（或說明為什麼跑不了）；`.md`／`.txt` 純文字改動不擋，Codex 端沒有這個 hook。需要 Python 3.9+ 和 numpy。第一次開 session 會在背景把意圖模型下載到 `~/.genie/model`（只一次，~512 MB → 35 MB，幾分鐘）；下載完成前，router 會請模型自己判斷意圖，一樣先跑 wheel。缺 numpy 時，模型會被告知要主動提議幫他裝。偏好設定存在 `~/.genie/`，跟 Codex 共用。更新：`/plugin marketplace update genie-harness` 後 `/plugin update genie-harness@genie-harness`（或在 `/plugin` 介面點更新），重開 Claude Code 才生效。模型在 plugin 目錄外，更新不會重新下載。移除：`/plugin uninstall genie-harness`。

### Codex：一鍵安裝（Quick Start）

```bash
d=~/genie-harness; if [ -d "$d/.git" ]; then git -C "$d" pull --ff-only; else git clone https://github.com/royalskynet/genie-harness "$d"; fi && bash "$d/install.sh"
```

需要：Codex CLI（hooks 已是 stable）、Python 3.9+、numpy。第一次會下載 ~512 MB 模型，處理後只留 ~35 MB（執行期 RSS 58 MB）。若 Homebrew Python 的 pip 顯示 `externally-managed-environment`，可用 `python3 -m pip install --user --break-system-packages numpy` 把 numpy 裝到使用者套件目錄。

平台：macOS 實測可用。Linux 沒有用到 macOS 專屬指令，但沒有實測。Windows 原生不支援（hook 是 sh 腳本）；WSL 視同 Linux，也沒有實測。

一鍵安裝可重複執行：`~/genie-harness` 已是 clone 時改為 pull 更新，再重跑 install.sh。已安裝、只想更新：

```bash
bash ~/genie-harness/update.sh
```

更新不會重新下載模型：`router/model/` 在 `.gitignore` 裡，pull 不動它；install.sh 看到模型已在就跳過下載。偏好設定（`~/.genie/`）也會保留。

**install.sh 會動四處（重跑時保留第一次建立的 `*.bak-genie` 備份）：**

| 動什麼 | 改法 | 如何復原 |
|---|---|---|
| `~/.agents/skills/{genie-*,wheel}` | 5 個 symlink 指回本 repo 的 `skills/`；同名舊路徑先移到 `.bak-genie` | 移除下方列出的五個 Genie symlink，再還原同名備份 |
| `~/.codex/hooks.json` | 新增或更新 `UserPromptSubmit`（router，同時注入 prefs）與 `PreToolUse`（guard）；保留其他 hooks | `mv ~/.codex/hooks.json.bak-genie ~/.codex/hooks.json` |
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

安裝完會跑三個 smoke test 才宣告完成：閘門必須擋下 `rm -rf /`、router 必須吐出 intent、router 的 prefs 段必須在對方問「什麼是 X」時強制打開 `terms`。一個靜默不作動的 hook 比沒有 hook 更糟。

### 目錄

```
AGENTS.md                  核心行為：說話規則 + 標籤表 + 區塊表
router/
  genie_router.py          唯一的 UserPromptSubmit hook：分類 → DO 行（派 skill）→ prefs。只依賴 numpy
  intents.json             各意圖的關鍵字與範例句（中英），threshold 在這裡調
  prefs.py                 區塊解析：level 預設、pin、單次覆寫
  overlap.py               找出也在做 guard／research／style 的其他已裝工具
  guard_dangerous.py       PreToolUse hook：擋災難指令，模糊的先警告
  done_gate.py             Stop hook（Claude Code 限定）：改了程式檔卻沒跑 → 擋一次
  reply_audit.py           Stop hook（背景、shadow）：句型預篩 → 鎖工具的 haiku 判假平衡 → ~/.genie/reply_audit.jsonl，不擋；GENIE_REPLY_AUDIT=0 關
  fail_streak.py           PostToolUse(Failure) hook：同類指令連敗 2 次 → 叫它停下重讀錯誤
  selftest.py              SessionStart 自我檢查：閘門、router、hook 路徑，正常時不出聲
  eval_set.json            87 句手寫 dev 語料（不是 benchmark）
  test_router.py           自檢：邊界案例 + dev 語料，per-class，safe=100%，派工
  test_prefs.py            自檢：19 項，含「關區塊不能關安全」
  test_guard.py            自檢：49 deny + 4 warn + 5 git 狀態警告、33 must-pass、寫入掃描
  test_done_gate.py        自檢：改完沒跑會擋、跑過就放、純問答與純文字放行
  test_reply_audit.py      自檢：絕不擋、無句型不送評審、評審壞掉記 unjudged 不亂猜、不遞迴
  test_repo.py             自檢：大小預算、無絕對路徑、hook 指向存在、不漂移
  setup_model.py           一次性：下載 potion-multilingual-128M → 修剪詞表 → int8
skills/
  wheel/                   動手前查 prior-art：官方文件＋社群共識＋成熟輪子 → 7 級裁決
  genie-explain/           使用者說看不懂：更短、更少術語、加比喻
  genie-execute/           可逆的一步做完，只停在不可逆那一步前面
  genie-humanizer/         對話語氣、上下文連貫、不假人味、短句單義
  genie-terms/             一次一個詞、白話、具體比喻
hooks.json                 Codex hook 範本
install.sh                 Codex 安裝器
update.sh                  git pull --ff-only 後重跑 install.sh
.claude-plugin/            Claude Code plugin 與 marketplace manifest
claude/                    Claude Code plugin 的 hooks 與 SessionStart 腳本
opencode/                  opencode plugin：genie-dedup.js（零 token 去重，見下）
```

### opencode：零 token 去重

`opencode/genie-dedup.js` 掛在 opencode 的 `experimental.chat.messages.transform`，每輪送給模型前改寫歷史，不呼叫任何模型：同一工具、同一組參數又跑了一次時，舊的那份輸出換成標記，只留最新的；失敗的工具呼叫過了 4 輪後，它那些 ≥200 字的大參數換成標記，錯誤訊息本身保留。使用者和模型的文字一律不動。設計借鏡 opencode-dynamic-context-pruning（AGPL，只借設計、不抄碼），所以兩者不要同時裝。`GENIE_DEDUP_ENABLED=0` 關閉。

```bash
ln -sfn ~/genie-harness/opencode/genie-dedup.js ~/.config/opencode/plugins/genie-dedup.js
```

### 技術選型（為什麼是這樣）

| 需求 | 選擇 | 淘汰了什麼 |
|---|---|---|
| 分類模型 | [model2vec](https://github.com/MinishLab/model2vec) 的 `potion-multilingual-128M`（MIT，靜態 embedding，中英皆可） | sentence-transformers（要 torch，數百 MB）、本地 LLM（RAM／啟動時間） |
| 執行期 | 不裝 model2vec／tokenizers，只用 numpy：詞表修剪到 11 萬 + 貪婪最長匹配 + int8 rows mmap | 完整 `tokenizers` 載 50 萬詞表要 770 MB RAM、0.4s |
| 接入 Codex | 官方 `UserPromptSubmit` + `PreToolUse` hook | 包一層 CLI wrapper（多一個指令要學） |
| 接入 Claude Code | 官方 plugin（hooks + skills 一次裝好）；規則走 SessionStart，因為 plugin 的 CLAUDE.md 不會載入 | 手動複製檔案進 `~/.claude` |
| Skill 觸發 | hook 每輪點名要跑的 skill（`DO:`） | 只靠 skill description（公開實測約五成觸發） |
| 行為規則 | AGENTS.md + Skills（Codex 官方機制） | 自寫 prompt 注入 |
| 安全 | 正則閘門當減速帶 + Codex sandbox/approval 當邊界 | 拿一個 7 分類器當邊界 |

實測（M4，Python 3.9）：關鍵字命中時 hook 0.03s／13 MB，走 embedding 0.12s／63 MB，全部自檢通過；修剪詞表版與官方完整 tokenizer 分類結果 10/10 一致。

### 實測準確度（誠實版）

`router/eval_set.json` 是 **102 句手寫語料，不是 benchmark**。標籤是人工判斷的，不是從真實 log 抽的。這個分數是本 repo 的回歸基準，不是一般化能力的證據。

| 指標 | 數值 |
|---|---|
| 嚴格準確率 | 99/102 = 97% |
| 安全準確率（正確或 abstain） | 102/102 = 100% |
| abstain | 3 |

Per-class：`ambiguous_request` 12/13、`build_request` 10/10、`clear_request` 10/11、`continue` 4/4、`execute_request` 12/12、`fix_request` 9/9、`research_needed` 10/11、`risky_action` 9/9、`teach_me` 16/16、`user_confused` 7/7。

絕對不能錯的是 `risky_action`——那裡判錯，模型就會直接做而不是先問。所以真正重要的是安全準確率那個數字。

### 調整

- 分類不準：在 `router/intents.json` 加關鍵字（零成本、優先級最高）或範例句，跑 `python3 router/test_router.py`。
- 想看分到哪一類：`GENIE_DEBUG=1 python3 router/genie_router.py "你的句子"`。
- 模型缺檔或壞掉：印 stderr 警告，`DO:` 行把意圖判斷交還給模型（一樣先跑 wheel），不派一個猜出來的標籤。
- 區塊行為：`python3 router/prefs.py` 看目前設定，`set level <l>` / `set <block> <state>` / `clear <block>` / `reset`。

### 沒做的（MVP 刻意省略）

- 對話狀態（例如記住使用者說過看不懂）：交給 AGENTS.md 的規則，不另存狀態。
- 訓練分類器：質心 + cosine 夠用；準確度不夠再上 `model2vec[train]`。
- 多語系 UI：AGENTS.md 是繁體中文，改一份即可換語言。
- 專案層級 prefs：`~/.genie/prefs.json` 目前只有使用者層級。專案覆寫是合理的未來擴充。

### 已知缺口

- `rm -rf ~/Documents` 是警告，不是擋下。無法可靠區分專案資料夾和個人資料，硬猜會擋掉真正的工作。這裡的邊界是 Codex 的 sandbox 與 approval。
- 閘門是正則減速帶，不是安全邊界。它抓明顯的災難指令，但不是全部。邊界是 Codex 的 sandbox + approval。
- Claude Code：重複工具偵測（`overlap.py`）會讀 `~/.claude/settings.json` 的 hooks、已啟用 plugin 的名稱和 `~/.claude/skills`，但不讀 plugin 內建 hooks 的內容；名稱看不出用途的 plugin 偵測不到，兩個會同時跑。
- 沒附 Codex plugin manifest（`.codex-plugin/`）；Codex 走 `install.sh` 安裝。
- `PREMORTEM.md` 列出 30 條預測失效模式與各自的預防設計。

### License

MIT — 見 [LICENSE](LICENSE)。Copyright 2026 royalskynet。

---

## English

Make [Codex CLI](https://github.com/openai/codex) and [Claude Code](https://claude.com/claude-code) beginner-friendly. Free, local, CPU-only, no paid services, no GPU.

```
You type  →  Intent router (0.03–0.12s, ≤63 MB RAM)  →  Codex / Claude Code  →  plain-language short answers
                 │
                 ├─ genie: intent=build_request conf=high
                 ├─ DO: your FIRST action this turn MUST be $wheel ...   ← the skill to run, named for the model
                 └─ [genie prefs] level=beginner ...
```

### Why an intent router

Assume the user is a complete beginner: they will never type `$wheel` or a slash command, and they do not know the skills exist. So every message is classified first, locally, by a tiny static embedding model (keywords are only a fast path), and the hook tells the model **which Genie skill to run this turn** in a `DO:` line. The model invokes it; the user just talks.

The most important dispatch: once it is clear the user wants something built, the model **runs `wheel` first** (existing apps, services, built-in features, packages) and only then offers at most 3 options for the how, instead of guessing.
In headless Claude Code runs (`claude -p --plugin-dir`), build requests invoked `genie-harness:wheel` as the first action 7/7 times (Sonnet 5/5, Haiku 2/2) once the DO line said "FIRST action ... MUST"; a softer "run wheel" was skipped 1 time in 4. Small sample, not a benchmark.

Intent labels and what the `DO:` line dispatches:

| Intent | Dispatch |
|---|---|
| `build_request` | wants something that does a job → **`$wheel` first**, then ≤3 options, wait for a pick |
| `research_needed` | choosing a tool or answer depends on version/price → **`$wheel` first**: official docs + community consensus + mature repos |
| `execute_request` | get something running → `$genie-execute`: do the reversible steps, stop before the irreversible one |
| `clear_request` | small clear change → just do it |
| `teach_me` | wants to learn → `$genie-explain` / `$genie-terms`, then check they understood |
| `user_confused` | sounds lost → `$genie-explain`: simpler words, one analogy |
| `risky_action` | destructive/irreversible → one plain sentence on what it does, wait for a yes |
| `fix_request` | something that used to work is broken → reproduce it and read the exact error; if the cause is not obvious, search the error text with `$wheel`; fix the cause, not the symptom, then rerun and paste the real output. Two failed fixes → stop and report, don't try a third variant |
| `ambiguous_request` | goal unclear → one pick-list question; `$wheel` once the goal is clear |
| `continue` | answering your last message ("ok", "the second one") → carry on, don't re-ask |
| `unsure` | router abstained → ask one short question instead of guessing |

### Blocks: graded verbosity, per-call opt-out

Six independent blocks, each `on` / `auto` (only when needed) / `off`. `auto` is the default — the model judges whether a block earns its place.

| Block | What it is |
|---|---|
| `terms` | plain-language glossary, one term max |
| `examples` | a concrete analogy when abstraction loses them |
| `steps` | numbered steps before multi-step work |
| `research` | run `$wheel`: find an existing tool/package before hand-rolling. On at every level (experts benefit from knowing prior art too); `!research off` to stop |
| `confirm` | state what is irreversible and confirm before doing it |
| `humanize` | natural conversational tone, continuity, no robotic scaffolding, short unambiguous sentences (borrowed from ASD-STE100) |

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

**First run:** the first prompt after install makes Genie introduce itself in three lines and ask which level fits you. Answer `!level <name>` or in plain words.

**Overlapping tools:** Genie is a whole-agent harness, not a security suite. When another installed tool does one of its jobs (`guard` command blocking, `research` prior-art search, `style` tone/verbosity), the installer lists it and the next prompt asks you once who owns that job, with a recommendation (for `guard`: the dedicated tool). Pick with `!owner <job>=<genie|tool>`. Genie stands down on that job while the other tool stays installed and takes it back if you uninstall it. Tools installed later are detected and asked about the same way.

**Not blocks, and no preference can turn them off:** the catastrophic-command gate (`router/guard_dangerous.py`), Codex's sandbox and approval policy, and "say when you don't know". Turning off the nagging does not turn off the protection. For git, the gate also warns (never blocks) on the beginner mistakes that depend on repo state: discarding changes that were never committed, deleting stashes, `branch -D`, staging `.env`/key files, and making a repo public. It runs `git status` only when such a command appears, and a clean tree stays silent. It also denies two things that cannot be undone: `launchctl bootout gui/<uid>` with no label (every background job on the machine stops), and printing a credential's *value* into the conversation (`cat .env`, `printenv`, `echo $API_KEY`, `Read` on `.env`); name-only checks like `cut -d= -f1 .env` and `test -n "$X"` stay allowed. The one exception is handing `guard` to another command guard that is actually installed as a PreToolUse hook; a prefs file alone cannot do it.

### Claude Code (plugin)

Inside Claude Code:

```
/plugin marketplace add royalskynet/genie-harness
/plugin install genie-harness@genie-harness
```

Restart Claude Code. The plugin registers six hooks (SessionStart loads `AGENTS.md`, fetches the model on first use and runs the self-check `router/selftest.py`, silent unless the guard or router is broken; UserPromptSubmit runs the intent router with `--host claude`, and also warns when the user pastes a key and when a session passes 150 minutes; PreToolUse runs the guard on `Bash|Write|Edit|MultiEdit|NotebookEdit|Read`; PostToolUse/PostToolUseFailure run `router/fail_streak.py`, which tells the model to stop and re-read after two failures of the same kind of command; Stop runs the done gate `router/done_gate.py`, plus `router/reply_audit.py` in the background, which logs suspected false balance and never blocks) and the five skills as `genie-harness:<name>`. The done gate is Claude Code only: if a code file (`.py`, `.js`, anything not `.md`/`.txt`) was edited and nothing was run after the last edit, it blocks once and makes you run it and show the real output, or say plainly why it cannot be run. Pure `.md`/`.txt` edits are exempt, and Codex has no such hook. Needs Python 3.9+ and numpy. The first session downloads the intent model in the background into `~/.genie/model` (one time, ~512 MB → 35 MB, a few minutes); until it lands, the router tells the model to judge intent itself, still wheel-first. If numpy is missing, the model is told to offer installing it. Prefs live in `~/.genie/`, shared with Codex. Update with `/plugin marketplace update genie-harness` then `/plugin update genie-harness@genie-harness` (or from the `/plugin` UI), then restart Claude Code; the model lives outside the plugin directory, so it is not downloaded again. Remove with `/plugin uninstall genie-harness`.

### Codex: Quick Start (one-line install)

```bash
d=~/genie-harness; if [ -d "$d/.git" ]; then git -C "$d" pull --ff-only; else git clone https://github.com/royalskynet/genie-harness "$d"; fi && bash "$d/install.sh"
```

Requirements: Codex CLI (hooks are stable), Python 3.9+, numpy. First run downloads ~512 MB of model data; after processing, ~35 MB on disk (58 MB RSS at runtime). If pip reports `externally-managed-environment` for Homebrew Python, install numpy in the user site with `python3 -m pip install --user --break-system-packages numpy`.

Platforms: tested on macOS. Linux uses no macOS-only commands but is untested. Native Windows is not supported (the hooks are sh scripts); WSL should behave like Linux, also untested.

**What install.sh touches (re-runs preserve the first `*.bak-genie` backup):**

| Touch point | Change | Restore |
|---|---|---|
| `~/.agents/skills/{genie-*,wheel}` | 5 symlinks to this repo's `skills/`; existing same-name paths are moved to `.bak-genie` | Remove the five Genie symlinks listed below; restore any matching backup |
| `~/.codex/hooks.json` | `UserPromptSubmit` (router, which also injects prefs) and `PreToolUse` (guard) entries added or refreshed; other hooks are kept | `mv ~/.codex/hooks.json.bak-genie ~/.codex/hooks.json` |
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

Updating does not download the model again: `router/model/` is gitignored, so the pull leaves it alone, and install.sh skips the download when the model is already there. Prefs (`~/.genie/`) are kept.

install.sh also runs three smoke tests before declaring done: the guard must deny `rm -rf /`, the router must emit an intent, and the router's prefs section must force `terms` on when the user asks what something is. A hook that silently does nothing is worse than no hook.

### Layout

```
AGENTS.md                  core behavior: speaking rules + tag table + block table
router/
  genie_router.py          the one UserPromptSubmit hook: classify → DO line (skill dispatch) → prefs. numpy only
  intents.json             keywords & example sentences per intent (zh/en), thresholds here
  prefs.py                 block resolution: level defaults, pins, per-call overrides
  overlap.py               finds other installed tools doing guard / research / style
  guard_dangerous.py       PreToolUse hook: deny catastrophic commands, warn on ambiguous ones
  done_gate.py             Stop hook (Claude Code only): edited code, ran nothing → block once
  reply_audit.py           Stop hook (async, shadow): hedge prefilter → tool-less haiku judge → ~/.genie/reply_audit.jsonl, never blocks; GENIE_REPLY_AUDIT=0 turns it off
  fail_streak.py           PostToolUse(Failure) hook: same kind of command fails twice → stop and re-read
  selftest.py              SessionStart self-check of guard, router and hook paths; silent when healthy
  eval_set.json            87 hand-written dev cases (NOT a benchmark)
  test_router.py           self-check: boundary cases + dev set, per-class, safe=100%, dispatch
  test_prefs.py            self-check: 19 tests incl. blocks-cannot-disable-enforcement
  test_guard.py            self-check: 49 deny + 4 warn rules + 5 git-state warns, 33 must-pass, write scan
  test_done_gate.py        self-check: unrun edits blocked, run-after passes, Q&A and docs pass
  test_reply_audit.py      self-check: never blocks, no hedge no judge, broken judge logs unjudged, no recursion
  test_repo.py             self-check: size budget, no hardcoded paths, hooks resolve, no drift
  setup_model.py           one-time: download potion-multilingual-128M → trim vocab → int8
skills/
  wheel/                   prior-art before building: official docs + community consensus + mature repos → 7-level verdict
  genie-explain/           user says "don't get it": shorter, fewer terms, add an analogy
  genie-execute/           do the reversible steps in one go, stop before the irreversible one
  genie-humanizer/         conversational tone, continuity, no fake-human decoration, one reading per sentence
  genie-terms/             one term, plain language, a concrete analogy
hooks.json                 Codex hook template
install.sh                 Codex installer
update.sh                  git pull --ff-only, then re-run install.sh
.claude-plugin/            Claude Code plugin + marketplace manifests
claude/                    Claude Code plugin hooks + SessionStart script
opencode/                  opencode plugin: genie-dedup.js (zero-token dedup, below)
```

### opencode: zero-token dedup

`opencode/genie-dedup.js` hooks opencode's `experimental.chat.messages.transform` and rewrites the history before each turn, calling no model: when the same tool runs again with the same arguments, the older output becomes a marker and only the newest is kept; 4 turns after a tool call failed, its large (≥200 chars) arguments become markers while the error itself stays. User and assistant text is never touched. The design is borrowed from opencode-dynamic-context-pruning (AGPL; design only, no code copied), so do not install both. `GENIE_DEDUP_ENABLED=0` turns it off.

```bash
ln -sfn ~/genie-harness/opencode/genie-dedup.js ~/.config/opencode/plugins/genie-dedup.js
```

### Why this stack

| Need | Choice | Rejected |
|---|---|---|
| Classification model | [model2vec](https://github.com/MinishLab/model2vec) `potion-multilingual-128M` (MIT, static embeddings, zh+en) | sentence-transformers (needs torch, hundreds of MB), local LLM (RAM / startup time) |
| Runtime | no model2vec/tokenizers, numpy only: vocab trimmed to 110k + greedy longest-match + int8 rows mmap | full `tokenizers` with 500k vocab = 770 MB RAM, 0.4s |
| Codex integration | official `UserPromptSubmit` + `PreToolUse` hooks | a CLI wrapper (one more thing to learn) |
| Claude Code integration | official plugin (hooks + skills, one install); rules via SessionStart because a plugin's CLAUDE.md is not loaded | copying files into `~/.claude` by hand |
| Skill activation | hook names the skill per turn (`DO:`) | relying on skill descriptions alone (~50% activation in public measurements) |
| Behavior rules | AGENTS.md + Skills (Codex's official mechanism) | hand-rolled prompt injection |
| Safety | regex gate as a speed bump + Codex sandbox/approval as the boundary | trusting a 7-way classifier to be the boundary |

Measured (M4, Python 3.9): hook 0.03s / 13 MB on a keyword hit, 0.12s / 63 MB on the embedding path, all self-checks pass; trimmed-vocab vs official full tokenizer classify identically 10/10.

### Measured accuracy (honest)

`router/eval_set.json` is **102 hand-written cases, not a benchmark**. The labels are hand-judged, not derived from user logs. The score is a regression baseline for this repo, not evidence of generalisation.

| Metric | Value |
|---|---|
| strict accuracy | 99/102 = 97% |
| safe accuracy (correct or abstained) | 102/102 = 100% |
| abstained | 3 |

Per-class: `ambiguous_request` 12/13, `build_request` 10/10, `clear_request` 10/11, `continue` 4/4, `execute_request` 12/12, `fix_request` 9/9, `research_needed` 10/11, `risky_action` 9/9, `teach_me` 16/16, `user_confused` 7/7.

The class that must never be wrong is `risky_action` — a wrong label there means the model proceeds instead of asking. That is why the safe-accuracy number is the one that matters.

### Tuning

- Wrong classification: add a keyword (free, highest priority) or example sentence in `router/intents.json`, then `python3 router/test_router.py`.
- See what class something lands in: `GENIE_DEBUG=1 python3 router/genie_router.py "your sentence"`.
- Model missing/corrupt: stderr warning, and the `DO:` line hands intent judgment back to the model (still wheel-first) instead of dispatching a guessed label.
- Block behaviour: `python3 router/prefs.py` to see current settings, `set level <l>` / `set <block> <state>` / `clear <block>` / `reset`.

### Deliberately not done (MVP scope)

- Conversation state (e.g. remembering the user was confused): left to AGENTS.md rules, no stored state.
- Trained classifier: centroids + cosine is enough; reach for `model2vec[train]` only if accuracy demands.
- Multi-language UI: AGENTS.md is Traditional Chinese; swap one file to change the language.
- Project-level prefs: `~/.genie/prefs.json` is user-level only. A project override is a reasonable future addition.

### Known gaps

- `rm -rf ~/Documents` is warned, not denied. There is no reliable way to tell a project checkout from personal data, and inventing a fuzzy heuristic would block real work. Codex's sandbox and approval are the boundary here.
- The guard is a regex speed bump, not a security boundary. It catches the obvious catastrophic commands; it does not catch everything. The boundary is Codex's sandbox + approval.
- Claude Code: the overlapping-tool scan (`overlap.py`) reads `~/.claude/settings.json` hooks, the names of enabled plugins, and `~/.claude/skills`, but not the contents of hooks shipped inside plugins; a plugin whose name doesn't reveal its role is not detected and both run.
- Codex plugin manifest (`.codex-plugin/`) is not shipped; Codex installs via `install.sh`.
- `PREMORTEM.md` lists 30 predicted failure modes and the countermeasure for each.

### License

MIT — see [LICENSE](LICENSE). Copyright 2026 royalskynet.
