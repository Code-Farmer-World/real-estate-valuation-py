# 設計：匯入填好的勘查表 xlsx

---

## 1. 三種輸入格式收斂到同一層

```
匯入（依檔案類型分流）
├─ PDF（有文字層）   parser/            靠座標，綁版面     現況：金山可用、新版面報錯
├─ xlsx              xlsxform/read.py   靠格位，結構化     本 spec 要做的
└─ 圖片／掃描 PDF    （未來 Textract）  OCR                現況：無
                          ↓
              統一的勘查事實格式
        {segments: {區段: {raw, facts, segment_range, source}}}
                          ↓
              kernel（判級、查矩陣、加總、算價格）
                          ↓
        xlsxform（回填 xlsx）／pdfform（產 PDF）
```

這一層的價值有三個。`kernel` 完全不必知道資料從哪來，它只認
`{factor_id: 值}`。三個 reader 互相獨立，PDF 那條壞掉不影響 xlsx 那條。
三者共用同一套驗收標準，就是 `kernel/fixtures/shulin_survey_facts.json`
那份人工核對過的答案。

現有 `parser/` 的輸出是 `Table1(period, segment_no, segment_scope, grades,
surveys, ...)`，其中 `surveys` 存的就是量測值，與統一格式的 `facts` 是同一件事，
只是包裝不同。要接進來需要一個攤平的轉接函式，那不在本 spec 範圍，
但格式先定好，之後接不必再改。

## 2. 模組位置

放在 `xlsxform/read.py`，與 `write.py` 對稱，共用 `layout.py`。

不另開一個 `xlsxreader/` 套件，因為讀與寫依賴的是同一份格位對映，分開放會讓
那份對映有兩個使用者卻沒有共同歸屬，容易改一邊忘另一邊。

`read.py` 與 `write.py` 一樣不 import `kernel/`。它輸出普通 dict，
由 `cli.py` 交給 `kernel`。

## 3. 工作表的辨識

一個工作表一個地價區段。兩種來源都要吃：

| 來源 | 工作表名稱 | 區段編號怎麼取 |
| --- | --- | --- |
| `xlsxform` 產出的 | `表3 P001-00` | 從名稱用正則 `P\d{3}-\d{2}` 抓 |
| 官方空白範本 | `表3區段勘查表` | 從格子 `G3` 讀 |

優先用名稱，抓不到就讀 `G3`，兩者都沒有就報錯（不猜）。

隱藏工作表一律跳過（官方範本每個檔案有 23 張隱藏的舊範本樣例，
內容是 ○○鄉／甲一／乙二 這類佔位資料，不是本案資料）。

## 4. 格位對映（沿用 `layout.py`）

表3 有兩種佈局，讀取與寫入用同一組常數：

```
佈局 A（第 4 到 9 列）   標籤 D:G，值 H:K   TABLE3_VALUE_CELLS_A
佈局 B（第 23 到 30 列） 標籤 D:H，值 I:K   TABLE3_VALUE_CELLS_B
特例                     G11 路名、J11 寬度、G12 平均寬度
                         E31／E32 土地改良勾選（□→■）
                         R42 建築密度、R43 建築型態（Q42／Q43 是印好的標籤）
                         Q44 土地利用現況（○→●）
                         B3 年期、G3 區段編號、L3 區段範圍
```

Q42／Q43 是範本印好的欄位名，值欄在右邊的 R42:V42 與 R43:V43。
先前誤把值寫進 Q 欄，把標籤蓋掉了，逐格盤點產出檔案時才發現。

勾選類欄位一律成對實作：寫入端把符號換掉，讀取端用 regex 抓回來。
少了讀取端，round-trip 會把勾選弄丟（土地改良與土地利用現況都踩過）。

`TABLE3_PERCENT_FIELDS` 從 `fill.py` 搬到 `layout.py`，讓寫入與讀取共用。
先前那份清單只有寫入端在用，讀取端若自己再寫一份，兩邊會不同步。

## 5. 型別轉換

```python
def _to_percent(value):   # "50%" 或 0.5 或 50 → 50
def _to_number(value):    # "28" 或 28 或 28.0 → 28（int 優先）
def _to_text(value):      # 去空白，空字串視為 None
def _is_absent(value):    # None、""、"○"、"-"、"－" → True
```

百分比要特別小心三種來源：

| xlsx 儲存的 | 顯示 | 轉換後 |
| --- | --- | --- |
| 字串 `"50%"` | 50% | 50 |
| 數值 `0.5` 加百分比格式 | 50% | 50 |
| 數值 `50` 無格式 | 50 | 50 |

判斷依據是儲存格的 `number_format` 含不含 `%`。若是數值且格式含 `%`，
乘 100；若是字串結尾有 `%`，去掉再轉數字；否則原樣當數值。

⚠️ 這裡有個不能自動判斷的邊界：數值 `0.5` 而格式**不含** `%` 時，
無法區分「0.5 個百分點」與「50% 被存成小數但格式掉了」。這種情況要報錯而不是猜。
實務上不會遇到（我們自己產出的檔案一定帶格式），但別人手填的檔案可能。

## 6. 土地改良的勾選數

範本印的是 `□整平或填挖基地　□開挖水溝　□水土保持　□鋪築道路`（第一行）與
`□埋設管道　　　　□修築駁嵌　□其他＿＿＿＿＿＿`（第二行），勾選後變 `■`。

讀取就是數 `■` 的個數。已有 `fill.checked_improvements()` 在做這件事
（用 `re.findall(r"([■□])([^■□]*)")` 在每個標記前斷開），read 端直接複用。

⚠️ 不要只依 `■` 切割字串。實測踩過：`"■開挖水溝 □水土保持"` 會被當成一個項目名，
四項只認到兩項。

## 7. `case_overrides`

案件層級的覆寫，說明「勘查表上寫的」與「計算要用的」為什麼不同。

```json
"case_overrides": [
  {
    "factor_id": "regional.land_control.floor_area_ratio",
    "applies_to": "all_segments",
    "value": 200,
    "source": "地價查估單位口頭指示（2026-09-12 工作坊）",
    "reason": "比較標的跟比準地的道路如果沒有到達八米，容積就不能到達 200 以上。這個專案內都是八米內，所以容積一律使用 200 計算。",
    "note": "勘查表原載 P001-00／P003-00／P004-00 為 260%、P002-00 為 200%，原值保留在各區段的 raw。四區段同值故修正率為 0，且容積率本來就不計入區域因素小計。"
  }
]
```

套用順序：

```
xlsx → raw（忠實記錄勘查表）
     → 套用 case_overrides → facts（計算用）
```

`applies_to` 目前只支援 `"all_segments"` 與具體的區段編號清單。不做更複雜的
條件式，因為那會變成在資料裡寫程式。

三個設計約束：

1. **不能寫進 `read.py`。** 那只負責讀檔案，不認識業務規則。
2. **不能寫進 `kernel/`。** 那是規則引擎，只認識評價基準，不認識個案特例。
3. **必須留下追溯。** `raw` 保留原值，覆寫要說明來源與理由。徵收案會被訴願，
   「為什麼容積率用 200 不用 260」必須答得出來。

## 8. 驗收：round-trip

```
fixtures 的 facts
      ↓ xlsxform.write（已完成）
表3 xlsx（四張工作表）
      ↓ xlsxform.read（本 spec）
讀回來的 facts
      ↓ 比對
除 case_overrides 涵蓋的細項外，必須完全一致
```

容積率是唯一例外：寫入時 `raw`（260）進 xlsx，讀回來得到 260，套用
`case_overrides` 後才變 200。所以比對要分兩層：

- `raw` 讀回來 == fixtures 的 `raw`（容積率 260）
- `facts` 套用覆寫後 == fixtures 的 `facts`（容積率 200）

## 9. 錯誤處理

要分得開的三種情況：

| 情況 | 行為 |
| --- | --- |
| 細項未勾選（本案 13 項） | `facts[fid] = None`，正常，下游由 `absent` 級距處理 |
| 格位讀不到值但該有值 | 記入 `warnings`，不中斷 |
| 工作表缺區段編號、檔案沒有可辨識的工作表 | 拋錯，中斷 |

第二種刻意不中斷，因為不同用地類別的勘查表欄位本來就不同（住宅用地沒有工商
活動那組），硬要求每一格都有值會讓別的用地類別直接不能用。但要讓使用者看到
少了什麼，不能靜默。

## 10. CLI

```bash
# 從人工核對的 fixtures 跑（現有）
python -m xlsxform.cli --facts kernel/fixtures/shulin_survey_facts.json \
    --templates ../正式題目 --out <目錄>

# 從填好的表3 xlsx 跑（本 spec 新增）
python -m xlsxform.cli --from-xlsx <填好的表3.xlsx> \
    --templates ../正式題目 --out <目錄>

# 回填完整性盤點：逐列比對範本與產出，看哪些格動了、哪些沒動
python -m xlsxform.audit --templates ../正式題目 --out <上面的輸出目錄>
```

改動格位對映之後跑一次 `audit`，逐列確認「未動的格」是本案沒有這一項
而不是漏填。詳見 `.kiro/steering/decisions.md` 的「這個專案的錯誤分兩類」。

`--from-xlsx` 需要一份「案件設定」提供 xlsx 裡沒有的資訊：案號、比準地是哪個
區段、`case_overrides`、以及表4 已給的交易實例資料（正常單價、交易日期、
調整百分率）。那些不在勘查表上。

做法是沿用現有的 fixtures JSON 當設定檔，只是 `segments` 區塊改由 xlsx 提供。
兩個參數可以並用：`--facts` 給設定、`--from-xlsx` 給勘查事實。單獨用
`--from-xlsx` 時預設讀 `kernel/fixtures/shulin_survey_facts.json` 當設定。

這樣設計的好處是不必再定義一種新的設定檔格式，而且 round-trip 驗收天然成立。
