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
- level 預設層（beginner/intermediate/advanced/expert）＋每級 register（比喻來源），不覆蓋使用者 pin；`!level <l>` 可在對話切換
- 首次啟動（無 prefs.json）注入 FIRST RUN：自我介紹＋問等級；research 每級預設 on
- `router/overlap.py` 掃 hooks.json＋skills 目錄找撞功能工具（guard/research/style），問一次交給誰（`!owner`），只在對方工具仍安裝時生效；guard 交出需該工具真的是 PreToolUse hook
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
- `hooks.json`：UserPromptSubmit（router + prefs）+ PreToolUse（guard）
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
   python3 tests/test_install.py                                         # Ran 4 tests, OK
   ```
2. 建立 PR 到 `main`

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
