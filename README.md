# Genie Harness

把 [Codex CLI](https://github.com/openai/codex) 變成對技術小白友善的 AI coding assistant。
免費、本地、CPU-only、不加任何付費服務。

```
你打字  →  Tiny Semantic Router (0.07s, 58 MB RAM)  →  Codex  →  白話短句的回答
                 │
                 └─ 只貼一個標籤：genie: intent=ambiguous_request
                    AGENTS.md 看標籤決定：直接做／只問一題／先查官方文件／講簡單一點／一次一步／先警告
```

## 為什麼要 Router

Codex 每次都自己猜「使用者到底想幹嘛」很浪費推理，而且對小白常猜錯（不是多問就是少問）。
Router 用一個極小的靜態 embedding 模型在本地 0.07 秒分好類，Codex 只要照標籤做。

六個標籤：`clear_request` `ambiguous_request` `research_needed` `user_confused` `execute_request` `risky_action`

## 安裝（一次）

```bash
git clone https://github.com/<you>/genie-harness ~/genie-harness
cd ~/genie-harness && bash install.sh
```

需要：Codex CLI（hooks 已是 stable）、Python 3.9+、numpy。第一次會下載 512 MB 模型，處理後只留 35 MB。

install.sh 做的事都可復原（會先備份成 `*.bak-genie`）：
- `~/.agents/skills/genie-*` 四個 symlink
- `~/.codex/hooks.json` 加一條 `UserPromptSubmit`
- `~/.codex/AGENTS.md` 尾端加上本專案的 AGENTS.md

## 目錄

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

## 技術選型（為什麼是這樣）

| 需求 | 選擇 | 淘汰了什麼 |
|---|---|---|
| 分類模型 | [model2vec](https://github.com/MinishLab/model2vec) 的 `potion-multilingual-128M`（MIT，靜態 embedding，中英皆可） | sentence-transformers（要 torch，數百 MB）、本地 LLM（RAM／啟動時間） |
| 執行期 | 不裝 model2vec／tokenizers，只用 numpy：詞表修剪到 11 萬 + 貪婪最長匹配 + int8 rows mmap | 完整 `tokenizers` 載 50 萬詞表要 770 MB RAM、0.4s |
| 接入 Codex | 官方 `UserPromptSubmit` hook，stdout 一行變 developer context | 包一層 CLI wrapper（多一個指令要學） |
| 行為規則 | AGENTS.md + Skills（Codex 官方機制） | 自寫 prompt 注入 |

實測（M4，Python 3.9）：hook 整條路 0.07s、RSS 58 MB、15/15 測試通過；修剪詞表版與官方完整 tokenizer 分類結果 10/10 一致。

## 調整

- 分類不準：在 `router/intents.json` 加關鍵字（零成本、優先級最高）或範例句，跑 `python3 router/test_router.py`。
- 想看分到哪一類：`GENIE_DEBUG=1 python3 router/genie_router.py "你的句子"`。
- 模型缺檔或壞掉：router 自動退回 `clear_request`，Codex 照常可用。

## 沒做的（MVP 刻意省略）

- 對話狀態（例如記住使用者說過看不懂）：交給 AGENTS.md 的規則，不另存狀態。
- 訓練分類器：質心 + cosine 夠用；準確度不夠再上 `model2vec[train]`。
- 多語系 UI：AGENTS.md 是繁體中文，改一份即可換語言。
