# HISTORY

## 沿革

### 來源

本紀律誕生於 `royalskynet/coding-hermes`，該 repo 是 `NousResearch/hermes-agent` 的 fork。

原始位置：`skills/software-development/coding-hermes/SKILL.md`，由 commit `4a679a3296367f69ec7dca150a904a1638178b19`（2026-08-20T17:31:13Z，author royalskynet）引入，走 PR [#6](https://github.com/royalskynet/coding-hermes/pull/6)，分支 `feat/coding-hermes-skill`。

### 抽出原因

紀律內容與 hermes-agent runtime 無耦合（純文檔紀律），綁在 9000+ 檔的 fork 內無法被單獨安裝；且該 fork 的 CI 相對 upstream 已漂移（ruff / Windows footguns / test slices 1,3,4 在 `main` 即為紅），docs-only PR 也被連坐。

### mdispatch 廢除

早期紀律曾依賴 `royalskynet/mdispatch`（plan.md 派工 CLI，含 falsifiability lint）。該 repo 已不存在（GitHub API 404），相關條目與安裝指令已移除。派工流程改由各 harness 自己的工單檢查機制承接（v2.6.0 起本 repo 不再附 `/dispatch`）。

### 保留依賴

`royalskynet/fixindex` 仍在維護，為本 skill 的選用依賴。

## 版本

### 2026-09-14 v2.2.0 本體瘦身拆 references

本體 16KB→≤7KB，細節拆六份 `references/`，progressive disclosure。行為不變，僅搬移與新增 References 索引。

### 2026-09-26 v2.3.0 自動情境路由

SKILL.md 改為六模式路由表（定向／圖譜優先／結構映射／查證／審計／專案記憶），先選最輕且足夠的模式、證據不足才升級。

### 2026-10-01 v2.4.0 Layer 2 抽出成 wheel skill

Layer 2 找輪子與查證抽成獨立 `wheel` skill（三軸＋深度分級＋7 級裁決＋不對稱閘＋registry），機制取自 deja-vu 與 dont-reinvent。coding-hermes 只留指標。

### 2026-10-18 v2.5.0 獨立成 ether-code

- 與 `wheel` 曾在 `royalskynet/wheel-it` 同住；該 repo 收斂為「只做 wheel」，本紀律獨立成新 repo `royalskynet/ether-code`。
- `commands/dispatch.md` 移入 `skills/coding-hermes/references/dispatch.md`（`commands/dispatch.md` 保留同內容方便複製到 `~/.claude/commands/`），通用化外部 agent 名稱。
- Layer 2 全文連結改指 wheel-it。

### 2026-10-24 v2.6.0 repo 根目錄即技能

- `skills/coding-hermes/` 攤平到 repo 根目錄：`SKILL.md`、`references/` 直接在根；skill 改名 `ether-code`。
- 刪除 `/dispatch`（`commands/dispatch.md` 與 `references/dispatch.md`）。

## 安裝與本機映射

`npx skills add https://github.com/royalskynet/ether-code` 安裝到 `~/.hermes/skills/ether-code/`。本機 `~/.agents/skills/ether-code`、`~/.codex/skills/ether-code`、`~/.claude/skills/ether-code` 統一指向本 repo 的 clone 根目錄（`~/dev/ether-code`）。
