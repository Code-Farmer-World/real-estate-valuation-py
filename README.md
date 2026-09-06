# real-estate-valuation-py

新北市 AI 黑客松「AI 輔助不動產估價案件審查」的**後端**。三個專案分工：

| 專案 | 內容 |
|---|---|
| `real-estate-valuation-py`（本專案） | 規則引擎 + 書表辨識 + API |
| `real-estate-valuation-doc` | 官方文件（PDF / docx）、計畫書 `PLAN.md` |
| `real-estate-valuation` | Vue 3 前端 |

分層規定：`kernel/` → `parser/` → `api/`，**kernel 不得反向依賴 parser / api**。
kernel 是純邏輯、零第三方依賴；PDF 解析屬 adapter，不能滲進 domain core。

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

## 啟動與驗證

### 1. 規則引擎重現官方答案

```powershell
cd kernel
python demo.py
```

會印出完整依據鏈與比對結果，五項官方答案全數相符：

```
個別因素合計 13.00%   絕對值加總 15.00%
試算價格 212,958      比準地比較價格 212,958      比準地地價 213,000
```

### 2. 辨識官方書表

先看一份 PDF 裡有哪些表：

```powershell
cd D:\SideProject\real-estate-valuation-py
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

再把表4 解成 JSON（`--provenance` 會一併輸出每個欄位的頁碼與座標）：

```powershell
python -m parser.cli "..\real-estate-valuation-doc\查估書表範本.pdf" 表4 --provenance
```

### 3. 測試

```powershell
cd D:\SideProject\real-estate-valuation-py
python -m pytest -q          # 全部：kernel 59 + parser 13 = 72 passed
python -m pytest kernel -q   # 只跑引擎
python -m pytest parser -q   # 只跑辨識
```

> 兩個子專案各有自己的 `conftest.py`。根目錄的把專案根放上 `sys.path`（提供 `parser` / `api` 套件），
> `kernel/conftest.py` 把 `kernel/` 放上（提供 `src`）。兩者不重疊，所以能一起跑。

### 4. API

**尚未實作。** 規劃的端點見 `../real-estate-valuation-doc/PLAN.md` Step 2：
`POST /api/parse`、`POST /api/compute`、`POST /api/review`、`GET /api/rulesets`。
完成後啟動方式會是：

```powershell
python -m uvicorn api.main:app --reload --port 8000
```

## 目錄

```
kernel/          規則引擎（純 Python 零依賴）
  rules/         規則資料 —— 唯一需要隨案件更換的東西
  src/           classify / matrix / compute / validate / ruleset
  golden/        官方已填範本作為測試答案
  demo.py        一鍵重現 + 依據鏈輸出
parser/          書表辨識層
  extract.py     PDF 文字層與框線抽取，只提供座標查詢原語
  detect.py      依標題判斷一頁是哪張表
  table4.py      表4 比較法調查估價表
  provenance.py  欄位級來源記錄
  cli.py         命令列入口
paths.py         外部文件位置（VALUATION_DOC_DIR）
```

## 目前進度

| 項目 | 狀態 |
|---|---|
| 規則引擎（個別因素 19 項、分級／查表／加總／價格／尾數） | ✅ 59 測試 |
| 規則引擎（區域因素 28 項） | ⚠️ 5/28 |
| 表4 辨識器 | ✅ 13 測試，facts 與 golden 逐項相符 |
| 表5-2 辨識器 | ⬜ 待做（需先造 fixture） |
| 表1 辨識器 | ⬜ 待做（最難：40 餘欄、圈選符號、等級前綴） |
| vision 備用路徑（掃描／壞字型 PDF） | ⬜ 待做 |
| API | ⬜ 待做 |
| 審查模式（逐格 diff + 賠償金差額） | ⬜ 待做 |

## 兩個寫程式時容易踩的坑

**1. 欄位定位只能靠框線與座標，不能靠文字順序。**
範本表4 的「9深度(M)」標籤在 y=149.1，它那一列的值（23 / 16 / 1.00%）在 y=145.8，
差 3.3pt；`pdftotext -layout` 會把這種偏移印成串行。全域 y 分群也不行——
最小列距 3.3pt 與相鄰列距 6.6pt 太接近，任何單一容差都會切錯或併錯。
正確做法：用標籤定位該列的 y，再依欄位 x 區間取值（`parser/extract.py`）。

**2. 分欄要用「單一邊最大跨距」，不能用累計長度。**
同一條欄界常被畫成多個 rect，累計後會和被畫很多次的欄內子分隔線混在一起。
範本表4 實測：欄界最小跨距 247pt、欄內子分隔線最大 105pt，用跨距 ≥200 分得很開。
另外三張表的畫法不同——表1 / 表4 有 line 物件（96 / 164 條），
**表5-2 一條 line 都沒有、只有 140 個 rect**，所以兩者都要收。
