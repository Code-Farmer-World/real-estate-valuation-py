"""外部資料位置。

官方文件放在本專案的 ``docs/`` 下，與程式分開但同一個 repo——這樣 clone
一份就能跑，不必依賴外層目錄結構。也可以用環境變數覆寫，方便部署環境掛載
唯讀文件目錄。

註：專案原本是 monorepo 的一部分，`docs/` 位於上一層（`ROOT.parent`）。
拆成獨立 repo 後改為 `ROOT`。這是唯一一處依賴目錄佈局的程式碼。
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

DOC_DIR = Path(
    os.environ.get(
        "VALUATION_DOC_DIR",
        ROOT / "docs" / "official" / "real-estate-valuation",
    )
).resolve()

#: 官方 xlsx 空白範本所在目錄（表3、表4、表5 三份）。
#: 那些檔案被根目錄 .gitignore 的 *.xlsx 排除，不在版控裡，所以位置要能覆寫。
#: 預設找 workspace 外層的「正式題目」，部署時用環境變數指向掛載的唯讀目錄。
TEMPLATE_DIR = Path(
    os.environ.get("VALUATION_TEMPLATE_DIR", ROOT.parent / "正式題目")
).resolve()

SAMPLE_FORMS_PDF = DOC_DIR / "查估書表範本.pdf"
CRITERIA_PDF = DOC_DIR / "評價基準明細表範例.pdf"
MANUAL_PDF = DOC_DIR / "土地徵收補償市價查估作業手冊.pdf"
NTPC_MANUAL_PDF = DOC_DIR / "新北查估書手冊.pdf"

GOLDEN_CASE = ROOT / "kernel" / "golden" / "case_1140901_99_001.json"

#: 案件設定（案號、比準地、表4 已給的交易實例資料、case_overrides）。
#: 勘查事實本身由上傳的 xlsx 提供，這份只補 xlsx 上沒有的資訊。
SURVEY_FACTS_JSON = ROOT / "kernel" / "fixtures" / "shulin_survey_facts.json"


def require(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(
            "找不到 %s。請確認 docs/official/real-estate-valuation 已整理完成，或設定 VALUATION_DOC_DIR "
            "指向文件目錄（目前推定為 %s）。" % (path, DOC_DIR)
        )
    return path
