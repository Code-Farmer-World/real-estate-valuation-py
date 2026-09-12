# 技術棧與啟動方式

這個 workspace 有**兩個獨立執行的程式**，各有自己的語言與埠號，靠 HTTP 溝通。
兩者可以分開啟動，也可以只開其中一個。

```
前端  Vite dev server（Node.js）  :5173   顯示畫面
後端  uvicorn（Python）            :8000   解 PDF、算數字
```

前端唯一知道後端的方式是 `real-estate-valuation-main/.env.development` 裡的
`VITE_API_URL=http://localhost:8000`。

---

## 前端 `real-estate-valuation-main/`

Vue 3.5 + TypeScript 6 + Vite 8，Pinia 4 管狀態，vue-router 5 做路由，
axios 打 API。測試用 Vitest 5 與 Playwright。Lint 用 oxlint + eslint，
格式用 oxfmt。

### ⚠️ node 與 npm 不在系統 PATH 上

沒有 nvm、沒有 homebrew node。可攜式 Node.js（v22.18.0）放在專案內的
`.tools/`，**每次開新終端機都必須先設 PATH**，否則 `npm` 會因為 shebang
找不到 node 而失敗：

```bash
cd real-estate-valuation-main
export PATH="$PWD/.tools/bin:$PATH"
```

`package.json` 的 `engines` 要求 `^22.18.0 || >=24.12.0`，`.tools` 內的版本符合。

### 指令

```bash
npm run dev          # 開發伺服器 :5173（長時間執行，需獨立終端機）
npm run build        # type-check + 建置
npm run type-check   # vue-tsc --build
npm run test:unit    # vitest（watch 模式）
npx vitest run       # vitest 單次執行
npm run test:e2e     # playwright（需先裝瀏覽器，見下）
npm run lint         # oxlint + eslint，會自動修
npm run format       # oxfmt src/
```

### 已知環境問題

- **Playwright 瀏覽器未安裝。** 要跑 e2e 需先 `npx playwright install chromium`
  （下載約 150MB+）。`playwright.config.ts` 會自動啟動 dev server，不用自己開。
- **`npm run type-check` 檢查不到 `e2e/`。** `tsconfig.json` 的 references 只
  包含 node / app / vitest 三個，不含 `e2e/tsconfig.json`。要檢查 e2e 得另外指定：
  `npx tsc --noEmit -p e2e/tsconfig.json`

---

## 後端 `real-estate-valuation-py-main/`

FastAPI + uvicorn，PDF 辨識用 pdfplumber，產表用 reportlab。Python 3.13.7，
虛擬環境在專案內的 `.venv/`。

### ⚠️ 換機器時先確認這幾件事（2026-09-12 實測並修復）

這份文件其餘部分描述的是原始開發機。實際在別台機器上跑之前先確認，不要假設
環境相同。以下是 2026-09-12 在另一台機器上遇到的差異，以及已經做的修復。

| 項目 | 原始開發機 | 2026-09-12 這台 | 狀態 |
| --- | --- | --- | --- |
| 後端資料夾名 | `real-estate-valuation-py-main` | `real-estate-valuation`＋`-py` | hook 已改成兩種都吃 |
| 前端資料夾名 | `real-estate-valuation-main` | `real-estate-valuation` | 同上 |
| `.venv` 的 Python | 3.13.7 | **3.9.6**（Command Line Tools） | 已相容，見下方第 1 點 |
| `docs/` 在哪 | 後端 repo 內 | workspace 外層 | 用 `VALUATION_DOC_DIR` 指過去 |
| 完整測試 | 163 passed | **180 passed** | 已修復 |

**這台機器目前的跑法**（兩件事都要做，缺一個就會失敗）：

```bash
cd real-estate-valuation-py
export VALUATION_DOC_DIR="$(cd ../docs/official/real-estate-valuation && pwd)"
.venv/bin/python -m pytest -q      # 180 passed，約 24 秒
```

`VALUATION_DOC_DIR` 是 `paths.py` 提供的覆寫點。官方 PDF 被根目錄 `.gitignore`
的 `*.pdf` 排除（約 103MB），全新 clone 之後 `parser` 與 `pdfform` 的測試會
因為找不到「查估書表範本.pdf」而失敗，設這個變數指向文件實際位置即可。

1. **Python 3.9 的相容性已處理。** `parser/extract.py` 原本有三個模組層級型別
   別名寫成 `str | None`，那是 3.10 才支援的執行期求值，而模組層級賦值在 import
   時就執行，`from __future__ import annotations` 不保護那裡。結果是整個 `parser`
   無法 import，`api` 與 `pdfform` 的測試在收集階段就以 `TypeError` 中斷。已改用
   `typing.Optional`，語意等價、3.13 行為不變。**之後寫程式若要加模組層級的型別
   別名，記得用 `Optional[X]` 而不是 `X | None`。** 函式註解不受此限。
2. **requirements.txt 不能直接裝。** `fastapi==0.141.1` 需要 3.10 以上，整包會
   失敗而且什麼都不會裝。這台機器實際裝的是相容版本：`fastapi 0.128.8`、
   `reportlab 4.5.1`、`uvicorn 0.39.0`、`httpx 0.28.1`、`pytest 8.4.2`、
   `openpyxl 3.1.5`。**沒有改 requirements.txt**，因為那份記錄的是 3.13 環境的
   正確版本，不該為了單一台機器降版。
3. **本機沒有任何 xlsx 轉 PDF 的工具。** LibreOffice、Excel、Numbers、pandoc、
   weasyprint、wkhtmltopdf 全部沒有。要把填好的 xlsx 交成 PDF，得在有 Excel、
   Numbers 或 Google Sheets 的地方另存，或改用 `reportlab` 自己畫版面。
4. **要讀 xlsx 而沒有 `openpyxl` 時**，xlsx 本身是 zip 加 XML，`zipfile` 搭
   `xml.etree.ElementTree` 就能讀。用 regex 解析 sheet XML 會因為自閉合的 `<c/>`
   標籤與回溯而出錯，2026-09-12 實測踩過。

### 指令

一律用 venv 內的 python，不要用系統或 conda 的：

```bash
cd real-estate-valuation-py-main

# 啟動 API（長時間執行，需獨立終端機）
.venv/bin/python -m uvicorn api.main:app --reload --port 8000

# 測試
.venv/bin/python -m pytest -q            # 全部 163 passed，約 100 秒
.venv/bin/python -m pytest kernel -q     # 引擎  90 passed，0.5 秒
.venv/bin/python -m pytest api -q        # 介面  20 passed，23 秒
.venv/bin/python -m pytest parser -q     # 辨識  44 passed，26 秒
.venv/bin/python -m pytest pdfform -q    # 產表   9 passed，31 秒

# 不啟動服務就辨識一份 PDF（回歸比對很好用）
.venv/bin/python -m parser.cli "../docs/official/real-estate-valuation/查估書表範本.pdf"
.venv/bin/python -m parser.cli <pdf> 表4 --provenance

# 產出三張填好的書表（PDF，金山範本那條路）
.venv/bin/python -m pdfform.cli <pdf> <輸出目錄>

# 回填官方 xlsx 空白範本（樹林住宅那條路，2026-09-12 新增）
.venv/bin/python -m xlsxform.cli --templates <範本目錄> --out <輸出目錄>
```

`xlsxform.cli` 產出五個檔案：表3 一份（四張工作表，一個區段一張）、
表5-1 與表4 各有活版（含 Excel 公式）與定版（純數值）。範本目錄指向官方三份
空白 xlsx 所在的位置，那些檔案被根目錄 `.gitignore` 的 `*.xlsx` 排除，
不在版控裡。`xlsxform` 的測試找不到範本時會整份 skip，可用環境變數
`SHULIN_TEMPLATE_DIR` 指定位置。

**只有 `kernel` 快到適合綁存檔 hook**（純邏輯零依賴）。其他三個都要實際解析
PDF，每次 20–30 秒。

### 官方文件路徑

後端預設從 `docs/official/real-estate-valuation/` 讀取官方 PDF，位置定義在
`paths.py`，可用環境變數 `VALUATION_DOC_DIR` 覆寫。

⚠️ **這些 PDF 不在版控裡**（約 103MB，見根目錄 `.gitignore`）。全新 clone 之後
`parser` 與 `pdfform` 的測試會因為找不到「查估書表範本.pdf」而失敗，需自行補檔。
`kernel` 與 `api` 的測試不受影響。

---

## 測試與驗證慣例

改完程式一定要跑對應的測試，不要只靠「沒有報錯」當成功依據：

| 改動範圍 | 至少要跑 |
| --- | --- |
| `kernel/` | `pytest kernel -q` |
| `xlsxform/` | `pytest xlsxform -q`，並用 `xlsxform.cli` 對範本實際產一次 |
| `parser/` | `pytest parser -q`，並用 `parser.cli` 對範本實際跑一次 |
| `pdfform/` | `pytest pdfform -q` |
| `api/` | `pytest api -q` |
| 前端 `src/` | `npm run type-check` + `npx vitest run` |
| 前端 `e2e/` | `npx tsc --noEmit -p e2e/tsconfig.json` |

跨層改動或不確定影響範圍時，跑後端全部 163 個 + 前端全部。

---

## 終端機注意事項

- **不要用 execute_bash 跑長時間執行的程序**（dev server、uvicorn --reload、
  watch 模式），會卡住。這些請使用者自己開終端機跑。
- 這個環境的 `cwd` 參數可能不生效，工具會自己 `cd` 回 workspace 根目錄。
  **一律用絕對路徑，或在指令裡自己接 `cd`。**
- 回傳的 exit code 不可靠（成功也可能回 1），要看實際輸出判斷。
- 長輸出容易被截斷，先寫檔再讀比較可靠。
- **殼是 zsh，內建 `echo` 預設會解釋反斜線轉義。** 檢查含字面 `\n` 的輸出（例如
  hook 產生的 JSON）時不要用 `echo "$out"`，它會把 `\n` 印成真換行，看起來像
  無效 JSON。改用 `printf '%s'` 或直接管線給下一個程式。2026-09-12 為此誤判過
  兩輪，以為 hook 產出的 JSON 壞了。
- **`eval "$cmd"` 若 `$cmd` 結尾有 `exit 0`，會結束整個 script**，後面的指令
  不會執行。測 hook 的 command 時用 `bash -c "$cmd"` 包在子行程裡跑。
