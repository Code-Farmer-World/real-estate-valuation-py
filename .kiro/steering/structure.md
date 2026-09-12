# 專案結構與分層界線

前後端是兩個獨立的 repo。這份講後端，前端結構見下方。

```
real-estate-valuation-py/            後端（本 repo）
├── .kiro/                           steering、hooks
├── docs/
│   ├── ROBUSTNESS_AUDIT.md          穩健性稽核與調整點索引，先看這份
│   ├── official/                    官方書表、評價基準、作業手冊（不進版控）
│   ├── workshops/                   工作坊教材
│   └── reference/aws/               AWS Well-Architected
├── kernel/  parser/  pdfform/  api/ 四層，見下方分層界線
├── xlsxform/                        回填官方 xlsx 範本（2026-09-12 新增）
└── stress/                          壓力測試

real-estate-valuation/               前端（另一個 repo）
```

⚠️ **上面是完整型態，實際 checkout 可能少東西。** 2026-09-12 實測某台機器的後端
repo 只有 `api/ kernel/ parser/ pdfform/ paths.py conftest.py requirements.txt`，
沒有 `docs/`（在 workspace 外層）也沒有 `stress/`，而 `.kiro/` 只存在於 remote
分支 `origin/morefoodq/hackathon-2026-09-11-rebased` 而沒有進 `main`。動手前先
`list_directory` 確認，`.kiro/` 若不在工作目錄可用
`git restore --source=<有它的 ref> -- .kiro` 取回。競賽規範 C6 要求 `/.kiro`
必須在專案根目錄，這件事會影響交件資格，見 `competition.md`。

---

## 前端

```
src/
├── main.ts              入口：createApp → use(pinia) → use(router) → mount('#app')
├── App.vue              只有 <RouterView />，但全域 CSS 變數定義在這裡
├── router/index.ts      只有一個路由：'/' → HomeView
├── views/
│   └── HomeView.vue     唯一的頁面，所有畫面都在這
├── components/
│   ├── Table1Panel.vue      地價區段勘查表
│   ├── Table52Panel.vue     區域因素分析明細表
│   ├── Table4Panel.vue      比較法調查估價表，可點格子
│   └── EvidencePanel.vue    依據面板，顯示後端算好的依據鏈
├── stores/case.ts       Pinia store：一次上傳串三支 API
├── services/
│   ├── axiosService.ts      通用層：baseURL、攔截器、{data,error} 信封解析
│   └── valuationService.ts  端點與型別定義
├── types/case.ts        後端回傳資料的型別
└── composables/useLogger.ts
```

### 幾個關鍵事實

- **整個系統只有一個路由。** 沒有登入頁、列表頁、詳情頁，網址永遠是 `/`。
- **啟動時不打任何 API。** `src/` 裡沒有任何 `onMounted`，`store.analyze` 只在
  `HomeView.vue` 的 `onPick()` 與 `onDrop()` 被呼叫。後端關著畫面照樣正常出來。
- **首屏九成內容被 `v-if="parsed"` 關掉。** `parsed` 初始值是 `null`，那一大段
  template 不是隱藏，是根本沒有建立 DOM。
- **全域配色在 `App.vue` 的非 scoped `<style>`。** `--accent`、`--ok`、`--bad`
  等 CSS 變數都在那裡，改視覺風格從這 20 行下手，不用動每個元件。
- `EvidencePanel.vue` **刻意不做任何運算**，只顯示後端算好的依據鏈。

---

## 後端

```
real-estate-valuation-py-main/
├── paths.py             官方文件路徑常數，可用 VALUATION_DOC_DIR 覆寫
├── api/                 FastAPI 薄殼
│   ├── main.py          entry point，app 定義在這；7 支端點
│   ├── envelope.py      {data, error} 回應信封與錯誤處理
│   ├── kernel_api.py    唯一接進 kernel 的入口
│   ├── review.py        三層逐格比對
│   └── CONTRACT.md      端點與回應格式規格
├── kernel/              規則引擎（純 Python 零依賴）
│   ├── src/
│   │   ├── ruleset.py   規則集載入
│   │   ├── classify.py  值 → 等級
│   │   ├── matrix.py    等級對 → 修正率
│   │   ├── compute.py   加總、尾數處理、全鏈路試算
│   │   └── validate.py
│   ├── rules/*.json     規則集（目前只有金山商業用地）
│   └── golden/          官方範本的期望答案
├── parser/              PDF 辨識
│   ├── extract.py       pdfplumber 包裝：Word / Page 資料結構與座標查詢
│   ├── detect.py        判斷一頁是哪張表
│   ├── table1.py        走網格
│   ├── table5_2.py      走網格，28 項 factor_id 的正本對照表在這
│   ├── table4.py        走框線座標
│   ├── survey.py        表1 量測值 → 可分級的值
│   ├── provenance.py    欄位來源（頁碼、bbox、原文）
│   └── cli.py           不啟動服務就辨識
└── pdfform/             產出填好的官方書表
    ├── forms.py         build_forms()，被 api/main.py 呼叫
    ├── template.py      值該畫在哪（用 provenance 的 bbox 當版面定義）
    ├── fill.py          每格要填什麼
    └── render.py        reportlab 畫成 PDF
```

### API 端點

| 方法 | 路徑 | 用途 |
| --- | --- | --- |
| GET | `/api/rulesets` | 列出可用規則集 |
| POST | `/api/parse` | 上傳 PDF → 辨識三張表 |
| POST | `/api/compute` | 重算表4 全鏈路 + 依據鏈 |
| POST | `/api/review` | 三層逐格比對 |
| POST | `/api/forms` | 產出三張書表，回傳下載連結 |
| GET | `/api/forms/{token}/{filename}` | 下載書表（回傳 PDF 本身，不走信封） |
| GET | `/api/health` | 健康檢查 |

---

## 分層界線（不要跨越）

```
parser/  ──→  api/  ──→  kernel/
   PDF 進來      只做 JSON      純計算
   座標抽取      進出與檔案      零依賴
                收發
```

- **`api/` 不做任何計算。** 一旦 API 開始自己算，「每個數字都指得回官方文件」
  的追溯鏈就斷在這一層。計算全部委派給 `kernel/`。
- **`kernel/` 零外部依賴，也不認識 PDF。** 輸入是 dict，輸出是 dataclass。
- **`pdfform/` 不 import `kernel/`。** 需要的計算函式（`appraise`、`classify`、
  `lookup`）由 `api/main.py` 以參數注入，相依方向由 api 決定。
- **`parser/survey.py` 刻意不 import kernel**，避免 pdfform 反向依賴 api。
- **`xlsxform/` 也不 import `kernel/`**，同 `pdfform/` 的理由。它接收已算好的
  結果（duck typing，只依賴介面不依賴型別），相依方向由 `xlsxform/cli.py` 決定，
  那是唯一同時知道兩邊的地方。

### `xlsxform/` 的內部分工

```
xlsxform/
├── layout.py     官方 xlsx 範本的格位對映。純資料無邏輯，全部是實測座標，
│                 附 check_layout() 自我檢查（它抓的是「對映表打錯了」）。
│                 讀與寫共用這一份，改一邊忘另一邊會被 round-trip 測試抓到
├── write.py      openpyxl 底層。只管怎麼把值放進格子而不弄壞範本，
│                 處理合併格導向主格、複製工作表、百分比存實際小數
├── read.py       反向：從填好的表3 xlsx 讀出勘查事實。含型別轉換、
│                 空值正規化、case_overrides 的套用
├── formulas.py   活版的 Excel 公式字串
├── fill.py       決定每一格填什麼。live=True 寫公式、live=False 寫數值
└── cli.py        串起 kernel 與 xlsxform，一行指令跑完整條鏈
```

`read.py` 與 `write.py` 對稱，共用 `layout.py`。不另開一個套件放讀取，
因為那份格位對映會變成有兩個使用者卻沒有共同歸屬，容易改一邊忘另一邊。

`read.py` 輸出的是統一的勘查事實格式，與 `kernel/fixtures/*.json` 的 `segments`
區塊同一個 schema。三種輸入格式（PDF、xlsx、未來的 OCR）都收斂到這一層。
現有 `parser/` 的 `Table1.surveys` 就是同一件事，只是包裝不同，要接進來需要一個
攤平的轉接函式。

`raw` 與 `facts` 分開，`extras` 放不是評價細項但回填需要的附屬資訊
（路名、土地改良勾選項目）。少了 `extras` 會掉字：reader 產出的 `raw` 是型別
轉換後的數值，解析不出路名，第二次產出時那幾格會變空白（實測踩過）。

分界線是「判斷 vs 運算」：優劣等級與修正百分比要翻基準表的級距與 5×5 矩陣並附
依據，只能由 `kernel/` 算並寫成數值；加總、乘法、加權是機械運算，寫成 Excel
公式讓局處填入個別因素後自動更新。權重兩版都寫數值，因為它含排序分級的判斷。

## 資料流

```
使用者拖入 PDF
  └─ HomeView.onPick/onDrop
      └─ store.analyze(file)                    stores/case.ts
          ├─ parseForms(file)   POST /api/parse    → parsed
          ├─ compute(tables)    POST /api/compute  → computed
          └─ review(tables)     POST /api/review   → reviewed
              ↓ 三者共用同一份 tables，所以在 store 串起來，畫面只等一個 loading
          畫面 v-if="parsed" 成立，三張表與審查結果才渲染
```

產表是**分開觸發**的（`store.makeForms()`），因為要花幾秒，而多數時候使用者
只想看審查結果。書表必須從同一份原始檔產生，所以 store 留了 `sourceFile`。
