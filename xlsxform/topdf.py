"""把產出的 xlsx 轉成 PDF，用 LibreOffice 的 headless 模式。

## 為什麼不能直接丟給 LibreOffice

官方範本每個檔案裡有 24 張工作表，只有對應檔名那一張可見，其餘 23 張是
隱藏的舊範本樣例（內容是 ○○鄉／甲一／乙二 那類佔位資料）。
LibreOffice 轉 PDF 時不理隱藏屬性，把 24 張全部印出來，
表5-1 那份會變成 58 頁，第 1 頁是「表7 宗地個別因素清冊」。

所以先做一份只留可見工作表的副本再轉。交付的 xlsx 本身保持範本原狀，
那 23 張隱藏表是官方範本自帶的,不由我們刪。

## LibreOffice 也是唯一能驗活版公式的東西

`openpyxl` 寫入公式後檔案裡沒有快取值,程式讀回來只拿得到公式字串。
把活版丟給 LibreOffice 轉存一次,它會重算並寫入快取值,
就能用 `data_only=True` 讀出「真的試算表引擎算出什麼」。
見 `xlsxform/tests/test_libreoffice_recalc.py`。

## 安裝

macOS 用官方 dmg,不需要 Homebrew 也不需要 sudo（`/Applications` 可寫）:

    curl -L -o /tmp/LO.dmg https://download.documentfoundation.org/libreoffice/stable/26.2.6/mac/aarch64/LibreOffice_26.2.6_MacOS_aarch64.dmg
    hdiutil attach -nobrowse -quiet /tmp/LO.dmg
    cp -R /Volumes/LibreOffice/LibreOffice.app /Applications/
    hdiutil detach /Volumes/LibreOffice -quiet
    xattr -dr com.apple.quarantine /Applications/LibreOffice.app
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import openpyxl

#: 常見的 soffice 位置。找不到就回 None,呼叫端決定要跳過還是報錯。
SOFFICE_CANDIDATES = (
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "/usr/bin/soffice",
    "/usr/local/bin/soffice",
    "/opt/homebrew/bin/soffice",
)

#: 獨立的使用者設定目錄。不指定的話,同時跑兩個 headless 會互相搶 profile 鎖。
_PROFILE = "file:///tmp/lo-profile-xlsxform"


def find_soffice() -> Path | None:
    """找 LibreOffice 執行檔。"""
    which = shutil.which("soffice")
    if which:
        return Path(which)
    for c in SOFFICE_CANDIDATES:
        p = Path(c)
        if p.exists():
            return p
    return None


#: 轉 PDF 時預設排除的工作表。
#:
#: 「計算依據」有 14 欄而且其中兩欄是整段敘述,列印會從 1 頁炸成 34 頁。
#: 那張是給人在表格軟體裡查證用的（可以拉欄寬、可以搜尋）,不是要印出來交的。
#: 要印的話用 `--include-evidence`。
DEFAULT_EXCLUDE_SHEETS = ("計算依據",)


def strip_hidden_sheets(
    src: Path, dest: Path, *, exclude: tuple[str, ...] = ()
) -> list[str]:
    """複製一份只留可見工作表的檔案。回傳留下來的工作表名稱。

    直接對副本操作,不動原始檔。
    """
    wb = openpyxl.load_workbook(src)
    keep = [
        ws.title
        for ws in wb.worksheets
        if ws.sheet_state != "hidden" and ws.title not in exclude
    ]
    if not keep:
        raise ValueError(f"{src.name} 沒有任何要轉出的工作表")
    for ws in list(wb.worksheets):
        if ws.title not in keep:
            wb.remove(ws)
    dest.parent.mkdir(parents=True, exist_ok=True)
    wb.save(dest)
    return keep


def to_pdf(
    src: Path,
    out_dir: Path,
    *,
    soffice: Path | None = None,
    timeout: int = 300,
    exclude: tuple[str, ...] = DEFAULT_EXCLUDE_SHEETS,
) -> Path:
    """把一份 xlsx 轉成 PDF。

    轉出來的頁數取決於範本的列印版面設定,那些設定在複製工作表時保留下來了。
    """
    soffice = soffice or find_soffice()
    if soffice is None:
        raise FileNotFoundError(
            "找不到 LibreOffice。安裝方式見 xlsxform/topdf.py 的模組說明。"
        )

    src, out_dir = Path(src), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        flat = Path(tmp) / src.name
        strip_hidden_sheets(src, flat, exclude=exclude)
        proc = subprocess.run(
            [
                str(soffice),
                "--headless",
                f"-env:UserInstallation={_PROFILE}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(out_dir),
                str(flat),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    pdf = out_dir / f"{src.stem}.pdf"
    if not pdf.exists():
        raise RuntimeError(
            f"轉檔沒有產生 {pdf.name}。soffice 的輸出：\n{proc.stdout}\n{proc.stderr}"
        )
    return pdf


def recalculate(src: Path, out_dir: Path, *, soffice: Path | None = None, timeout: int = 300) -> Path:
    """讓 LibreOffice 重算一份 xlsx 並轉存,產生帶快取值的副本。

    用途是驗證活版的 Excel 公式。轉存後的檔案用
    `openpyxl.load_workbook(path, data_only=True)` 就讀得到計算結果。

    這裡不刪隱藏工作表,因為要保持格位不動。
    """
    soffice = soffice or find_soffice()
    if soffice is None:
        raise FileNotFoundError("找不到 LibreOffice")

    src, out_dir = Path(src), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if out_dir.resolve() == src.parent.resolve():
        raise ValueError("輸出目錄不能與來源相同,會覆蓋原始檔案")

    proc = subprocess.run(
        [
            str(soffice),
            "--headless",
            f"-env:UserInstallation={_PROFILE}",
            "--convert-to",
            "xlsx",
            "--outdir",
            str(out_dir),
            str(src),
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    dest = out_dir / src.name
    if not dest.exists():
        raise RuntimeError(f"重算沒有產生 {dest.name}。\n{proc.stdout}\n{proc.stderr}")
    return dest


def main(argv: list[str] | None = None) -> int:
    """把一個產出目錄裡的 xlsx 轉成 PDF。

        python -m xlsxform.topdf --out <產出目錄>              定版與勘查表
        python -m xlsxform.topdf --out <產出目錄> --all         連活版一起
    """
    import argparse

    ap = argparse.ArgumentParser(description="把產出的 xlsx 轉成 PDF（需要 LibreOffice）")
    ap.add_argument("--out", type=Path, required=True, help="xlsxform.cli 的輸出目錄")
    ap.add_argument(
        "--pdf-dir",
        type=Path,
        default=None,
        help="PDF 的輸出目錄，預設是 <out>/PDF",
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help="連活版（-live）也轉。預設只轉定版與勘查表，因為活版是給人繼續編輯的",
    )
    ap.add_argument(
        "--include-evidence",
        action="store_true",
        help="連「計算依據」工作表也轉。那張 14 欄含整段敘述，列印會從 1 頁變 34 頁",
    )
    args = ap.parse_args(argv)

    soffice = find_soffice()
    if soffice is None:
        print("找不到 LibreOffice。安裝方式見 xlsxform/topdf.py 的模組說明。")
        return 1
    print(f"使用 {soffice}")

    pdf_dir = args.pdf_dir or (args.out / "PDF")
    targets = sorted(
        p
        for p in args.out.glob("*.xlsx")
        if args.all or "-live" not in p.stem
    )
    if not targets:
        print(f"{args.out} 裡沒有可轉的 xlsx")
        return 1

    exclude = () if args.include_evidence else DEFAULT_EXCLUDE_SHEETS
    for src in targets:
        pdf = to_pdf(src, pdf_dir, soffice=soffice, exclude=exclude)
        size = pdf.stat().st_size / 1024
        print(f"  {pdf}  ({size:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
