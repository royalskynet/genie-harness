# fixindex 使用指南

本 skill 的開工查舊帳與完工寫入依賴 `fixindex` CLI（[royalskynet/fixindex](https://github.com/royalskynet/fixindex)）。
**fixindex 是選用依賴**：未安裝時，階段 0 的 `fixindex find` 段落改以本機記憶 / 搜尋工具代替，skill 其餘紀律照樣適用。

## 環境變數

- `FIXINDEX_DIR` — 覆蓋預設 runbook 目錄（預設 `~/notes/runbook/fixes`）
- `FIXINDEX_INDEX` — 覆蓋索引檔路徑

## 查詢

```bash
fixindex find "<錯誤症狀 / 系統名>"
```

命中時直接讀對應 `fixes/NNNN-*.md`。

## 寫入 defect 條目

```bash
printf 'SYMPTOM: <可搜尋的症狀描述>\nROOT: <根因>\nFIX: <具體修復動作>\nVERIFY: <可重跑指令 + 期望結果>' | fixindex fi
```

- `SYMPTOM`：別人會拿來搜尋的文字，不是進度報告
- `ROOT`：根因，一句話
- `FIX`：具體修復動作，不寫「Phase 3 修好」
- `VERIFY`：**可重跑**的指令 + 期望結果；一次性讀數不算

## 寫入 insight 條目

```bash
printf 'CONTEXT: <背景>\nINSIGHT: <洞察>\nIMPLICATION: <影響>\nREVISIT-WHEN: <何時需要重新檢視>\nQUERIES: <相關查詢關鍵字>' | fixindex fi
```

## 新域與修復

- 新域：`fixindex new <slug>`
- frontmatter 損毀：`fixindex doctor --fix`

## 禁則清單

1. **date 進檔名**：檔名不含日期
2. **`## §N (date)` 修正片段**：直接改原文，不 append 修正段
3. **Verify 用一次性讀數**：必須是可重跑 + 有期望結果
4. **一條記塞多個 defect**：一事一條
5. **secrets**：含截斷 key 前綴的 credential 一律不入檔

## 未修診斷

未修診斷寫入交接文件，記錄已排除證據與最小下一步；不要寫入 fixindex。宿主若另有更嚴規則，依宿主規則。

## 寫入驗證:search 命中 ≠ 寫入成功

`fixindex fi` 寫完後**不得**用 `fixindex find "<剛寫的症狀>"` 當成功判準。索引是語意搜尋,幾個月前的相近舊帳一樣會命中高分 —— 寫入根本失敗時也照樣「查得到」,看起來像成功。

**唯一判準是 `fixindex fi` 自己回傳的 JSON**:

```json
{"appended": "0322-<slug>.md", "section": 2, "committed": "05c8954", "pushed": true, "git_error": null}
```

- `appended` + `section` → 條目的精確位址 `NNNN#S`,回報時貼這個,不要只寫編號
- `committed` 有 SHA、`pushed: true`、`git_error: null` → 才算落地
- 指令非零結束碼、或 harness 回 `Exec failed` → **就是沒寫進去**,不得回報成功

**複查要對得上位址**:`fixindex find` 之後,確認命中的是 `appended`/`section` 指的那一條(比對 title 與 tags),不是語意相近的別條。對不上就是沒寫成功。

**跳脫地獄的解**:`printf` 內嵌 `\|`、`%`、巢狀引號極易讓整條指令掛掉。內容超過三行就先寫檔再 pipe:

```bash
cat /tmp/fi-entry.txt | fixindex fi
```
