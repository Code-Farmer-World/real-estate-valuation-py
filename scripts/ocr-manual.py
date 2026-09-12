"""把新北市查估書表製作手冊 OCR 成可搜尋的全文。

    python scripts/ocr-manual.py

## 為什麼需要這支

那份手冊的內文字型無法用文字層抽取，`pdfplumber` 讀出來是 `(cid:xxxx)`，
只有標題與目錄是標準字型。可是手冊裡的填寫說明與填載範例才是「每一格該填
什麼」的依據，而我們已經因為沒讀到那些規定漏填過三次
（表5-1 的等級文字欄、表3 的優劣等級與總級數、圈選類設施的「名稱：」欄）。

逐頁轉圖看得懂但一次只能看一頁，93 頁太慢。所以先 OCR 成全文用來定位，
再對有疑義的頁看原圖確認。OCR 用 macOS 內建的 Vision（`ocrmac`），
中文辨識品質夠好（多數區塊信心度 1.00），而且不需要額外裝系統套件。

## 產出怎麼用

輸出到 `../docs/ocr/新北查估書手冊-OCR.md`，也就是官方 PDF 旁邊，
不進版控（`.gitignore` 有 `docs/ocr/`）。理由是它等同官方文件內容，
比照 `*.pdf` 處理；有價值而該留在 repo 的是這支產生工具而不是產出。

用途是**定位與搜尋**，
不是引用來源。要據以填表或引條文時回去看原始 PDF 對應頁的圖，
因為 OCR 會有錯字，表格的閱讀順序也會亂（按文字區塊座標排序，
不是按表格邏輯）。

實測有用的搜法是抓規範性語句：

    應填 應敘明 須填 不得 必須 一律填 免填 不予 以「-」 填「

頁碼是 PDF 頁碼，手冊自印頁碼通常是 PDF 頁碼減 2。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT.parent / "docs" / "official" / "real-estate-valuation" / "新北查估書手冊.pdf"
OUT = ROOT.parent / "docs" / "ocr" / "新北查估書手冊-OCR.md"

#: 200 dpi 是實測的平衡點。150 會讓小字的信心度掉到 0.5 以下，
#: 300 讓每頁的辨識時間從 0.9 秒變 2 秒而正確率沒有明顯提升。
RESOLUTION = 200

HEADER = """# 新北市土地徵收補償市價查估書表製作手冊（OCR 全文）

來源 `docs/official/real-estate-valuation/新北查估書手冊.pdf`，{pages} 頁。

這份手冊的內文字型無法用文字層抽取（`pdfplumber` 讀出來是 `(cid:xxxx)`），
所以逐頁轉圖後用 macOS Vision OCR（`ocrmac`，語言 zh-Hant）辨識。

用途是**定位與搜尋**。要據以填表或引用條文時，回去看原始 PDF 對應頁的圖，
OCR 會有錯字，表格的閱讀順序也會亂（按文字區塊的座標排序，不是按表格邏輯）。
頁碼是 PDF 頁碼，手冊自己印的頁碼通常是 PDF 頁碼減 2。

產生方式：`python scripts/ocr-manual.py`

章節對照（PDF 頁碼）：

| 章 | 內容 | 頁 |
| --- | --- | --- |
| 1 | 宗地個別因素清冊 | 3–10 |
| 2 | 劃分地價區段 | 11–18 |
| 3 | 地價區段勘查表 | 19–30 |
| 4 | 買賣實例調查估價表 | 31–42 |
| 5 | 影響地價區域因素分析明細表 | 43–58 |
| 6 | 比較法調查估價表 | 59–68 |
| 7 | 比準地地價估計表 | 69–70 |
| 8 | 徵收土地宗地市價估計表 | 71–72 |
| 9 | 公共設施保留地地價加權平均計算表 | 73–76 |
| 10 | 徵收土地宗地市價評議表 | 77–78 |
| 11 | 提案表 | 79–93 |

---
"""


def main() -> int:
    if not SRC.exists():
        print(f"找不到 {SRC}")
        print("官方 PDF 不在版控裡（見 docs/README.md），需自行補檔。")
        return 1

    try:
        import pdfplumber
        from ocrmac import ocrmac
    except ImportError as e:
        print(f"缺相依：{e}。安裝：pip install pdfplumber ocrmac")
        return 1

    tmp = Path("/tmp/ocr_manual_pages")
    tmp.mkdir(exist_ok=True)

    t0 = time.time()
    parts: list[str] = []
    with pdfplumber.open(SRC) as pdf:
        total = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            img = tmp / f"p{i + 1:03d}.png"
            page.to_image(resolution=RESOLUTION).save(img)
            try:
                blocks = ocrmac.OCR(str(img), language_preference=["zh-Hant"]).recognize()
            except Exception as e:  # noqa: BLE001
                parts.append(f"## PDF p{i + 1}\n\n（OCR 失敗：{e}）\n")
                continue
            # Vision 的座標原點在左下、y 向上，所以閱讀順序是 y 由大到小、x 由小到大
            blocks.sort(key=lambda b: (-round(b[2][1], 2), b[2][0]))
            body = "\n".join(t for t, _, _ in blocks)
            parts.append(f"## PDF p{i + 1}\n\n{body}\n")
            if (i + 1) % 20 == 0:
                print(f"  {i + 1}/{total} 頁，{time.time() - t0:.0f} 秒")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(HEADER.format(pages=total) + "\n" + "\n".join(parts), encoding="utf-8")
    print(f"完成 {total} 頁，{time.time() - t0:.0f} 秒")
    # OUT 在 repo 之外（官方文件目錄），不能對 ROOT 取 relative_to
    print(f"{OUT} 共 {len(OUT.read_text('utf-8')):,} 字")
    return 0


if __name__ == "__main__":
    sys.exit(main())
