"""檢查轉出來的 PDF 頁數是否符合預期。

    python scripts/check_pdf_pages.py <PDF 目錄>

頁數是回填品質的間接指標。官方範本每個檔案帶 23 張隱藏的舊範本樣例，
LibreOffice 轉檔時不理隱藏屬性，沒剝掉的話表5-1 會從 1 頁變 58 頁，
而且第 1 頁是「表7 宗地個別因素清冊」。頁數對不上就代表剝的那一步失效，
或範本的列印版面設定被弄壞了。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pdfplumber

#: 檔名開頭 → 應有頁數。表3 是四個地價區段各一頁。
EXPECTED_PAGES = {"表3": 4, "表5": 1, "表4": 1}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2

    pdf_dir = Path(argv[1])
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        print(f"   {pdf_dir} 裡沒有 PDF")
        return 1

    bad = []
    for pdf in pdfs:
        with pdfplumber.open(pdf) as doc:
            pages = len(doc.pages)
        key = next((k for k in EXPECTED_PAGES if pdf.name.startswith(k)), None)
        want = EXPECTED_PAGES.get(key)
        if want is None:
            print("   %-46s %2d 頁  （沒有預期值）" % (pdf.name[:44], pages))
            continue
        print("   %-46s %2d 頁  %s" % (pdf.name[:44], pages, "OK" if want == pages else f"預期 {want} 頁"))
        if want != pages:
            bad.append((pdf.name, pages, want))

    if bad:
        print("   頁數不符，可能是隱藏工作表沒剝掉或列印版面設定被弄壞：")
        for name, got, want in bad:
            print(f"     {name} 得到 {got} 頁，預期 {want} 頁")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
