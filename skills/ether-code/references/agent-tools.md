# agent-tools —— agent 系統自身的維護工具

> 只在「維護 agent 系統本身」時才需要讀這份：改行為契約檔、查系統健康、
> 動自我改進管線。一般 coding／debug 任務用不到。

## 這套系統的三層切分

| 層 | 位置 | 誰能寫 |
|---|---|---|
| **契約** skill／`CLAUDE.md`／openclaw 人格檔 | `<memory>/agent/`（private repo，live 位置是 symlink 指過去） | 主 session |
| **資料** golden corpus／指標快照 | `<memory>/templates/` | 主 session |
| **工具** 下列腳本 | `~/dev/agent-tools`（`royalskynet/Glass-Breaker`, private） | **可派 worker** |

**為什麼工具要獨立出去**：worker 的 approvals policy 把 `<memory>/` 列為「需審批」，
派過去不會乾脆失敗，而是卡審批逾時、燒完 iteration 預算（fixindex `0292`）。
工具搬出來、把該 repo 設成 task workspace，worker 的讀寫與 `git add`/`commit` 就自動放行。

## 指令

全部在 `~/dev/agent-tools/bin/`，需要 `FIXINDEX_DIR` 有值（互動 shell 由 `~/.zshenv` 匯出；
**launchd／cron／hook 子行程不會載入 zshenv**，那些情境要顯式帶入）。

| 指令 | 用途 |
|---|---|
| `python3 bin/agent_paths.py` | 印出全部路徑解析結果。路徑不對時第一個跑這支 |
| `python3 bin/drift.py` | 偵測 live 位置漂移（不是 symlink／指向錯／內容不符）。`drift=0` 才算健康，非 0 回 exit 1 |
| `python3 bin/link.py --dry-run` | 列出將建立的 symlink，不碰檔案系統。**實做前一定先跑這個** |
| `python3 bin/link.py` / `--restore` | 建立 symlink／還原成實體檔 |
| `python3 bin/metrics.py --week <ISO週>` | 全局指標快照（空召回率／返工率／完成時間／攔截數） |
| `python3 bin/metrics.py --week A --compare B` | 逐欄 delta |
| `python3 bin/classify_feedback.py --report` | memory／skill／fixindex 邊界分類報告（唯讀） |

## 判準

- **改了行為契約檔之後跑 `drift.py`。** live 位置被某個 runtime 覆寫成實體檔時，
  兩份真相會開始漂移而沒有任何錯誤訊息。
- **指標看趨勢不看單週。** 第一週的 delta 沒有意義（基線是空的，會把「開始落 log」
  誤報成「變差」）。另：**規則新增數與 PR 數不是進步指標**，correction 率、返工率才是。
- **`classify_feedback.py` 的分類表是硬編的**（腳本檔頭有揭露）——它是凍結成程式碼的
  一次性報告，不是分類器；新增檔案它不會判。只有「未進版控清單」那段是每次現場算的。
- 新增工具**不得寫死絕對路徑**，一律 `from agent_paths import ...`。
  驗收：`grep -rn "/Users/" bin/` 必須無輸出。
- 工具只負責產出，**寫入 `<memory>/` 或 `~/.claude/` 由主 session 執行**。
  這條界線就是「可派 worker」的前提，破壞它等於白搬。

## 自寫 Hermes 腳本（cron／launchd entry point）

- **第一個 hermes 相關 import 必須是 `import hermes_bootstrap`**，排在任何
  `agent.*`、`llm_fallback`、第三方依賴之前。bootstrap 在模組層會 `execv` 換到內建
  python 並用 runpy 重跑整支腳本；若依賴已先在 venv 解譯器載到一半，重跑的子行程會在
  依賴尚未接上時 import 而 `ModuleNotFoundError`（fixindex `9893`）。
- **辨識特徵**：`python -c "import X"` 成功、跑檔案卻 `No module named X`；log 開頭印兩次；
  traceback 最外層是 `<string>` 裡的 `runpy.run_path`。看到這組合別猜 PATH 或 hook，
  先 monkeypatch `os.execv` 印堆疊，找出是誰換了解譯器。
- 驗收照 plist 原樣重現：`env -i` 帶 plist 的 `PATH`／`HERMES_HOME`，用 plist 指定的
  解譯器跑；腳本有 `--dry-run` 就用它，避免排程外觸發真實副作用。

完整說明見該 repo 的 `README.md`，本檔不重抄。
