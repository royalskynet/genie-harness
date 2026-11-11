# Changelog

每一版改了什麼。最新的在最上面。 · What changed in each version, newest first.

## 0.5.9 — 2026-11-11

- 常駐載入瘦身：prefs 砍掉和 AGENTS.md 重複的三句（停手規則、research 提示、「使用者不會打指令」），開場那份從 1562 降到 1166 bytes；Claude Code 上單則訊息只動一個開關時不再重送整段常駐規則；定期重送從每 12 則改成每 24 則（`GENIE_PREFS_REFRESH=<N>` 照舊可調）。停手規則現在只在 AGENTS.md，原句獨有的兩個子句（猜錯要整個重來也先問、問題一次問完）一併搬過去。 · Slimmer standing context: prefs drops three lines AGENTS.md already says (the stop rule, the research hint, "they cannot type commands"), 1562 -> 1166 bytes at session start; on Claude Code a message that flips one block no longer re-sends the whole always-on line; the periodic refresh goes from every 12th to every 24th prompt (`GENIE_PREFS_REFRESH=<N>` still tunes it). The stop rule now lives only in AGENTS.md, with its two extra clauses moved there (#52, #53).
- AGENTS.md：描述模糊時，動手前模型先自問三件事（專業詞、理論或研究、別的領域怎麼解），答案留在上下文當依據，不拿去問使用者。 · AGENTS.md: on a vague ask the model first asks itself three things (the term of art, the supporting theory or research, how other fields solve it) and keeps the answers in context; it does not ask the user (#51).
- 輪子閘：Codex 也註冊；抓 `apply_patch` 新增檔與 heredoc 寫檔；整個 session 沒查過現成做法時擋第一個新檔（`GENIE_WHEEL_FIRST=0` 關閉）；heredoc 內文不再誤判成寫檔；research 交給 `wheel` 時認得是 Genie 的 wheel。 · Wheel gate: registered for Codex too; catches `apply_patch` new files and heredoc writes; blocks the first new file in a session that never looked up prior art (`GENIE_WHEEL_FIRST=0` = off); heredoc bodies are no longer read as writes; research handed to `wheel` is recognised as Genie's wheel (#45, #46).
- 工單內的高風險動作：訊息本身已下令的照做，只在它沒講到的地方停；單行指令照舊等一聲好。 · A risky action inside a work order is carried out as ordered, stopping only on what the order does not cover; one-line risky orders still wait for a yes (#45).
- overlap：`/wheel` 指令殼取代已連結的 wheel skill 時提醒。 · overlap flags a `/wheel` command shim standing in for the linked wheel skill (#47).
- 災難指令閘：引號內的 `#` 不當註解，引號內的 `|;&<>` 當文字。 · Guard: `#` inside quotes is not a comment, and quoted `|;&<>` is text (#48).
- fail_streak：wheel 發動過的 session 連續失敗兩次時呼叫 wheel-it 的 `force trip`。 · fail_streak calls wheel-it's `force trip` after two failures in a session where wheel ran (#50).

## 0.5.8 — 2026-11-06

- numpy 改為選配：Codex 安裝沒有 numpy 時不再中止，只提醒；router 退回關鍵字比對，所有 hook 照常運作。 · numpy is now optional: the Codex installer warns instead of stopping, and the router falls back to keywords with every hook working.
- 災難指令閘：`gh release create` 改用自己的理由與解法（加 `--draft`），草稿版放行；heredoc 內文當資料，不再誤判成指令（餵給 shell 的 `bash <<EOF` 照查）。 · Guard: `gh release create` gets its own reason and a `--draft` remedy, and drafts pass; heredoc bodies are read as data unless fed to a shell (#40).
- 輪子閘：裝了 ds-claude 時，`task/verify.sh` 工單不擋，其他新檔照擋。 · Wheel gate skips `task/verify.sh` when ds-claude is installed (#41).
- 新增語氣抽查（`tone_gate.py`）與 genie-humanizer 中文翻譯腔規則：依同題配對研究，回覆有「不是 X 而是 Y」、結論冒號、頓號連排等 AI 腔，下一輪提醒，不擋回覆。 · New tone check (`tone_gate.py`) and Chinese translationese rules in genie-humanizer, from a paired human/AI study: AI-tone patterns in a reply produce a next-turn note, never a block.
- Claude Code 長對話回覆漂成英文：prefs 只在 SessionStart 送一次，系統提示與工具輸出都是英文，規則被沖淡。現在每 12 則訊息重送一次（`GENIE_PREFS_REFRESH=<N>`，`0` 關閉）；語言行明講工具呼叫之間的說明也照用；自我檢查發現釘了語言但 Claude Code 沒設 `language` 時提醒一次。 · Long Claude Code sessions drifted into English: prefs went out once at SessionStart and faded under English system prompt and tool output. They are now re-sent every 12th prompt (`GENIE_PREFS_REFRESH=<N>`, `0` = off); the language line covers notes between tool calls; the self-check flags a pinned language missing from Claude Code's `language` setting.

## 0.5.7 — 2026-10-31

- 長 session 換新對話提醒改為預設關閉：原本 150 分鐘後每 30 分提醒 /clear，前提「長 session 會崩」來自已修好的 client 記憶體洩漏。要提醒設 `GENIE_LONG_SESSION_MIN=<分鐘>`。 · The long-session /clear reminder is now off by default; its "long sessions crash" premise came from a since-fixed client memory leak. Set `GENIE_LONG_SESSION_MIN=<minutes>` to opt in (#36).

## 0.5.6 — 2026-10-28

- Windows 上 hook 讀 stdin 不再被系統 ANSI code page（如 cp950）亂碼：繁中提示詞先前會被誤判成 unsure，現在一律以 UTF-8 解碼。 · Hooks now decode stdin as UTF-8 on every platform, fixing CJK prompts being mojibake-misrouted to unsure under non-UTF-8 locales like Windows cp950 (#30).
- 五個 `genie-*` skill 瘦身。 · Slimmed the five `genie-*` skills (#34).

## 0.5.5 — 2026-10-25

- 開場注入瘦身：`AGENTS.md` 從 11.1KB 減到 3.3KB（Claude Code 開場約 4.0k → 1.5k token）。意圖表（`DO:` 已帶做法）、等級段（`register:` 已帶）、「不可關掉」段（hook 強制）、「說話」段（prefs 已帶）刪除；區塊說明改由 prefs 只送沒關掉的區塊；撞功能做法併進 `OVERLAP` 行本身。 · Slimmer startup injection: `AGENTS.md` 11.1KB -> 3.3KB (~4.0k -> 1.5k tokens on Claude Code). Content already carried by `DO:`, `register:`, hooks or prefs is gone; block hints are sent only for blocks that are not off; overlap guidance rides on the `OVERLAP` line (#32).
- 新增 `genie-fix` skill：修 bug 的流程（重現、根因、同型掃描、帶回歸檢查的修法、突變驗收）。 · New `genie-fix` skill: reproduce, root cause, same-pattern sweep, fix with a regression check, mutation-verified acceptance (#31).

## 0.5.4 — 2026-10-23

- 收尾閘（Stop gate）的提醒改到下一輪才注入，不再擋住回覆。 · Stop-gate notes are deferred to the next turn instead of blocking the reply (#27).
- 只改 `.json`／`.jsonl`／`.yml`／`.yaml`／`.csv` 這類資料檔，不再被判「改了檔卻沒跑」。 · Editing only data files (`.json`, `.jsonl`, `.yml`, `.yaml`, `.csv`) no longer triggers "changed files but ran nothing" (#28).
- `get.sh` 分兩種用法：
  - **一般**（`| bash`）：Genie 沒裝就裝、有新版就更新、最新就跳過；附加元件（wheel、fixindex、ponytail）沒裝的一個一個問，已裝的不動。
  - **完整安裝**（`| bash -s -- --all`）：沒裝的全部裝、不問；已裝的有新版先問要不要更新，最新就跳過。
  - `-y` 全部回答「要」。沒有終端機時，一般模式不裝附加元件，完整安裝一律回答「要」。
  `get.sh` has two modes: default asks about each missing add-on and leaves installed ones alone; `--all` installs every missing one, asks before updating installed ones, and skips what is latest. `-y` answers yes to everything.
- 已裝的判斷：plugin 比對市集版本號，git 安裝比對上游 commit。你自己的 wheel skill 或指令算已裝，不覆蓋。
  Installed vs. latest: plugins by marketplace version, git installs by upstream commits. Your own wheel skill or command counts as installed.

## 0.5.3 — 2026-10-20

- 一行安裝：`curl -fsSL https://raw.githubusercontent.com/royalskynet/genie-harness/main/get.sh | bash`。它會偵測電腦上的 `claude` 和 `codex`，沒裝的就裝，裝過的就更新。
  One-line install: `get.sh` detects `claude` and `codex`, installs what is missing and updates what is there.
- 新增這份 CHANGELOG。 · This changelog.

## 0.5.2 — 2026-10-20

- 更新 Claude Code 版改走 `router/safe_update.py`。原生的 `claude plugin update` 會刪掉舊版，開著的 session 的 hook 會找不到檔、擋下每個工具。新做法先備份，所有 scope 一起升，舊版留給還開著的 session，沒人用了才清掉。
  Claude Code updates go through `safe_update.py`: every scope at once, and the old version stays for sessions still running it.

## 0.5.1 — 2026-10-20

- 決定閘擋下時，訊息開頭加上 `Genie decide_gate:`，每擋一次也記一行到 `~/.genie/decide.log`。跟別的工具疊著跑時，看得出是誰擋的。
  The decide gate tags its deny message and logs each deny, so stacked tools can be told apart.

## 0.5.0 — 2026-10-20

防幻覺閘。 · Anti-hallucination gates.

- **完成閘**多查一件事：收尾引用了 commit 或 issue 編號，但這個 session 裡從沒出現過，就擋一次。
  Done gate: a cited commit or issue id never seen in the session blocks once.
- **決定閘**（新）：可逆的問題，模型自己已經標了唯一一個「(Recommended)」，就不准問你，直接照做。不可逆的問題一定要問，而且要附建議和理由。
  Decide gate (new): reversible question with one recommended option → do it; irreversible → must ask with a recommendation and reason.
- **歸因閘**（新）：收尾把失敗推給「模型太弱」或「timeout」，卻沒列任何替代原因，就擋一次。
  Blame gate (new): blaming the model or a timeout with no alternative cause blocks once.
- 同類指令連敗兩次時，提示要先寫反事實（換掉模型或拉長 timeout 也一樣失敗的話，原因是什麼）。
  Two failures in a row now ask for a counterfactual before a third try.
- 找輪子改成強制：該先查現成方案的那一輪，第一個新檔和計畫定案會被擋，查過才放行。
  Prior-art check is enforced by a PreToolUse gate, not only suggested.
- `wheel` 移出本 repo，改用 [royalskynet/wheel-it](https://github.com/royalskynet/wheel-it)。
  `wheel` moved out to its own repo.
- 等級與講人話重整：humanize 每一級預設開；beginner 第一次出現的詞都加括號註解；比喻最多 3 句。
  Levels reworked: humanize on at every level, beginner glosses each new term, at most 3 sentences of analogy.
- 說「更新 Genie／精靈」會路由到更新，並給這台主機真正能跑的指令。
  "Update Genie" routes to the host's real update command.
- CI：shell 語法、router／install／opencode 測試、gitleaks。
  CI runs shell syntax, router/install/opencode tests and gitleaks.

## 0.4.9 — 2026-10-14

- wheel 社群軸加計票（借鏡 Straitly-ai/consensus），用途不同的意見分開算，不硬湊票數。
  wheel tallies community votes, split by use case.

## 0.4.8 — 2026-10-13

- AGENTS.md 新增常駐的「寫程式時」段：先讀再寫、極簡階梯、測試要會失敗。
  AGENTS.md gains an always-on "when writing code" section.
- Codex 的 AGENTS.md 區塊改成覆寫更新，舊安裝也拿得到新規則。
  The Codex AGENTS.md block is upserted, so updates reach existing installs.

## 0.4.7 — 2026-10-13

- wheel registry CLI（find／add／check），取代手打 grep 和 printf。0.5.0 已隨 wheel 移出。
  wheel registry CLI; moved out with wheel in 0.5.0.
- 同類指令連敗兩次就提示停損。 · Two failures of the same command in a row inject a stop-loss hint.
- 災難指令閘多擋兩種：沒帶 label 的 `launchctl bootout`、把憑證值讀到畫面上。例外改成逐條白名單 `GENIE_GUARD_ALLOW`。
  Guard blocks label-less `launchctl bootout` and printing credential values; exceptions are a per-rule allowlist.
- SessionStart 自檢 guard、router、hook 路徑，健康時不輸出。 · SessionStart self-check, silent when healthy.
- `route_ext` 擴充點：使用者自己的路由表。 · `route_ext`: user routing table.
- 反假平衡：先講結論和信心，另一個可能要有證據才提。 · Verdicts first, with confidence; alternatives need evidence.
- opencode：`genie-dedup` 零 token 去重 plugin。 · opencode: zero-token dedup plugin.

## 0.4.5 — 2026-10-07

- wheel 的輪子卡依領域變化速度給重驗期限（30／90／180 天）。
  wheel cards get a re-check date by how fast the domain moves.

更早的版本（0.4.4 以前）看 git log。 · Earlier versions: see git log.
