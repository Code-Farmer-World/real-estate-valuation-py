# real-estate-valuation-py

新北市 AI 黑客松「AI 輔助不動產估價案件審查」的**後端**。三個專案分工：

| 專案 | 內容 |
|---|---|
| `real-estate-valuation-py`（本專案） | 規則引擎 + 書表辨識 + API |
| `real-estate-valuation-doc` | 官方文件（PDF / docx）、計畫書 `PLAN.md` |
| `real-estate-valuation` | Vue 3 前端 |

分層規定：`kernel/` → `parser/` → `api/`，**kernel 不得反向依賴 parser / api**。
kernel 是純邏輯、零第三方依賴；PDF 解析屬 adapter，不能滲進 domain core。
api 只做 JSON 進出與檔案接收，**沒有任何計算邏輯**——demo 的主論述是
「每個數字都能指回官方文件」，API 層一旦自己算，追溯鏈就斷在那裡。

## 前置

- **Python 3.14**（實測 3.14.7）
- **官方文件目錄**。文件不在這個 repo 裡（唯讀證據、共 80MB、比賽當天會換檔），
  預設從並存的 `../real-estate-valuation-doc` 讀取。放在別處時設環境變數：

  ```powershell
  $env:VALUATION_DOC_DIR = "D:\path\to\docs"
  ```

## 安裝

```powershell
cd D:\SideProject\real-estate-valuation-py
python -m pip install -r requirements.txt
```

`kernel/` 不需要任何套件就能跑；`requirements.txt` 裡的都是 `parser/` 與 `api/` 用的。

## 啟動

### 1. 啟動 API

```powershell
cd D:\SideProject\real-estate-valuation-py
python -m uvicorn api.main:app --reload --port 8000
```

確認活著：

```powershell
curl http://127.0.0.1:8000/api/health
# {"data":{"status":"ok","doc_dir":"D:\\SideProject\\real-estate-valuation-doc"},"error":null}
```

互動式文件在 <http://127.0.0.1:8000/docs>。前端把 `VITE_API_URL` 指到
`http://localhost:8000` 即可（CORS 已開 `localhost:5173` / `127.0.0.1:5173`）。

端點：

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/api/health` | 存活檢查，順便回報文件目錄位置 |
| GET | `/api/rulesets` | 可用規則集（demo 現場抽換基準表用） |
| POST | `/api/parse` | 上傳查估書表 PDF → 三張表的辨識結果 + provenance |
| POST | `/api/compute` | 依規則集重算表4 全鏈路 + 依據鏈 |
| POST | `/api/review` | 審查模式：三層逐格比對 + 賠償金差額 |

**回應格式是固定的信封** `{"data": …, "error": …}`，二擇一，錯誤回應也一樣。
這是配合前端既有的 `axiosService.ts` 攔截器，完整契約見 [api/CONTRACT.md](api/CONTRACT.md)。

### 2. 不啟動服務，直接用命令列辨識

```powershell
python -m parser.cli "..\real-estate-valuation-doc\查估書表範本.pdf"
```

```
p1  表1
p2  表5-2
p3  表4
p4  （非書表：圖或其他）
p5  （非書表：圖或其他）
p6  （非書表：圖或其他）
```

```powershell
python -m parser.cli "..\real-estate-valuation-doc\查估書表範本.pdf" 表4 --provenance
```

### 3. 規則引擎重現官方答案

```powershell
cd kernel
python demo.py
```

```
個別因素合計 13.00%   絕對值加總 15.00%
試算價格 212,958      比準地比較價格 212,958      比準地地價 213,000
```

### 4. 測試

```powershell
cd D:\SideProject\real-estate-valuation-py
python -m pytest -q          # 全部：117 passed
python -m pytest kernel -q   # 引擎  59
python -m pytest parser -q   # 辨識  43
python -m pytest api -q      # 介面  15
```

> 兩個子專案各有自己的 `conftest.py`。根目錄的把專案根放上 `sys.path`（提供 `parser` / `api` 套件），
> `kernel/conftest.py` 把 `kernel/` 放上（提供 `src`）。兩者不重疊，所以能一起跑。

## 目錄

```
kernel/          規則引擎（純 Python 零依賴）
  rules/         規則資料 —— 唯一需要隨案件更換的東西
  src/           classify / matrix / compute / validate / ruleset
  golden/        官方已填範本作為測試答案
  demo.py        一鍵重現 + 依據鏈輸出
parser/          書表辨識層
  extract.py     PDF 文字層、框線與 cell 網格抽取
  detect.py      依標題判斷一頁是哪張表
  table1.py      表1 地價區段勘查表（28 個細項的等級與量測值）
  table5_2.py    表5-2 影響地價區域因素分析明細表（28 細項 + 8 小計 + 總修正數）
  table4.py      表4 比較法調查估價表（19 個個別因素 + 價格鏈）
  provenance.py  欄位級來源記錄
  golden/        表5-2 的期望值 fixture
  cli.py         命令列入口
api/             FastAPI 薄殼
  main.py        端點
  envelope.py    回應信封與錯誤改寫
  review.py      三層審查比對
  kernel_api.py  接進 kernel 的唯一入口
  CONTRACT.md    介面契約（以前端 axiosService.ts 為準）
paths.py         外部文件位置（VALUATION_DOC_DIR）
```

## 目前進度

| 項目 | 狀態 |
|---|---|
| 規則引擎（個別因素 19 項、分級／查表／加總／價格／尾數） | ✅ 59 測試 |
| 表4 辨識器 | ✅ facts 與 golden JSON 逐項相符 |
| 表5-2 辨識器 | ✅ 28 細項 + 8 群組小計 + 總修正數 |
| 表1 辨識器 | ✅ 28 細項的等級／級數／量測值 |
| API（parse / compute / review / rulesets） | ✅ 15 測試，端到端 212,958 / 213,000 |
| 審查模式三層比對 | ✅ 第二、三層完整；第一層受限於規則集 |
| 規則引擎（區域因素 28 項） | ⚠️ 5/28，所以審查第一層只查得動 5 項 |
| vision 備用路徑（掃描／壞字型 PDF） | ⬜ 待做 |
| 表6 徵收土地宗地市價估計表 | ⬜ 待做（賠償金真正的出口） |

**誠實記錄**：`/api/review` 會把查不動的項目列在 `not_checkable` 並說明原因
（目前 23 項，因為區域因素規則集只補到 5/28）。不會靜靜跳過然後顯示「全部通過」。

## 五個寫程式時容易踩的坑

全部是實測踩到的，也都寫成了測試。

**1. 欄位定位只能靠框線與座標，不能靠文字順序。**
範本表4 的「9深度(M)」標籤在 y=149.1，它那一列的值（23 / 16 / 1.00%）在 y=145.8，
差 3.3pt；`pdftotext -layout` 會把這種偏移印成串行。全域 y 分群也不行——
最小列距 3.3pt 與相鄰列距 6.6pt 太接近，任何單一容差都會切錯或併錯。

**2. 分欄要用「單一邊最大跨距」，不能用累計長度。**
同一條欄界常被畫成多個 rect，累計後會和被畫很多次的欄內子分隔線混在一起。
範本表4 實測：欄界最小跨距 247pt、欄內子分隔線最大 105pt。
另外三張表的畫法不同——表1 / 表4 有 line 物件（96 / 164 條），
**表5-2 一條 line 都沒有、只有 140 個 rect**，所以兩者都要收。

**3. 座標與 cell 網格兩種取值方式都要留。**
表4 用座標（欄內有子分隔線，摘要列與資料列排版不同）；
表5-2 與表1 用網格（細項名折成 2–3 行，值落在中間那一行）。
硬要統一成一種，另一張表就會爛掉。

**4. 表1 的等級可能落在標籤的下一列。**
跨列儲存格的文字畫在垂直置中處，會被切到相鄰網格列——
「市場」標籤在 r31、等級在 r32；「廢棄物處理」標籤在 r18、等級在 r19。
而且同一列左右面板各有一組等級（r14 左邊交流道 5/5、右邊殯葬 5/5），
取值必須分面板。

**5. 級數不一定是 5。**
都市計畫內外、有無禁止建築、有無限制建築都是 **2 級**。
把 5 寫死會讓這三項的等級語意整個錯掉。

## 一個已知的合規缺口

金山區商業用地個別因素「道路種類」自訂表最大修正幅度 **8%**，
超出內政部附件25 規定的商業用地上限 **5%**。

validator 只發 WARN、**不自動修正**——因為 Golden Case 的 +2.00% 正是用
超標的 step=2.0 算出來的，自動夾到 5% 會變成 +1.25%，反而重現不出官方答案。
合規問題應回報地政局，不是偷偷改數字。細節見 [kernel/README.md](kernel/README.md)。
