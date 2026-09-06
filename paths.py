"""外部資料位置。

官方文件（PDF / docx）刻意不進這個 repo：它們是唯讀證據、共 80MB，
而且比賽當天會換成官方給的新檔。所以路徑用環境變數指定，
預設指向並存的文件目錄。
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

DOC_DIR = Path(
    os.environ.get("VALUATION_DOC_DIR", ROOT.parent / "real-estate-valuation-doc")
).resolve()

SAMPLE_FORMS_PDF = DOC_DIR / "查估書表範本.pdf"
CRITERIA_PDF = DOC_DIR / "評價基準明細表範例.pdf"
MANUAL_PDF = DOC_DIR / "土地徵收補償市價查估作業手冊.pdf"
NTPC_MANUAL_PDF = DOC_DIR / "新北查估書手冊.pdf"

GOLDEN_CASE = ROOT / "kernel" / "golden" / "case_1140901_99_001.json"


def require(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(
            "找不到 %s。官方文件不在這個 repo 裡，請設定 VALUATION_DOC_DIR "
            "指向文件目錄（目前推定為 %s）。" % (path, DOC_DIR)
        )
    return path
