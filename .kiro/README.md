# .kiro

Kiro 在這個專案的使用紀錄。依 2026 新北市 AI 智慧城市黑客松競賽規範，
本資料夾必須存在於專案根目錄，且不得加入 `.gitignore`。

```
.kiro/
├── steering/     專案背景知識，每次對話自動載入
├── hooks/        事件觸發的自動化
└── specs/        功能開發紀錄（需求 → 設計 → 任務）
```

## steering/

每次與 Kiro 對話時自動帶入的專案知識。內容全部來自實際閱讀程式碼與
執行驗證，不是推測。

| 檔案 | 內容 |
| --- | --- |
| `product.md` | 這個系統在解什麼問題：土地徵收補償查估書表的三層審查。含核心設計主張與已知限制 |
| `tech.md` | 技術棧、啟動指令、各測試套件實測耗時，以及環境陷阱（node 不在 PATH、e2e 不在 type-check 範圍內） |
| `structure.md` | 目錄結構、API 端點、分層界線、完整資料流 |
| `competition.md` | 部署與資料的硬性限制：可用區域、服務白名單、模型限制、憑證處理、`/.kiro` 的交件要求 |
| `decisions.md` | 幾條不要越過的線：AI 不碰數字、不宣稱準確率、計算集中在 `kernel/`。含編新行政區規則集的八條紀律 |

`tech.md` 與 `structure.md` 記錄的環境陷阱是實際踩過才發現的，例如：

- `node` 與 `npm` 不在系統 PATH，可攜式 Node 在 `real-estate-valuation-main/.tools/`
- `npm run type-check` 檢查不到 `e2e/`，因為 `tsconfig.json` 的 references 沒包含它
- `kernel` 測試 0.5 秒，但 `parser` / `pdfform` / `api` 要 20–30 秒（都得真的解 PDF）

## hooks/

| 檔案 | 觸發 | 作用 |
| --- | --- | --- |
| `kernel-tests-on-save.json` | `PostFileSave`，比對 `kernel/**/*.{py,json}` | 跑規則引擎測試。選 kernel 是因為它只花 0.5 秒（純邏輯零依賴），而規則引擎是整個系統可信度的根基 |
| `guard-secrets-before-commit.json` | `PreToolUse`，比對 `execute_bash` | 檢查 staged 檔案是否疑似含憑證，命中則要求確認。競賽規範禁止上傳 Access Key 等憑證，而 `docs/competition/ACCESS.local.md` 存有競賽 Access Code |

第二個 hook 的比對規則刻意排除 `.kiro/`。實測發現不排除的話，
`guard-secrets-before-commit.json` 這個檔名本身就會命中 `secret` 而誤判，
把競賽強制要求上傳的資料夾攔下來。三項驗證：`.kiro/` 不誤判、
`ACCESS.local.md` 會被抓到、`.env.development`（只含 API 位址）正確略過。

### 2026-09-12 的修正

兩支 hook 原本都無法在換過的機器上運作，一併修掉並重跑上述三項驗證。

1. **路徑寫死。** 兩支都寫死 `real-estate-valuation-py-main`，而該機器的資料夾名
   沒有 `-main` 後綴，所以 matcher 永遠不命中。已改為兩種名稱都吃。
2. **憑證檢查靜默失效。** hook 由 IDE 在 workspace 根目錄執行，而根目錄不是
   git repo（前後端各自是獨立 repo，分別在子目錄），`git diff --cached` 直接失敗，
   錯誤被 `2>/dev/null` 吞掉之後 `hits` 永遠是空字串，等於永遠回報沒有可疑檔案。
   已改為逐一進入各子 repo 檢查。這個失敗模式正是專案本身最反對的那種
   （安靜地給出錯誤結論，見 `decisions.md`）。
3. **輸出不是合法 JSON。** 原本用 shell 的 `printf` 產生 `permissionDecision`
   回應，格式字串裡的 `\n` 被解釋成真換行並嵌進 JSON 字串值，那是無效 JSON，
   決策無法被解析，命中了也攔不下來。改用 `python3` 的 `json.dumps` 產生輸出，
   任何檔名都能正確轉義。註：macOS 的 awk 會把 `"\\n"` 再解釋成真換行，
   中途試過的 awk 版本同樣不可行。

`kernel-tests-on-save.json` 目前在該機器上仍會失敗，因為那個 `.venv` 沒有安裝
`pytest`（見 `tech.md` 的換機器差異表）。規則集的正確性改用
`kernel/src/validate.py` 的 `check_ruleset()` 驗證，它只用標準庫。

## specs/

目前是空的。

原因：spec 是「需求 → 設計 → 任務」的開發紀錄，這個專案的既有程式是在
導入 Kiro 之前完成的，替已經寫好的程式倒推一份 spec 沒有意義。
接下來的功能開發會實際走 spec 流程，屆時紀錄會出現在這裡。

已排入候選的題目：

- **接上 `/api/rulesets`**：後端端點已可用，`valuationService.ts` 也已定義
  `listRulesets()`，但前端沒有任何地方呼叫它。接起來可在畫面上抽換不同行政區
  的評價基準
- **書表改存 S3**：目前存在 `tempfile.gettempdir()`，部署到 Lambda 會導致
  產表後下載不到檔案。這是部署前的必要改動
- **依 `land_use` 選規則集**：`api/main.py` 目前寫死預設規則集，上傳其他行政區
  的書表會用錯基準審查而且不提示。表5-1 已經解析出 `land_use`，只是沒拿來選。
  現在規則集已有兩組（金山商業、樹林住宅），這個缺陷開始會真的選錯
- **補編住宅用地的內政部上限表**：`kernel/rules/moi_caps_regional.json` 只有
  附件24 的商業用地表，住宅用地那份（附件24 第1表）還沒編，所以樹林那組規則集
  的合規性驗不了，`check_ruleset()` 對 29 項全發 WARN。來源是
  `土地徵收補償市價查估作業手冊.pdf` 的附件24
- **表3 的 parser**：正式題目的勘查表是表3 且共 4 張，版面與表1 不同，
  `table1.py` 的 `PANELS` 欄索引全部要重測。`detect.find_page` 目前遇到同一張表
  有多頁會拋 `LookupError`，要改成收集全部並依區段編號區分。這是目前最大的
  技術風險
