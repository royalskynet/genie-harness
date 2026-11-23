# ether-code

> English: [README.md](README.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**先理解，再改變。** 給 coding agent 的行為紀律：動手前盤點現況、定義驗收、選最輕但足夠的理解深度、找輪子再自造、卡住時停損、修完貼真輸出。

找輪子那一步（三軸 prior-art、輪子卡、7 級裁決）在 [royalskynet/wheel-it](https://github.com/royalskynet/wheel-it) 的 `wheel` skill；本 repo 只留「怎麼做程式」的紀律，不重抄。

**技能類型：** 純文檔紀律，無 runtime 依賴。選用依賴：[fixindex](https://github.com/royalskynet/fixindex)（症狀→修法查詢）。

## 安裝

```bash
npx skills add https://github.com/royalskynet/ether-code
```

安裝到 `~/.hermes/skills/ether-code/`。**開新 session** 才會進索引生效。

## 內容

repo 根目錄就是 `ether-code` 這個 skill：本體 `SKILL.md` 加六份按需讀取的 `references/`：

| 檔 | 何時讀 |
|---|---|
| `references/orientation-routing.md` | 開工選理解深度、使用既有圖譜、做全庫審計 |
| `references/stop-loss.md` | 卡住或清單變長 |
| `references/acceptance.md` | 驗收前 |
| `references/fixindex-usage.md` | 查舊帳或完工寫入 fixindex |
| `references/agent-tools.md` | 維護 agent 系統本身 |
| `references/command-construction.md` | 三條指令案例細節 |

## 重點

- **自動情境路由** — 定向理解／圖譜優先／結構映射／查證／審計／專案記憶，先選最輕且足夠的模式，證據不足才升級。
- **三層紀律** — 查現況與舊帳 → 找輪子（跑 `/wheel`）→ 三條路線失敗後記錄並停手。
- **停損兩軸** — 重試軸（同題續不續試）與範圍軸（新發現該不該現在修）分清，不混用。
- **驗收紀律** — Judge／Guard 類驗收必含應失敗的紅樣本；工具回報也是宣稱；貼原始輸出。
- **記憶邊界** — napkin（專案陷阱）、fixindex（已定位已修的 defect）、圖譜（索引不是事實）各管各的。

## 宿主分工

預設試過三種實質不同的方案仍失敗，就記錄並停手；宿主若有更嚴格的重試上限，以宿主為準。反事實閘門與查舊帳的具體入口，屬於每輪都生效的全域規則（CLAUDE.md／AGENTS.md／system prompt）。

## 觸發條件

**觸發：** 複雜跨檔開發、陌生程式庫或服務、架構或影響面不明、外部整合、重複失敗的任務。

**不觸發：** 一般局部小修、純配置、純問答；全庫技術債審計只在使用者明確要求時進入。

## 來源

從 [royalskynet/coding-hermes](https://github.com/royalskynet/coding-hermes)（`NousResearch/hermes-agent` 的 fork）抽出，先在 wheel-it 與 `wheel` 同住，2026-10-18 起獨立成本 repo。沿革見 [HISTORY.md](HISTORY.md)。

## License

MIT。Copyright (c) 2026 royalskynet。
