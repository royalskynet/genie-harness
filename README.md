# Genie Harness

> [繁體中文](#繁體中文) · [English](#english)

---

## 繁體中文

讓 [Codex CLI](https://github.com/openai/codex) 和 [Claude Code](https://claude.com/claude-code) 對不寫程式的人也友善。

- **免費、本地、只用 CPU**：不接任何付費服務，不需要 GPU。
- **你只要講話**：不用學斜線指令，Genie 每一輪替模型決定該用哪個 skill。
- **講人話**：預設假設你沒碰過電腦，聽不懂就說「人話」「不懂」。
- **不亂講、不亂來**：會把東西弄沒的指令直接擋。模型沒跑就說做完、引用不存在的 commit、可以自己決定卻回頭問你、把失敗推給「模型太弱」，各擋一次要它補。

```
你打字  →  意圖路由 (0.03–0.12s, ≤63 MB RAM)  →  Codex / Claude Code  →  白話短句的回答
                 │
                 ├─ genie: intent=build_request conf=high
                 ├─ DO: 這一輪第一個動作必須是 $wheel ...   ← 直接點名這一輪要跑的 skill
                 └─ [genie prefs] level=beginner ...
```

### 安裝

在終端機貼這一行（裝過再跑一次就是更新）：

```bash
curl -fsSL https://raw.githubusercontent.com/royalskynet/genie-harness/main/get.sh | bash
```

它會看你電腦上有哪個：有 `claude` 就裝 Claude Code 版，有 `codex` 就裝 Codex 版，兩個都有就都裝。只要其中一個，在最後加 `-s claude` 或 `-s codex`。

**附加元件**（各自是獨立的 repo）：

- **wheel**（[royalskynet/wheel-it](https://github.com/royalskynet/wheel-it)）：找現成輪子，`$wheel` 和輪子閘靠它。
- **fixindex**（[royalskynet/fixindex](https://github.com/royalskynet/fixindex)）：個人修 bug 紀錄，修過的錯再遇到能用錯誤訊息找回來；裝了以後「壞了」那類訊息會先查它。要 ripgrep。
- **ponytail**（[DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail)）：讓模型寫最少的程式。

上面那一行遇到**沒裝**的附加元件會一個一個問你要不要裝，已經裝的不動。

**完整安裝**：全部裝，不問。已經裝過的有新版會先問你要不要更新，已經是最新就跳過。

```bash
curl -fsSL https://raw.githubusercontent.com/royalskynet/genie-harness/main/get.sh | bash -s -- --all
```

加 `-y` 全部回答「要」。沒有終端機可以問的時候（例如讓 AI 代你跑），一般模式不裝附加元件，完整安裝一律回答「要」。Codex 的 ponytail 只會加進市集，要在 Codex 裡打 `/plugins` 裝。

也可以在 Claude Code 裡打：`/plugin marketplace add royalskynet/genie-harness`，再打 `/plugin install genie-harness@genie-harness`。

- **需要**：Python 3.9+、numpy。
- **意圖模型**：約 512 MB，處理後留 35 MB，下載一次要幾分鐘。
  - **Claude Code**：第一次開 session 時在背景下載到 `~/.genie/model`。下載完前一樣能用，由模型自己判斷意圖。
  - **Codex**：`install.sh` 安裝時當場下載到 repo 裡的 `router/model`，下載完才裝完。
- **wheel（找輪子）**：在另一個 repo，`get.sh` 會問你要不要裝到 `~/dev/wheel`（見上面附加元件）。手動裝 Codex 版時沒有它，安裝器印 `skipping wheel` 照樣裝完，只是少了找輪子。
- **平台**：macOS 實測可用。Linux、WSL 沒有實測。Windows 原生不支援（hook 是 sh 腳本）。
- **numpy 裝不上**：Homebrew Python 出現 `externally-managed-environment` 時，跑 `python3 -m pip install --user --break-system-packages numpy`。

### 更新

**最簡單**：直接跟 Codex 或 Claude Code 說「幫我更新 Genie」或「更新精靈到最新」，它會自己跑。

自己跑也一樣，**再貼一次安裝那一行**。

- **Claude Code**：不走原生的 `claude plugin update`。原生更新會刪掉舊版，開著的 session 的 hook 會找不到檔、擋下每個工具。`router/safe_update.py` 先備份，所有 scope（user 和各專案）一起升，開著的 session 繼續用舊版，等沒有 session 在用了才清掉。
- **Codex**：上游歷史在 2026-10-19 改寫過一次，舊安裝的 `git pull` 會失敗。這一行會處理：本地沒改動就對齊最新版，舊版留在 `genie-before-update-*` 分支；有改動就停下來不動。

每一版改了什麼，看 [CHANGELOG.md](CHANGELOG.md)。

更新完重開 Codex／Claude Code 才生效。模型不會重新下載，偏好設定（`~/.genie/`）會保留。

### 等級：從雞婆到專家

預設 `beginner`。對話中打 `!level <名稱>` 切換，或直接用白話說。

- **`beginner`（預設，雞婆模式）**：假設你從沒用過電腦。每個技術詞第一次出現都加括號註解，例如「終端機（打字跟電腦說話的視窗）」。整段解釋 3–5 句，比喻取自生活。
- **`intermediate`**：比喻取自你用過的工具（Excel、資料夾、瀏覽器分頁），真名講一次。
- **`advanced`**：比喻取自相鄰技術（索引、佇列、lockfile），術語直接用。
- **`expert`**：不比喻。直接講機制、取捨、附來源。

每一級都一樣的規則：

- **比喻最多 3 句**。比喻太長，你要多懂一件事。
- **講人話（humanize）每一級都開**：短句、一句一件事、先講結論。`!humanize off` 才關。
- **聽不懂就說「人話」「不懂」「看不懂」**：Genie 只重講卡住的那一點，詞全部註解，最後問你哪裡還不清楚。

### 它每一輪會做什麼

Genie 先在本地判斷你這句話是什麼意圖，再用一行 `DO:` 告訴模型該做什麼：

| 你的處境 | 模型會做 |
|---|---|
| 想要一個能做事的東西（`build_request`） | **先跑 `$wheel` 找現成的**，再給 1–3 個選項等你選 |
| 要選方案、答案看版本或價格（`research_needed`） | **先跑 `$wheel`**：官方文件＋社群共識＋成熟輪子 |
| 要把東西跑起來（`execute_request`） | 可逆的一口氣做完，只停在不可逆那步前面 |
| 需求清楚的小改動（`clear_request`） | 直接做 |
| 想學（`teach_me`） | 白話解釋，最後確認你懂了 |
| 聽不懂（`user_confused`） | 只重講卡住的點，詞全部註解 |
| 要做弄不回來的事（`risky_action`） | 一句白話講後果，等你說好 |
| 東西壞了（`fix_request`） | 先重現、讀錯誤訊息，修原因不修症狀，修完重跑貼真的輸出 |
| 目標還不清楚（`ambiguous_request`） | 問一題選擇題 |
| 在回你上一則（`continue`） | 接著做，不再問 |
| 要更新 Genie 本身（`update_genie`） | 自己跑這台機器的更新指令，跑完提醒重開 |
| 判斷不出來（`unsure`） | 不硬猜，模型自己讀訊息決定 |

為什麼要路由：你不會打 `$wheel`，也不知道有這些 skill。只靠 skill 說明讓模型自己想起來，公開實測約五成會觸發。無頭 Claude Code 實測，DO 行寫成「第一個動作必須是」之後，要做東西的請求 7/7 次先跑 wheel（樣本小，不是 benchmark）。

### 區塊：可以只關一輪

六個區塊，各自 `on`／`auto`（需要才出現，預設）／`off`：

- **`terms`**：白話小百科，一次最多一個詞。
- **`examples`**：抽象講不過去時給一個具體比喻。
- **`steps`**：多步驟的事先給路徑。
- **`research`**：動手前先跑 `$wheel` 找現成的。每一級都開。
- **`confirm`**：碰到不可逆的事先講清楚再問。
- **`humanize`**：講人話（借鏡 ASD-STE100 的短句單義）。每一級都開。

怎麼關：

- **只關這一輪**：說「不用百科」「直接給我程式碼」或 `!terms off`。
- **永久關**：說「不要再給我百科了」，會記住。你問「什麼是 X」時那一輪仍然會解釋。
- **看全部設定**：`python3 router/prefs.py`（或 `genie prefs`）。

### 安全閘：關不掉的部分

這些不是區塊，任何偏好都關不掉：

- **災難指令閘**（`guard_dangerous.py`）：擋 `rm -rf /`、不帶 label 的 `launchctl bootout`、把憑證的值印進對話（`cat .env`、`printenv`、`echo $API_KEY`）。只看變數名的 `cut -d= -f1 .env` 照常放行。
- **git 新手警告**（只警告不擋）：丟掉沒 commit 的改動、刪 stash、`branch -D`、把 `.env` 加進 git、把 repo 設公開。工作區乾淨就不出聲。
- **輪子閘**（`wheel_gate.py`）：判定要找現成方案的那一輪，第一個新檔和 ExitPlanMode（計畫定案）擋到跑過 wheel 為止。改既有檔、寫 `.md` 不擋；同一 session 擋第二次就放行，卡不住你。跟著 `research` 區塊走。
- **完成閘**（`done_gate.py`，只有 Claude Code）：改了程式檔卻什麼都沒跑，擋一次要你跑給它看。`ls`／`cat`／`git status` 這類只看一眼的指令不算跑過。收尾那句引用的 commit hash 或 GitHub issue／PR 網址，若這個 session 的工具輸出和你的訊息裡都沒出現過，也擋一次：這種 ID 只能照抄、不能推算，沒出現過就是編的。數字不查（加總、百分比本來就是算出來的）。Codex 沒有對等的 Stop 事件，所以沒接。
- **決定閘**（`decide_gate.py`，只有 Claude Code）：可逆的問題，模型自己已經標了唯一一個「(Recommended)」，就不准問你，直接照它做，回報時講一句採用了哪個預設、怎麼改。不可逆的問題一定問，但必須剛好標一個建議選項並寫理由，空白選擇題擋回去重問。不呼叫模型。擋下時訊息開頭是 `Genie decide_gate:`，並記一行到 `~/.genie/decide.log`（`GENIE_DECIDE_LOG=0` 關），跟別的閘疊跑時分得出是誰擋的。
- **連敗閘**（`fail_streak.py`）：同一個指令或同一個檔連續失敗 2 次，叫模型停下重讀錯誤，先列 3 個能被證明是錯的替代原因（設定過期、權限、路由走錯、依賴沒在跑）各跑一個最小檢查，排除前不准只靠換模型、加 timeout、重送或重啟，不試第三招。
- **歸因閘**（`blame_gate.py`，只有 Claude Code）：收尾那句把失敗推給「模型太弱」或「timeout」、卻沒列任何替代原因，擋一次要它補。已經寫了排除過什麼就放行。不呼叫模型。
- **宿主權限層**：Codex 的 sandbox／approval、Claude Code 的權限確認。

唯一例外：把 `guard` 交給另一個**真的裝成 PreToolUse hook** 的守門工具。只改設定檔做不到。

### 跟其他套件撞功能

- 另一個工具也在擋指令、找輪子、管語氣時，Genie 只問你一次交給誰，附建議。
- 用 `!owner <事>=<genie|工具名>` 選。交出去的事 Genie 就不做；那個工具移除了，Genie 自動接回。
- 能疊著跑不打架的（路由、完成證據），Genie 只講一句，不叫你關任何一邊。

### 調整

- **分類不準**：在 `router/intents.json` 加關鍵字（零成本、最優先）或範例句，跑 `python3 router/test_router.py`。
- **看某句分到哪類**：`GENIE_DEBUG=1 python3 router/genie_router.py "你的句子"`。
- **改設定**：`python3 router/prefs.py` 後用 `set level <l>`、`set <block> <state>`、`clear <block>`、`reset`。

### 實測準確度（誠實版）

`router/eval_set.json` 是 **102 句手寫 dev 語料，不是 benchmark**。標籤是人工判的，分數只當本 repo 的回歸基準。

- **嚴格準確率**：99/102 = 97%
- **安全準確率**（答對或放棄判斷）：102/102 = 100%
- **per-class**：`ambiguous_request` 12/13、`build_request` 10/10、`clear_request` 10/11、`continue` 4/4、`execute_request` 12/12、`fix_request` 9/9、`research_needed` 10/11、`risky_action` 9/9、`teach_me` 16/16、`user_confused` 7/7

最重要的是 `risky_action` 不能錯：判錯，模型就會直接做而不是先問。

### 技術細節

<details>
<summary>Claude Code plugin 註冊的 hook</summary>

- **SessionStart**：載入 `AGENTS.md`、第一次下載模型、跑自我檢查 `router/selftest.py`（正常時不出聲）。
- **UserPromptSubmit**：意圖路由 `--host claude`；你貼了金鑰時提醒別複述；session 超過 150 分鐘時提醒換新對話。
- **PreToolUse**：`Bash|Write|Edit|MultiEdit|NotebookEdit|Read` 跑災難指令閘；`Write|ExitPlanMode|Skill|SlashCommand|Bash` 跑輪子閘。
- **PostToolUse／PostToolUseFailure**：`Bash|Edit|Write|MultiEdit|NotebookEdit` 跑連敗閘。
- **Stop**：完成閘。

四個 skill 以 `genie-harness:<名稱>` 出現；`wheel` 在本 repo 外（`royalskynet/wheel-it`）。移除：`/plugin uninstall genie-harness`。

</details>

<details>
<summary>Codex install.sh 會動的四處</summary>

重跑時保留第一次的 `*.bak-genie` 備份，既有備份不會被覆蓋。

- **`~/.agents/skills/{genie-*,wheel}`**：4 個 symlink 指回本 repo 的 `skills/`；`wheel` 指到 `~/dev/wheel`（`royalskynet/wheel-it` 的 clone，`GENIE_WHEEL_UPSTREAM` 可改）。全新安裝時那個 clone 不存在，安裝器印 `skipping wheel` 後繼續；只有原本已有 `wheel` 連結、clone 卻不見時才以「refusing」停下，避免把能用的連結指到空處。
- **`~/.codex/hooks.json`**：新增或更新 `UserPromptSubmit`（router）與 `PreToolUse`（guard），其他 hook 保留。復原：`mv ~/.codex/hooks.json.bak-genie ~/.codex/hooks.json`。
- **`~/.codex/config.toml`**：新增或更新 hook 的 `trusted_hash`。復原：`mv ~/.codex/config.toml.bak-genie ~/.codex/config.toml`。
- **`~/.codex/AGENTS.md`**：只管 `<!-- genie-harness -->` 標記內的區塊，每次安裝或更新都換成最新版；標記外你自己寫的內容不動。復原：`mv ~/.codex/AGENTS.md.bak-genie ~/.codex/AGENTS.md`。

安裝完跑三個 smoke test 才宣告完成：閘門要擋下 `rm -rf /`、router 要吐出 intent、問「什麼是 X」時要強制打開 `terms`。

移除技能連結並還原備份：

```bash
for name in genie-execute genie-explain genie-humanizer genie-terms wheel; do
  link="$HOME/.agents/skills/$name"
  backup="$link.bak-genie"
  if [ -L "$link" ] && [[ "$(readlink "$link")" == */genie-harness/skills/"$name" || "$name" == wheel ]]; then rm "$link"; fi
  if { [ -e "$backup" ] || [ -L "$backup" ]; } && [ ! -e "$link" ] && [ ! -L "$link" ]; then mv "$backup" "$link"; fi
done
```

</details>

<details>
<summary>opencode：零 token 去重</summary>

`opencode/genie-dedup.js` 掛在 `experimental.chat.messages.transform`，送給模型前改寫歷史，不呼叫任何模型：

- 同一工具同一組參數又跑一次，舊的輸出換成標記。
- 失敗的工具呼叫過 4 輪後，≥200 字的大參數換成標記，錯誤訊息保留。
- 使用者和模型的文字一律不動。

設計借鏡 opencode-dynamic-context-pruning（AGPL，只借設計不抄碼），兩者不要同時裝。`GENIE_DEDUP_ENABLED=0` 關閉。

```bash
ln -sfn ~/genie-harness/opencode/genie-dedup.js ~/.config/opencode/plugins/genie-dedup.js
```

</details>

<details>
<summary>技術選型</summary>

- **分類模型**：[model2vec](https://github.com/MinishLab/model2vec) `potion-multilingual-128M`（MIT，靜態 embedding，中英皆可）。淘汰 sentence-transformers（要 torch）、本地 LLM（RAM／啟動時間）。
- **執行期**：只用 numpy。詞表修剪到 11 萬＋貪婪最長匹配＋int8 mmap。完整 `tokenizers` 要 770 MB RAM、0.4s。
- **接入**：Codex 用官方 hook；Claude Code 用官方 plugin，規則走 SessionStart（plugin 的 CLAUDE.md 不會載入）。
- **Skill 觸發**：hook 每輪點名（`DO:`），不只靠 skill 說明。
- **安全**：正則閘當減速帶，宿主 sandbox／approval 當邊界。

實測（M4，Python 3.9）：關鍵字命中 0.03s／13 MB，走 embedding 0.12s／63 MB；修剪詞表與官方完整 tokenizer 分類 10/10 一致。

</details>

<details>
<summary>目錄</summary>

```
AGENTS.md                  核心行為：等級、區塊、標籤、說話規則
router/
  genie_router.py          UserPromptSubmit hook：分類 → DO 行 → prefs。只依賴 numpy
  intents.json             各意圖的關鍵字與範例句（中英），threshold 在這裡
  prefs.py                 區塊解析：等級預設、pin、單次覆寫
  overlap.py               找出也在做 guard／research／style 的其他工具
  guard_dangerous.py       PreToolUse：擋災難指令，模糊的先警告
  wheel_gate.py            PreToolUse：要找輪子的那一輪，新檔與 ExitPlanMode 擋到跑過 wheel
  done_gate.py             Stop（Claude Code 限定）：改了程式檔卻沒跑，或引用沒出現過的 commit／issue → 擋一次
  decide_gate.py           PreToolUse(AskUserQuestion)：可逆且已有建議 → 照做不問；不可逆缺建議或理由 → 重問
  fail_streak.py           PostToolUse(Failure)：同指令或同檔連敗 2 次 → 停下重讀、先排除替代原因
  blame_gate.py            Stop（Claude Code 限定）：怪模型或 timeout 卻沒列替代原因 → 擋一次
  safe_update.py           Claude Code 更新：所有 scope 一起升，舊版留給開著的 session
  selftest.py              SessionStart 自我檢查，正常時不出聲
  eval_set.json            102 句手寫 dev 語料（不是 benchmark）
  test_*.py                14 支自檢，全部要 PASS
  setup_model.py           一次性：下載模型 → 修剪詞表 → int8
skills/
  genie-explain/           聽不懂：只重講卡住的點，詞全部註解，比喻 ≤3 句
  genie-execute/           可逆的一口氣做完，停在不可逆那步前面
  genie-humanizer/         講人話：短句單義、先講結論
  genie-terms/             一次一個詞的白話百科；beginner 的雞婆註解
get.sh                                 一行安裝／更新（偵測 claude、codex）
hooks.json / install.sh / update.sh    Codex 用
.claude-plugin/ / claude/              Claude Code plugin
opencode/                              genie-dedup.js
```

</details>

### 已知缺口

- **`rm -rf ~/Documents` 只警告不擋**：分不出專案資料夾和個人資料，硬猜會擋到正常工作。邊界交給宿主的 sandbox／approval。
- **閘門是減速帶不是邊界**：正則抓明顯的災難指令，抓不到全部。
- **重複工具偵測有盲點**：不讀 plugin 內建 hook 的內容，名稱看不出用途的 plugin 偵測不到。
- **沒附 Codex plugin manifest**：Codex 走 `install.sh`。
- **刻意沒做**：對話狀態、訓練分類器、多語系 UI、專案層級 prefs。
- 完整失效模式清單見 [`PREMORTEM.md`](PREMORTEM.md)。

### License

MIT — 見 [LICENSE](LICENSE)。Copyright 2026 royalskynet。

---

## English

Make [Codex CLI](https://github.com/openai/codex) and [Claude Code](https://claude.com/claude-code) usable by people who don't write code.

- **Free, local, CPU-only**: no paid services, no GPU.
- **You just talk**: no slash commands to learn; Genie tells the model which skill to run each turn.
- **Plain language**: by default it assumes you have never used a computer. Lost? Say "plain words" or "I don't get it".
- **No bluffing, no wrecking**: commands that destroy things are blocked. Claiming done without running anything, citing a commit that doesn't exist, asking you what it could decide itself, or blaming "the model is too weak" each get blocked once until fixed.

```
You type  →  Intent router (0.03–0.12s, ≤63 MB RAM)  →  Codex / Claude Code  →  plain-language short answers
                 │
                 ├─ genie: intent=build_request conf=high
                 ├─ DO: your FIRST action this turn MUST be $wheel ...   ← the skill to run, named for the model
                 └─ [genie prefs] level=beginner ...
```

### Install

Paste this one line in a terminal (run it again later to update):

```bash
curl -fsSL https://raw.githubusercontent.com/royalskynet/genie-harness/main/get.sh | bash
```

It looks at what you have: `claude` gets the Claude Code plugin, `codex` gets the Codex install, both get both. For only one, add `-s claude` or `-s codex` at the end.

**Add-ons** (separate repos):

- **wheel** ([royalskynet/wheel-it](https://github.com/royalskynet/wheel-it)): prior-art search behind `$wheel` and the wheel gate.
- **fixindex** ([royalskynet/fixindex](https://github.com/royalskynet/fixindex)): a personal fix log, so a bug fixed once is found again by its error text; with it, "it's broken" turns check it first. Needs ripgrep.
- **ponytail** ([DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail)): keeps the code the model writes minimal.

The line above asks, one by one, about each add-on that is **missing**; installed ones are left alone.

**Full install**: installs everything without asking. For what is already installed it asks before updating, and skips what is already latest.

```bash
curl -fsSL https://raw.githubusercontent.com/royalskynet/genie-harness/main/get.sh | bash -s -- --all
```

Add `-y` to answer yes to everything. With no terminal to ask (an AI running it for you), the default line installs no add-on and the full install answers yes. On Codex, ponytail is only added to the marketplace; install it from `/plugins` in Codex.

Or inside Claude Code: `/plugin marketplace add royalskynet/genie-harness`, then `/plugin install genie-harness@genie-harness`.

- **Needs**: Python 3.9+, numpy.
- **Intent model**: ~512 MB, 35 MB after processing, a few minutes to download once.
  - **Claude Code**: downloaded in the background to `~/.genie/model` on the first session. Until then it still works; the model judges intent itself.
  - **Codex**: `install.sh` downloads it on the spot into the repo's `router/model`; install finishes after the download.
- **wheel (prior-art search)**: lives in a separate repo; `get.sh` offers to install it to `~/dev/wheel` (see add-ons above). A manual Codex install without it prints `skipping wheel` and finishes, minus prior-art search.
- **Platforms**: tested on macOS. Linux and WSL untested. Native Windows unsupported (hooks are sh scripts).
- **numpy won't install**: on Homebrew Python with `externally-managed-environment`, run `python3 -m pip install --user --break-system-packages numpy`.

### Update

**Easiest**: tell Codex or Claude Code "update Genie" (or "upgrade genie to latest"). It runs the update itself.

By hand, **paste the install line again**.

- **Claude Code**: it skips the native `claude plugin update`, which deletes the old version so hooks in sessions still open lose their files and block every tool. `router/safe_update.py` backs it up, updates every scope (user and each project) together, lets open sessions keep the old version, and removes it once no session started before the update is left.
- **Codex**: upstream history was rewritten once (2026-10-19), so `git pull` fails on old installs. The line handles it: with no local edits it moves to the latest version and keeps the old one on a `genie-before-update-*` branch; with local edits it stops and changes nothing.

What changed in each version: [CHANGELOG.md](CHANGELOG.md).

Restart Codex / Claude Code afterwards. The model is not downloaded again; prefs (`~/.genie/`) are kept.

### Levels: from hand-holding to expert

Default is `beginner`. Switch with `!level <name>` in chat, or just say it.

- **`beginner` (default, hand-holding mode)**: assumes you have never used a computer. Every technical word gets a short gloss in brackets the first time, e.g. "terminal (the window where you type to the computer)". Explanations stay at 3–5 sentences; analogies come from daily life.
- **`intermediate`**: analogies from tools you use (spreadsheets, folders, browser tabs); the real term is named once.
- **`advanced`**: analogies from adjacent tech (an index, a queue, a lockfile); real terms freely.
- **`expert`**: no analogies. The mechanism, the trade-off, a source.

Same at every level:

- **An analogy is at most 3 sentences.** A long analogy is one more thing to understand.
- **Plain language (`humanize`) is on at every level**: short sentences, one point each, answer first. `!humanize off` to stop.
- **Say "plain words", "I don't get it", "人話", "不懂"**: Genie re-explains only the point you are stuck on, glosses every term, and asks what is still unclear.

### What it does each turn

Genie classifies your message locally, then tells the model what to do in one `DO:` line:

| Your situation | The model will |
|---|---|
| Want something that does a job (`build_request`) | **Run `$wheel` first** for existing tools, then offer 1–3 options and wait |
| Choosing a tool, or the answer depends on version/price (`research_needed`) | **Run `$wheel` first**: official docs + community consensus + mature repos |
| Get something running (`execute_request`) | Do the reversible steps in one go, stop before the irreversible one |
| Small clear change (`clear_request`) | Just do it |
| Want to learn (`teach_me`) | Explain plainly, then check you understood |
| Lost (`user_confused`) | Re-explain only the stuck point, every term glossed |
| Something that can't be undone (`risky_action`) | One plain sentence on the consequence, wait for a yes |
| Something broke (`fix_request`) | Reproduce, read the error, fix the cause not the symptom, rerun and paste real output |
| Goal still unclear (`ambiguous_request`) | Ask one pick-list question |
| Replying to the last message (`continue`) | Carry on, don't re-ask |
| Updating Genie itself (`update_genie`) | Runs this host's update command, then reminds you to restart |
| Router can't tell (`unsure`) | No guessing; the model reads the message and decides |

Why a router: you won't type `$wheel` and don't know the skills exist. Relying on skill descriptions alone activates them about half the time in public measurements. In headless Claude Code runs, once the DO line said "FIRST action ... MUST", build requests ran wheel first 7/7 times (small sample, not a benchmark).

### Blocks: turn off for one turn

Six blocks, each `on` / `auto` (only when needed, the default) / `off`:

- **`terms`**: plain-language glossary, one term max.
- **`examples`**: one concrete analogy when abstraction loses you.
- **`steps`**: the path before multi-step work.
- **`research`**: run `$wheel` before building. On at every level.
- **`confirm`**: say what is irreversible and ask first.
- **`humanize`**: plain language (short, one-reading sentences borrowed from ASD-STE100). On at every level.

How to turn off:

- **This turn only**: "skip the glossary", "just code", or `!terms off`.
- **For good**: "stop giving me glossaries" — remembered. Asking "what is X" still gets an explanation that turn.
- **See everything**: `python3 router/prefs.py` (or `genie prefs`).

### Safety gates: the parts you can't turn off

Not blocks; no preference disables them:

- **Catastrophic-command gate** (`guard_dangerous.py`): denies `rm -rf /`, `launchctl bootout` with no label, and printing a credential's value into the chat (`cat .env`, `printenv`, `echo $API_KEY`). Name-only checks like `cut -d= -f1 .env` pass.
- **Git beginner warnings** (warn, never block): discarding uncommitted changes, deleting stashes, `branch -D`, staging `.env`, making a repo public. A clean tree stays silent.
- **Wheel gate** (`wheel_gate.py`): on a turn judged to be about building or choosing, the first new file and ExitPlanMode (a plan is a decision) wait until a prior-art search has run. Edits to existing files and `.md` pass; a second block in the same session opens it, so it can't wedge you. Follows the `research` block.
- **Done gate** (`done_gate.py`, Claude Code only): edited code and ran nothing → blocks once and asks for a real run. Look-only commands (`ls`, `cat`, `git status`) don't count. It also blocks once when the final reply cites a commit hash or a GitHub issue/PR URL that no tool output or user message this session contains: such ids can only be quoted, not derived. Numbers are not checked (sums and percentages are computed). Codex has no matching Stop event, so it is not wired there.
- **Decide gate** (`decide_gate.py`, Claude Code only): a reversible question where the model already marked exactly one option "(Recommended)" is denied, so it does that and says in one line which default it took. Irreversible questions are always asked, but must mark exactly one recommendation with a reason; a bare choice is sent back. No model call. Each deny starts with `Genie decide_gate:` and logs one line to `~/.genie/decide.log` (`GENIE_DECIDE_LOG=0` turns it off), so a stacked gate can be told apart.
- **Fail-streak gate** (`fail_streak.py`): the same command or the same file fails twice → the model stops, re-reads the error, and checks three alternative causes a test could prove wrong (stale config, permissions, wrong route, a dependency not running) before swapping models, raising timeouts, resending or restarting.
- **Blame gate** (`blame_gate.py`, Claude Code only): the final reply blames the model or a timeout and names no alternative cause → blocks once and asks for them. Replies that say what was ruled out pass. No model call.
- **Host permissions**: Codex sandbox/approval, Claude Code permission prompts.

The one exception: handing `guard` to another command guard that is actually installed as a PreToolUse hook. A prefs file alone can't do it.

### Overlapping tools

- When another tool also blocks commands, finds prior art, or sets tone, Genie asks you once who owns that job, with a recommendation.
- Pick with `!owner <job>=<genie|tool>`. Genie stands down on that job and takes it back if you uninstall the tool.
- Jobs that stack without conflict (routing, completion evidence): Genie says one line and asks you to turn nothing off.

### Tuning

- **Wrong classification**: add a keyword (free, highest priority) or example sentence in `router/intents.json`, then `python3 router/test_router.py`.
- **See where a sentence lands**: `GENIE_DEBUG=1 python3 router/genie_router.py "your sentence"`.
- **Change settings**: `python3 router/prefs.py`, then `set level <l>`, `set <block> <state>`, `clear <block>`, `reset`.

### Measured accuracy (honest)

`router/eval_set.json` is **102 hand-written dev cases, not a benchmark**. Labels are hand-judged; the score is a regression baseline for this repo only.

- **Strict accuracy**: 99/102 = 97%
- **Safe accuracy** (correct or abstained): 102/102 = 100%
- **Per-class**: `ambiguous_request` 12/13, `build_request` 10/10, `clear_request` 10/11, `continue` 4/4, `execute_request` 12/12, `fix_request` 9/9, `research_needed` 10/11, `risky_action` 9/9, `teach_me` 16/16, `user_confused` 7/7

`risky_action` is the class that must never be wrong: a wrong label there means the model proceeds instead of asking.

### Technical details

<details>
<summary>Hooks the Claude Code plugin registers</summary>

- **SessionStart**: loads `AGENTS.md`, fetches the model on first use, runs the self-check `router/selftest.py` (silent when healthy).
- **UserPromptSubmit**: intent router `--host claude`; warns when you paste a key; suggests a new session after 150 minutes.
- **PreToolUse**: catastrophic-command gate on `Bash|Write|Edit|MultiEdit|NotebookEdit|Read`; wheel gate on `Write|ExitPlanMode|Skill|SlashCommand|Bash`.
- **PostToolUse / PostToolUseFailure**: fail-streak gate on `Bash|Edit|Write|MultiEdit|NotebookEdit`.
- **Stop**: done gate.

Four skills appear as `genie-harness:<name>`; `wheel` lives outside this repo (`royalskynet/wheel-it`). Remove with `/plugin uninstall genie-harness`.

</details>

<details>
<summary>What Codex install.sh touches</summary>

Re-runs keep the first `*.bak-genie` backup; an existing backup is never overwritten.

- **`~/.agents/skills/{genie-*,wheel}`**: 4 symlinks to this repo's `skills/`; `wheel` points at `~/dev/wheel` (a clone of `royalskynet/wheel-it`, override with `GENIE_WHEEL_UPSTREAM`). On a fresh install without that clone, the installer prints `skipping wheel` and continues. It stops with "refusing" only when a `wheel` link already exists but its clone is gone, so a working link is never pointed at nothing.
- **`~/.codex/hooks.json`**: adds or refreshes `UserPromptSubmit` (router) and `PreToolUse` (guard); other hooks are kept. Restore: `mv ~/.codex/hooks.json.bak-genie ~/.codex/hooks.json`.
- **`~/.codex/config.toml`**: adds or refreshes the hooks' `trusted_hash`. Restore: `mv ~/.codex/config.toml.bak-genie ~/.codex/config.toml`.
- **`~/.codex/AGENTS.md`**: owns only the block inside the `<!-- genie-harness -->` marker and replaces it with the latest on every install or update; your text outside the marker is left alone. Restore: `mv ~/.codex/AGENTS.md.bak-genie ~/.codex/AGENTS.md`.

Three smoke tests run before install declares done: the guard must deny `rm -rf /`, the router must emit an intent, and asking "what is X" must force `terms` on.

Remove the skill links and restore backups:

```bash
for name in genie-execute genie-explain genie-humanizer genie-terms wheel; do
  link="$HOME/.agents/skills/$name"
  backup="$link.bak-genie"
  if [ -L "$link" ] && [[ "$(readlink "$link")" == */genie-harness/skills/"$name" || "$name" == wheel ]]; then rm "$link"; fi
  if { [ -e "$backup" ] || [ -L "$backup" ]; } && [ ! -e "$link" ] && [ ! -L "$link" ]; then mv "$backup" "$link"; fi
done
```

</details>

<details>
<summary>opencode: zero-token dedup</summary>

`opencode/genie-dedup.js` hooks `experimental.chat.messages.transform` and rewrites history before each turn, calling no model:

- The same tool with the same arguments runs again → the older output becomes a marker.
- 4 turns after a failed tool call, its large (≥200 chars) arguments become markers; the error stays.
- User and assistant text is never touched.

Design borrowed from opencode-dynamic-context-pruning (AGPL; design only, no code copied), so don't install both. `GENIE_DEDUP_ENABLED=0` turns it off.

```bash
ln -sfn ~/genie-harness/opencode/genie-dedup.js ~/.config/opencode/plugins/genie-dedup.js
```

</details>

<details>
<summary>Why this stack</summary>

- **Classifier**: [model2vec](https://github.com/MinishLab/model2vec) `potion-multilingual-128M` (MIT, static embeddings, zh+en). Rejected sentence-transformers (needs torch) and a local LLM (RAM / startup).
- **Runtime**: numpy only. Vocab trimmed to 110k + greedy longest-match + int8 mmap. Full `tokenizers` costs 770 MB RAM and 0.4s.
- **Integration**: official Codex hooks; official Claude Code plugin, rules via SessionStart (a plugin's CLAUDE.md is not loaded).
- **Skill activation**: the hook names the skill each turn (`DO:`), not skill descriptions alone.
- **Safety**: a regex gate as a speed bump; the host's sandbox/approval as the boundary.

Measured (M4, Python 3.9): 0.03s / 13 MB on a keyword hit, 0.12s / 63 MB on the embedding path; trimmed vocab and the official full tokenizer classify identically 10/10.

</details>

<details>
<summary>Layout</summary>

```
AGENTS.md                  core behavior: levels, blocks, tags, speaking rules
router/
  genie_router.py          UserPromptSubmit hook: classify → DO line → prefs. numpy only
  intents.json             keywords & example sentences per intent (zh/en), thresholds here
  prefs.py                 block resolution: level defaults, pins, per-call overrides
  overlap.py               finds other tools doing guard / research / style
  guard_dangerous.py       PreToolUse: deny catastrophic commands, warn on ambiguous ones
  wheel_gate.py            PreToolUse: on a prior-art turn, new files and ExitPlanMode wait for wheel
  done_gate.py             Stop (Claude Code only): edited code and ran nothing, or cited an unseen commit/issue → block once
  decide_gate.py           PreToolUse(AskUserQuestion): reversible with a recommendation → do it; irreversible without one → re-ask
  fail_streak.py           PostToolUse(Failure): same command or file fails twice → stop, re-read, rule out alternatives
  blame_gate.py            Stop (Claude Code only): blames model or timeout with no alternative cause → block once
  safe_update.py           Claude Code update: every scope at once, old version kept for open sessions
  selftest.py              SessionStart self-check, silent when healthy
  eval_set.json            102 hand-written dev cases (NOT a benchmark)
  test_*.py                14 self-checks, all must PASS
  setup_model.py           one-time: download model → trim vocab → int8
skills/
  genie-explain/           lost: re-explain only the stuck point, every term glossed, analogy ≤3 sentences
  genie-execute/           do the reversible steps in one go, stop before the irreversible one
  genie-humanizer/         plain language: one reading per sentence, answer first
  genie-terms/             one-term plain glossary; beginner's gloss-everything mode
get.sh                                 one-line install/update (detects claude, codex)
hooks.json / install.sh / update.sh    Codex
.claude-plugin/ / claude/              Claude Code plugin
opencode/                              genie-dedup.js
```

</details>

### Known gaps

- **`rm -rf ~/Documents` is warned, not denied**: there is no reliable way to tell a project checkout from personal data; guessing would block real work. The host's sandbox/approval is the boundary.
- **The guard is a speed bump, not a boundary**: it catches the obvious catastrophic commands, not all of them.
- **Overlap detection has a blind spot**: it doesn't read hooks shipped inside plugins; a plugin whose name hides its role is not detected.
- **No Codex plugin manifest**: Codex installs via `install.sh`.
- **Deliberately not done**: conversation state, a trained classifier, multi-language UI, project-level prefs.
- Full failure-mode list: [`PREMORTEM.md`](PREMORTEM.md).

### License

MIT — see [LICENSE](LICENSE). Copyright 2026 royalskynet.
