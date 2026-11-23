---
name: ether-code
version: 2.6.0
author: royalskynet (Ether)
description: "複雜跨檔開發、陌生程式庫或服務、架構或影響面不明、外部整合、重複失敗時使用：先建立可驗證的系統模型，再選最小實作、查證、驗收與停損。一般局部小修、純配置、純問答或已有更窄專用 workflow 時不使用；全庫技術債審計僅在使用者明確要求時進入。"
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [coding, debugging, fixindex, discipline, stop-loss, glue-coding, architecture, kanban, self-sufficient]
    related_skills: [systematic-debugging, hermes-agent, kanban-worker]
---

# ether-code — 先理解，再改變

**ENGINEERING = 在改變系統前先理解它。** 理解深度與風險、範圍、不確定性成比例；「先理解」不等於預設全庫掃描。

## 自動情境路由

先選**最輕且足夠**的模式；證據不足才升級，不因工具存在就使用。

| 訊號 | 模式 | 必做 |
|---|---|---|
| 路徑已知、單一子系統、低風險 | 定向理解 | 讀受影響的導出、調用者、測試、共用庫與配置；建立局部流程後修改 |
| 問題涉及跨檔關係，且已有 `graphify-out/graph.json`、`.ua/knowledge-graph.json` 或 `.understand-anything/knowledge-graph.json` | 圖譜優先 | 先查現成圖譜，再以原始碼驗證關鍵邊；圖譜是索引，不是事實 |
| 陌生程式庫、跨信任／持久化／公開契約邊界、跨 3+ 模組，或入口與資料流不清 | 結構映射 | 盤點 manifest、入口、邊界、主要流向與相關 churn；形成可證偽 mental model |
| 動手寫任何非 trivial 程式碼前，或同一解法連敗 2 次 | 查證 | 跑 `/wheel` 再決定自造；停止猜 API 或堆變體 |
| 使用者明確要求全庫健康、架構或技債審計 | 審計 | 先結構映射再判斷；每個 finding 附 `file:line`；另列反證與不確定性；不自動建議重寫 |
| 已證實的專案特有陷阱或慣例 | 專案記憶 | 若既有 `.claude/napkin.md`，依授權精煉成可執行規則；具跨 session 檢索價值的 defect 才進 fixindex |

完整升降級判準、圖譜新鮮度、定向命令與審計輸出 → [references/orientation-routing.md](references/orientation-routing.md)。不要只為定向而安裝工具或產生持久圖譜；若重型分析會新增大量產物、耗費顯著 token／時間，除非使用者已明確要求，先說明成本。

## 工作流

1. **盤點現況**：必讀適用的 `AGENTS.md`／專案規則與版控狀態；再按所選模式讀相關 manifest、README 與架構文件。接手續作時以現況為準，不把報告當事實。
2. **定義驗收**：寫出最小可重跑的成功條件；缺少會改變解法的必要資訊才詢問。
3. **建立模型**：按上表選模式。至少能回答「入口在哪、資料／控制怎麼走、哪個不變量不可破壞、已界定範圍內哪些調用者受影響、如何證偽我的理解」。答不出才升級。
4. **選最小解**：依序檢查：不做／刪除 → 復用現有實作 → 標準庫 → 平台原生能力 → 既有相依 → 最少新代碼。不得省略信任邊界驗證、資料安全、必要錯誤處理與可及性。
5. **修根因**：優先修所有相關調用者共經的邊界，不在每個症狀點各貼 guard。只改必要範圍，不順手重構。
6. **驗證意圖**：跑受影響範圍的測試／lint／型別檢查；非平凡邏輯至少留一個能因回歸而失敗的最小判決。若服務有 listener，啟動後先確認預期端口與健康，再驗功能。
7. **沉澱學習**：只記可重用且已證實的規則。不要建立時間線式日誌；每條都寫明「下次改做什麼」。

## 實作紀律

- 明說關鍵假設與推翻條件；不確定但可安全續做時標 `[Assumption]`。
- 缺陷計畫分成「根治」與「預防加固」。根治必做；加固只在有復發風險且能用小型 test／guard／hook 落地時做，不為湊完整而造框架。
- 先查現有相依與相鄰模式。能連不造，能復用不重寫；新增相依前證明現有能力不足。
- 不留無遷移需求的相容層；從最小可運行版本分層成長；邊界清楚，拒絕只對當下有效的臨時方案。

## 三層行為紀律

| 層 | 觸發 | 動作 |
|---|---|---|
| 1. 查現況與舊帳 | 跨 session、重複故障、破壞性操作或 repo 規則要求 | 先查版控／服務狀態；再查既有 napkin、fixindex 與 session 歷史 |
| 2. 找輪子與查證 | **所有 coding 任務預設觸發**，排在 Layer 1 之後、動手之前（trivial 單行改動／純配置例外，寫「輪子：不適用（原因）」豁免）；同一解法連敗 2 次必觸發 | 跑 `/wheel`（三軸＋輪子卡）；計畫寫一行「輪子：<裁決> <來源>」或「輪子：不適用（原因）」 |
| 3. 記錄並停手 | 預設試過 3 種實質不同方案仍失敗；宿主若有更嚴格的重試上限，以宿主為準 | 記下假設、反例、證據與最小下一步，交回決策 |

Layer 2 全文 → [`/wheel` skill（wheel-it）](https://github.com/royalskynet/wheel-it)。

## 停損

不要混用兩個軸：**重試軸**判斷同題是否續試；**範圍軸**判斷新發現是否現在修。卡住用重試軸，清單變長用範圍軸。

- 同一解法連續失敗：停止換參數式變體，重述假設、反例與決定性下一步。
- 影響面大且靜默失敗者優先；影響小且會明確報錯者可記錄不修。
- 一次只推進一層；有依賴不並行；挖到第三層就寫交接，不直接擴修；新發現超過 5 條另開文件。

全文與對話判準 → [references/stop-loss.md](references/stop-loss.md)。

## 記憶邊界

- **Napkin**：專案級、會重複遇到的陷阱／慣例；若檔案存在，開工只讀並套用。僅在使用者或 repo workflow 要求維護 Napkin、且規則已證實可重用時，才去重、淘汰與回寫；不要只因 skill 觸發就建立或修改檔案。
- **fixindex**：具跨 session 檢索價值、已定位根因且已修好的 defect。未修診斷寫入交接文件，不進 fixindex；階段完成、任務交付、一般失敗也不寫。
- **架構圖譜**：用來定位閱讀順序與關係假設；關鍵結論必回到原始碼、設定或可重跑輸出驗證。

fixindex 完整格式、禁則與寫入驗證 → [references/fixindex-usage.md](references/fixindex-usage.md)。維護 agent 系統本身 → [references/agent-tools.md](references/agent-tools.md)。

## 驗收紀律

- Judge／Guard／referee 類驗收必含至少一條應被 block／rewrite 的紅樣本；全 PASS 可能是 fail-open。
- 貼原始輸出；若節錄，標「節錄，共 N 行」並附產生命令。
- 工具回報也是宣稱：正面命中先抽驗誤報；負面探測先驗證探測姿勢。
- 新訊號收集器先逐筆看前 N 筆內容，再接分類器或下游。

全文 → [references/acceptance.md](references/acceptance.md)。

## 指令與協作

- 判斷全量是否含某類輸出，用 `wc -l`／`grep -c`，不用 `head` 當全貌。
- `mv` 前確認目標是否存在；完成後驗證最終位置與層數。
- push 後檢查 ahead commit，不以「沒報錯」當成功。
- 代理只處理可獨立、有清楚輸入輸出的工作；主代理保留系統模型、衝突裁決與最終驗收。

案例 → [references/command-construction.md](references/command-construction.md)。

## 收工自檢（重大改動限定）

- [ ] 能用入口、流向、不變量、受影響調用者與反證描述系統模型
- [ ] 使用了最輕足夠的模式；圖譜結論已抽查原始碼
- [ ] 新相依／陌生整合／連敗已完成 Layer 2 查證
- [ ] 改動位於根因邊界，未擴成順手重構或臨時相容層
- [ ] Judge／Guard／referee 類驗收含應失敗的紅樣本；其他改動有能因回歸而失敗的最小測試
- [ ] 只將已證實、可重用知識寫進正確記憶層

<!-- LEARNED:BEGIN -->
<!-- LEARNED:END -->

## References 索引

| 檔名 | 何時讀 |
|---|---|
| `references/orientation-routing.md` | 開工選理解深度、使用既有圖譜或做全庫審計 |
| `references/stop-loss.md` | 卡住或清單變長 |
| `references/acceptance.md` | 驗收前 |
| `references/fixindex-usage.md` | 查舊帳或完工寫入 fixindex |
| `references/agent-tools.md` | 維護 agent 系統本身 |
| `references/command-construction.md` | 三條指令案例細節 |
