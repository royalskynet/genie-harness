# DEV HANDOFF LOG

> 脫敏版：無絕對路徑、無憑證、無個人資訊。空白模型可自足接手。

## 分支與狀態

- 分支：`feat/beginner-autonomy-and-community-first`
- 基於：`origin/main`（含 PR #1 install retry safety、PR #2 AGENTS beginner section）
- 最新 commit：`b007db4` fix: single UserPromptSubmit registration per event, match hooks by script name
- 工作樹：clean（所有變更已 commit）

## 已完成

### 1. 安全閘（`router/guard_dangerous.py`）
- PreToolUse hook，擋災難指令（deny）與模糊指令（warn）
- 41 deny + 4 warn 規則，33 must-pass，5 file rules，6 write-blocked，6 write-allowed
- 掃寫入腳本內容（A1：防「寫腳本再執行」繞過）
- 替代動詞規則（A2：git clean -fdx、shutil.rmtree、mv /dev/null、find -delete 等）
- 逃生門 `GENIE_ALLOW_DANGEROUS=1` 寫 audit log（A7）
- fail-open：任何例外都放行
- 測試：`python3 router/test_guard.py` → PASS

### 2. 偏好系統（`router/prefs.py` + `router/prefs_hook.py`）
- 6 個三態區塊（terms/examples/steps/research/confirm/humanize）
- level 預設層（beginner/intermediate/advanced），不覆蓋使用者 pin
- 單次覆寫（`!terms off`、`不用百科`）與永久關閉（`不要再給我百科了`）
- 問「什麼是 X」時強制 on，不管設定
- 原子寫入、壞檔退回預設、hostile key 忽略
- **B1 斷言**：所有區塊 off 時，guard 仍然 deny（跨模組測試）
- 測試：`python3 router/test_prefs.py` → PASS（13 項）

### 3. Router（`router/genie_router.py` + `router/intents.json`）
- 新增 `teach_me` intent、`unsure` abstain 層、confidence 輸出
- 缺模型時印 stderr 警告（C3）
- 74 句手寫 dev set：strict 72/74 = 97%，safe 74/74 = 100%
- 測試：`GENIE_MODEL_DIR=<model_path> python3 router/test_router.py` → PASS

### 4. Skills（5 個）
- `genie-humanizer`：對話關係（上下文、語氣、節奏、誠實），禁止假人味
- `genie-research`：社群優先 → 官方 → GitHub 高星活躍；有輪子不自造
- `genie-execute`：可逆步驟批次做，只停不可逆那一步
- `genie-explain`：降一级難度，一段 ≤3 句，一次只講一個詞
- `genie-terms`：一次一個詞、白話、具體比喻

### 5. AGENTS.md
- 重寫：區塊表、單次標記語法、不可關掉的部分、不可逆只有四種
- 說話規則：白話短句、先結論、最多 3 選項、不確定就說

### 6. 文件
- `PREMORTEM.md`：30 條預測失效模式 + 預防設計（5 層）
- `README.md`：雙語，誠實標示 74 句自寫 dev set
- `hooks.json`：UserPromptSubmit（router + prefs）+ PreToolUse（guard）
- `install.sh`：多 hook 合併 + smoke test（A4/E3）

### 7. 測試
- `router/test_repo.py`：大小預算、無絕對路徑、hook 指向存在、無漂移（D1/D2/E4/A5/C1）
- 全部 PASS

## 未完成 / 阻塞

### install.sh 多 hook 合併邏輯（唯一阻塞）
- **問題**：`tests/test_install.py` 的 `test_reinstall_preserves_backups_and_refreshes_moved_hook` 期望 `UserPromptSubmit` 只有一個 registration entry，但當前 install.sh 在「repo 移動後第二次安裝」時會產生 2 個 entry
- **已失敗的三種寫法**（不要重複）：
  1. 逐 hook 建立 entry → 2 個 entry
  2. 按 event 分組（UserPromptSubmit 一組、PreToolUse 一組）→ 還是 2 個
  3. 修正搜尋變數名 → 還是 2 個
- **正確方向**：先讀 Codex 官方 hooks 文件（`gh` 查 `openai/codex` repo 的 hooks 相關 source/docs），確認「多個 hook 如何放進同一個 registration entry」的結構
- **關鍵約束**：
  - `tests/test_install.py` 不可修改
  - `backup_once`、`already_installed`、trust hash 邏輯不可破壞
  - 不可引入新的 Python 依賴
- **驗收**：`python3 tests/test_install.py` → `Ran 4 tests` + `OK`

## 下一步

1. 修好 install.sh 多 hook 合併（見上）
2. 跑全部測試確認沒改壞：
   ```bash
   python3 router/test_guard.py
   python3 router/test_prefs.py
   python3 router/test_repo.py
   GENIE_MODEL_DIR=<model_path> python3 router/test_router.py
   python3 tests/test_install.py
   ```
3. commit + push + 建立 PR

## 關鍵檔案

| 檔案 | 用途 |
|---|---|
| `router/guard_dangerous.py` | PreToolUse 安全閘 |
| `router/prefs.py` | 偏好系統核心 |
| `router/prefs_hook.py` | UserPromptSubmit hook |
| `router/genie_router.py` | 意圖分類器 |
| `router/intents.json` | 意圖定義與門檻 |
| `router/eval_set.json` | 74 句手寫 dev set |
| `install.sh` | 安裝器（多 hook 合併待修） |
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
