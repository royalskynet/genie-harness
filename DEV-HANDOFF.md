# DEV HANDOFF LOG

> 脫敏版：無絕對路徑、無憑證、無個人資訊。空白模型可自足接手。

## 分支與狀態

- 分支：`feat/dispatch-engine-claude-code`（PR #1–#8 已併入 main）
- 主軸：意圖路由＝派工引擎。每則訊息分類後注入 `DO:` 行點名這一輪要跑的 skill；要做東西／選方案一律先 wheel。使用者假設為完全小白，不會打指令
- 宿主：Codex（`install.sh`）＋ Claude Code（`.claude-plugin/` plugin，`claude/hooks.json`）

## 已完成

### 1. 安全閘（`router/guard_dangerous.py`）
- PreToolUse hook，擋災難指令（deny）與模糊指令（warn）
- 49 deny + 4 warn 規則，33 must-pass，5 file rules，6 write-blocked，6 write-allowed
- git 狀態警告 5 條（`inspect_git`）：未存檔時丟棄改動、刪 stash、`branch -D`、把 .env/金鑰加進 git、repo 設公開。只在指令吻合時才跑 `git status`；乾淨工作區不吵，在暫存 repo 實測
- 掃寫入腳本內容（A1：防「寫腳本再執行」繞過）
- 替代動詞規則（A2：git clean -fdx、shutil.rmtree、mv /dev/null、find -delete 等）
- 逃生門 `GENIE_ALLOW_DANGEROUS=1` 寫 audit log（A7）
- fail-open：任何例外都放行
- 測試：`python3 router/test_guard.py` → PASS

### 2. 偏好系統（`router/prefs.py`，由 `genie_router.py` 一併注入；`prefs_hook.py` 已併入並刪除，install.sh 會清掉舊註冊）
- 6 個三態區塊（terms/examples/steps/research/confirm/humanize）
- level 預設層（beginner/intermediate/advanced/expert）＋每級 register（比喻來源），不覆蓋使用者 pin；`!level <l>` 可在對話切換
- 首次啟動（無 prefs.json）注入 FIRST RUN：自我介紹＋問等級；research 每級預設 on
- `router/overlap.py` 依宿主掃 hooks（Codex `hooks.json`／Claude Code `settings.json`）＋skills 目錄找撞功能工具（guard/research/style），問一次交給誰（`!owner`），只在對方工具仍安裝時生效；guard 交出需該工具真的是 PreToolUse hook
- 單次覆寫（`!terms off`、`不用百科`）與永久關閉（`不要再給我百科了`）
- 問「什麼是 X」時強制 on，不管設定
- 原子寫入、壞檔退回預設、hostile key 忽略
- **B1 斷言**：所有區塊 off 時，guard 仍然 deny（跨模組測試）
- 測試：`python3 router/test_prefs.py` → PASS（19 項）

### 3. Router（`router/genie_router.py` + `router/intents.json`）
- intents：build_request／research_needed／execute_request／clear_request／teach_me／user_confused／risky_action／ambiguous_request／continue＋`unsure` abstain
- `dispatch()`：intent → `DO:` 行；`--host codex|claude` 決定 skill 寫法（`$wheel`／`genie-harness:wheel`）；research off 或交給他工具時換文案
- 「FIRST action MUST be wheel」是實測後的措辭：軟性「run wheel」在無頭 Claude Code 4 次跳過 1 次，改後 Sonnet 5/5、Haiku 2/2
- 缺模型時印 stderr 警告，DO 改 `degraded`（交還模型判斷、仍 wheel-first）（C3）
- 模型位置：`GENIE_MODEL_DIR` > `router/model` > `~/.genie/model`（plugin 用後者，升級不會被洗掉）
- 87 句手寫 dev set：strict 84/87 = 97%，safe 87/87 = 100%
- 測試：`GENIE_MODEL_DIR=<model_path> python3 router/test_router.py` → PASS

### 4. Skills（5 個）
- `genie-humanizer`：對話關係（上下文、語氣、節奏、誠實），禁止假人味
- `wheel`：動手前查官方／社群共識／成熟輪子 → 7 級裁決；自造最後一格
- `genie-execute`：可逆步驟批次做，只停不可逆那一步
- `genie-explain`：降一级難度，一段 ≤3 句，一次只講一個詞
- `genie-terms`：一次一個詞、白話、具體比喻

### 5. AGENTS.md
- 重寫：區塊表、單次標記語法、不可關掉的部分、不可逆只有四種
- 說話規則：白話短句、先結論、最多 3 選項、不確定就說

### 6. 文件
- `PREMORTEM.md`：30 條預測失效模式 + 預防設計（5 層）
- `README.md`：雙語，誠實標示 74 句自寫 dev set
- `hooks.json`：Codex 範本，UserPromptSubmit（router，含 prefs）+ PreToolUse（guard）
- `claude/hooks.json`：Claude Code plugin，SessionStart（`session_start.sh`：輸出 AGENTS.md、首次背景下載模型）+ UserPromptSubmit（`--host claude`）+ PreToolUse（guard）
- `install.sh`：多 hook 合併 + smoke test（A4/E3）

### 7. 測試
- `router/test_repo.py`：大小預算、無絕對路徑、hook 指向存在、無漂移（D1/D2/E4/A5/C1）
- 全部 PASS

## 未完成 / 阻塞

無。install.sh 多 hook 合併邏輯已在 `b007db4`（fix: single UserPromptSubmit registration per event, match hooks by script name）修好，`tests/test_install.py` 全數 4 項 PASS（含 `test_reinstall_preserves_backups_and_refreshes_moved_hook`）。此節先前脫敏時未同步跑驗收，內容已過時，2026-09-30 重跑確認全綠後更新。

## 下一步

1. 全部測試已確認 PASS：
   ```bash
   python3 router/test_guard.py                                          # PASS
   python3 router/test_prefs.py                                          # PASS
   python3 router/test_repo.py                                           # PASS
   GENIE_MODEL_DIR=<model_path> python3 router/test_router.py            # strict 97% / safe 100%
   python3 tests/test_install.py                                         # Ran 5 tests, OK
   claude plugin validate .                                              # plugin + marketplace manifest
   ```
2. 已知缺口：`overlap.py` 只掃 Codex 設定；未附 `.codex-plugin/`；eval 仍是作者自寫語料，需要真實使用紀錄校準

## 關鍵檔案

| 檔案 | 用途 |
|---|---|
| `router/guard_dangerous.py` | PreToolUse 安全閘 |
| `router/prefs.py` | 偏好系統核心 |
| `router/genie_router.py` | 唯一 UserPromptSubmit hook：分類 → DO 派工 → prefs |
| `.claude-plugin/`、`claude/` | Claude Code plugin |
| `router/intents.json` | 意圖定義與門檻 |
| `router/eval_set.json` | 87 句手寫 dev set |
| `install.sh` | Codex 安裝器 |
| `tests/test_install.py` | 安裝測試（不可修改） |
| `hooks.json` | hook 範本 |
| `AGENTS.md` | 核心行為規則 |
| `PREMORTEM.md` | 預測失效模式 |
| `README.md` | 雙語說明 |

## 環境變數

- `GENIE_MODEL_DIR`：router 模型路徑（測試時指向 `<repo>/router/model`）
- `GENIE_PREFS`：prefs 檔案路徑（測試時用 temp dir）
- `GENIE_ALLOW_DANGEROUS=1`：逃生門（寫 audit log）
- `CODEX_HOME`：Codex 設定目錄（安裝時用）
