# 指令構造 — 三條重踩教訓全文（現況：未實驗驗證）

## 背景

`context-router`／Beacon 記憶召回綁在 **user prompt** 上；**agent 自己構造指令的那一刻沒有任何注入**。以下三條是重踩過的「指令構造型」教訓 —— 靠語意檢索救不回來,必須寫成常駐行為。這是「高頻且後果大」才被選入；全部塞進去會讓 skill 膨脹,違反 progressive disclosure。

## 三條

1. **`head` 截斷輸出判斷內容會誤判**（fixindex 0547#5）：`git status --porcelain | head` 剛好被 10 行改名填滿，未追蹤檔的證據被切掉，據此下錯結論。→ 判斷「有沒有某類輸出」時用 `wc -l`／`grep -c` 數全量，不用 `head` 當全貌；要節錄就明寫「節錄，共 N 行」。
2. **`mv` 語意隨目標存在與否而變**（fixindex 0629#2）：目標不存在＝改名、目標存在＝搬進去，同條指令兩種結果（實測把狀態目錄包成 93 層巢狀）。→ 移動前先確認目標目錄是否已存在，且 `mv` 後用 `find`／`ls` 驗證最終位置與層數，不預設語意。
3. **`push` 錯 ref／無效 ref 會靜默 no-op**（fixindex 0636）：`git push` 印「Everything up-to-date」但本地 10 個 commit 沒上去（ref 指錯），退出碼仍是 0。→ push 後比對 `git log origin/<branch>..HEAD` 剩餘 commit 數，或 `git status -sb` 看 ahead 數，不靠「沒報錯」當成功。

## 追蹤

行為改善**未經實驗驗證**——若再踩到三種之一，代表本段固化無效，應改 lint 或收工自檢。追蹤：fixindex 0645。