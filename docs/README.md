# 文件目錄

專案文件與官方參考資料。程式在上一層各模組目錄，前端在
[`real-estate-valuation`](https://github.com/MoreFoodQ/real-estate-valuation)。

## 先看這一份

- **`DEMO.md`**：可以對外講的特色與 Demo 腳本。每一條都附「怎麼當場驗證」，
  沒有話術。含三個特色、刻意不做的事、照著操作的流程、會被問到的問題與答案、
  數字速查表。錄影片或現場說明前看這一份。
- **`ARCHITECTURE.md`**：架構決策的對外敘述。確定性與適應性的權衡、
  四層結構與各層的變動成本、確定性的定義、刻意不做的事（不用模型算數字、
  不接地圖 API 算距離）、擴充路徑、人機分工。同樣每條都附驗證方式。
- **`FILLING-BASIS.md`**：填表依據逐條對照。每一格填什麼、為什麼那樣填、
  依據哪一條手冊條文，含三處官方文件不一致的取捨與還沒讀完的部分。
  跟主辦方對答案時看這一份。
- **`ocr/新北查估書手冊-OCR.md`**：新北市手冊 93 頁全文 OCR。
  那份手冊的內文字型抽不出文字，這是用 macOS Vision 辨識的結果，
  用途是定位與搜尋，引用條文要回去看原始 PDF 的圖。
  重新產生用 `python scripts/ocr-manual.py`。


- **`ROBUSTNESS_AUDIT.md`**：穩健性稽核。壓力測試結果、寫死與彈性規則的完整盤點、
  風險清單與修正優先序、格式變異的實測行為，以及症狀對照的調整點索引。
  改 `parser/` 之前先看第 4 與第 10 節。

技術立場與已知限制寫在 `../.kiro/steering/decisions.md`。

## 分類

- `official/real-estate-valuation/`：估價系統使用的官方書表、評價基準與作業手冊
- `workshops/`：工作坊教材
- `reference/aws/`：AWS Well-Architected 參考資料

⚠️ **憑證不入庫**：Access Key、API Token 等一律不寫入任何檔案，
需要時直接貼進終端機。根目錄 `.gitignore` 已排除 `*.local.md` 與 `*.local`
作為後備防線。

⚠️ **官方 PDF 不在版控裡**（約 103MB，見根目錄 `.gitignore`）。全新 clone 之後
`parser` 與 `pdfform` 的測試會因為找不到「查估書表範本.pdf」而失敗，需自行補檔。
`kernel` 與 `api` 的測試不受影響。

後端預設從 `official/real-estate-valuation/` 讀取官方文件；若部署環境使用其他
位置，請設定 `VALUATION_DOC_DIR`。規則引擎實際計算使用的是 `kernel/rules/*.json`，
官方 PDF 是來源與驗證文件。
