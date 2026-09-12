# 任務：回填樹林住宅三份書表

> 狀態更新於 2026-09-12。勾選代表已完成並驗證過，不是「寫完程式」。
> 開工前先讀 `requirements.md`（範圍）與 `design.md`（格位與演算法）。

---

## 前置（已完成，這裡記錄以免重做）

- [x] **編樹林區普通住宅用地區域因素規則集**
      `kernel/rules/shulin_residential_regional.json`，29 個細項全數編碼，
      `check_ruleset()` 0 ERROR。附 17 個驗收測試，確認 116 格等級都判得動
      且重現 +23.50%／+14.75%／+14.75% 與三筆試算價格。
      `kernel` 測試從 90 增至 107 passed。
- [x] **修復本機環境**
      `parser/extract.py` 的模組層級型別別名改用 `Optional`，讓 Python 3.9 能
      import（原本 `str | None` 需要 3.10，導致 `parser`／`api`／`pdfform` 的測試
      在收集階段就中斷）。搭配 `VALUATION_DOC_DIR` 後完整測試 180 passed。
- [x] **量測三份 xlsx 的格位對映**
      結果寫在 `design.md` 第 3 節，全部用 `openpyxl` 實測，不是從 PDF 推測。
- [x] **建立本 spec 三份文件**

## 進行中

- [ ] **建立表3 事實 JSON**
      `kernel/fixtures/shulin_survey_facts.json`。四個區段，每個欄位標註來源
      頁碼。這是整條鏈的唯一輸入，取代對話記憶。
      驗收：用它跑 `classify()` 能重現 116 格等級。

- [ ] **修正其他影響因素(8) 的處理**
      題目已預填「-」與 0.00，本案不參與計算，性質同使用分區／建蔽率／容積率。
      要改的地方：規則集加註記、`kernel/tests/test_shulin_residential.py` 目前
      餵「普通」給它（結果 0 是對的但填法與題目不同）。

- [ ] **`kernel/src/compute.py` 新增群組小計與表5-1 產出函式**
      `group_subtotals()` 與 `build_table5_1()`，見 `design.md` 第 6 節。
      不放 `api/review.py`（那會讓計算跑到 api 層，斷掉追溯鏈）。
      驗收：輸出 116＋87＋24＋3 格，每格帶依據字串。

- [ ] **新增 `xlsxform/` 模組**
      `layout.py`（格位對映）、`fill.py`、`formulas.py`、`write.py`。
      不 import `kernel/`，計算函式由 CLI 注入。
      四張表3 用 `copy_worksheet()` 產生，複製後要檢查格式是否失真。

- [ ] **表4 回填與前提標註**
      填 `J8`／`N8`／`R8`（區域因素調整百分率）、`R29` 到 `R32`。
      `D34` 全案備註寫明個別因素由地價查估單位辦理、試算價格以 0 計、
      權重為暫定值。備註文字見 `design.md` 第 5 節。

- [ ] **CLI 入口並驗證**
      一行指令重跑整條鏈。驗收兩件事：活版公式與定版數值一致；
      重現 +23.50%／+14.75%／+14.75% 與 170,337／161,577／206,885。
      完整測試維持 180 passed 以上。

- [ ] **commit 並更新 `.kiro/README.md`**
      那份目前寫著「specs 目前是空的」，要改成指向本 spec。

## 之後（不阻塞交件）

- [ ] **表3 的 PDF parser**
      目前最大的技術風險。驗收標準已經先做好了：要能從 `正式題目/題目.pdf`
      產出與人工核對的事實 JSON 完全一致的結果。
      `detect.py` 的 `_NAMES` 要加表3 與表5-1；`find_page` 遇到同一表多頁會拋
      `LookupError`，要改成收集全部並依區段編號區分。

- [ ] **xlsx 轉 PDF**
      本機沒有任何轉檔工具。兩條路：用 `reportlab` 自己畫版面（`pdfform/` 已有
      能力但版面是為金山的 PDF 寫的），或在有 Excel／Numbers 的地方另存。

- [ ] **`api/main.py` 依 `land_use` 選規則集**
      現在寫死 `DEFAULT_REGIONAL = "jinshan_commercial_regional"`。規則集已經
      有兩組，這是唯一會安靜給錯答案的地方。`parser/table5_2.py` 有解析
      `land_use`，但表5-1 的 parser 還不存在，所以有前置依賴。

- [ ] **補編住宅用地的內政部上限表**
      `kernel/rules/moi_caps_regional.json` 只有附件24 的商業用地那份。
      住宅用地不能套商業用地的欄位，所以樹林那組的合規性驗不了，
      `check_ruleset()` 對 29 項全發 WARN。那代表「合規尚未驗證」而不是
      「不予調整」。只影響 WARN 訊息的準確度，不影響任何交付物。

- [ ] **前端表格鍵名**
      `src/stores/case.ts` 與 `src/types/case.ts` 寫死 `表1`／`表5-2`，
      後端改回傳 `表3`／`表5-1` 之後會全部拿到 `undefined`，而首屏九成內容被
      `v-if="parsed"` 擋住，畫面會幾乎全空。約 30 分鐘的機械改名。

## 待向局處確認

1. **比較標的權重打平怎麼處理。** 標的2 與標的3 的調整百分率絕對值加總都是
   19.75%，作業手冊 p.57 沒有規定打平的處置。`similarity_and_weights()` 用
   `sorted()`，穩定排序會依輸入順序決定（標的2 拿較高 50%、標的3 拿普通 30%），
   不會崩但是安靜地選一個。手冊原文另註「惟需另配合蒐集資料可信度等綜合決定」，
   所以打平時本來就有人工判斷空間。
2. **要交的是 xlsx 範本那份還是題目 PDF 那份的表5-1。** 兩者列名寫法不同
   （例如 xlsx 寫「電業設施及公用氣體燃料設施之有無及接近程度」，題目 PDF 寫
   「變電所或高壓鐵塔、瓦斯槽之有無及接近程度」），而且題目 PDF 版多一列
   「修正差異數」，xlsx 版沒有。目前依「要回填的是 xlsx」的指示，以 xlsx 為準。
3. **「修正差異數」的定義**（只有題目 PDF 版的表5-1 有這一列）。
