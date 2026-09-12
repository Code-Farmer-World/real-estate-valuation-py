"""回填完整性的守門測試。

## 這一組測試在防什麼

`test_output.py` 驗的是「填進去的值對不對」。這一組驗的是「有沒有填」。
兩者抓不到同一類錯誤。

實際踩過三次漏填，每次都是程式跑完、驗證通過、測試全綠，只有把產出檔案
打開逐格看才發現：表4 表頭六格整排沒填、表3 的建築密度值寫進標籤格
把欄位名蓋掉、土地利用現況整格沒動。

所以這裡把「我們動了哪些格」整份釘住。任何改動讓某一格不再填入，
或多動了一格（例如又把標籤蓋掉），座標集合就對不上，測試會紅。

座標集合是實測結果，不是設計文件。改格位對映之後要先跑
`python -m xlsxform.audit` 逐列確認，再更新這裡的清單。
順序無關，比對的是集合。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from xlsxform import layout
from xlsxform.audit import audit_sheet, filled_coords
from xlsxform.pipeline import (
    OUTPUT_STEM,
    compute_all,
    find_template,
    write_table3,
    write_table4,
    write_table5,
)

ROOT = Path(__file__).resolve().parent.parent.parent
FACTS = json.loads((ROOT / "kernel" / "fixtures" / "shulin_survey_facts.json").read_text("utf-8"))
COMPS = list(FACTS["comparables"])
SEGMENTS = [FACTS["benchmark"]] + COMPS

TEMPLATES = Path(__file__).resolve().parent.parent.parent.parent / "正式題目"

pytestmark = pytest.mark.skipif(
    not TEMPLATES.exists(), reason=f"找不到官方範本目錄 {TEMPLATES}"
)

#: 表4 該動的 46 格。
#: 表頭 6 + 地號 4 + 已給資料 15 + 區段號 4 + 區域因素 3 + 個別因素合計 3
#: + 決策列 12（絕對值加總、相近程度、試算價格、權重各 3）
#: + 比準地比較價格 1 + 全案備註 1。
#: 比準地沒有交易實例，所以 D5／D6／D7 空著是對的。
#: 個別因素項目 7 到 25（第 9 到 28 列）題目未提供，一律留空。
TABLE4_EXPECTED = {
    # 表頭：估價基準日、案號、比準地宗地流水號、三個實例編號
    "L1", "P1", "F2", "J2", "N2", "R2",
    # 地號
    "D4", "G4", "K4", "O4",
    # 土地正常單價、交易日期與其調整率、調整至基準日單價
    "G5", "K5", "O5",
    "G6", "J6", "K6", "N6", "O6", "R6",
    "G7", "K7", "O7",
    # 地價區段號與區域因素調整百分率（J8／N8／R8 是我們算的）
    "D8", "G8", "J8", "K8", "N8", "O8", "R8",
    # 個別因素合計
    "G29", "K29", "O29",
    # 調整百分率絕對值加總與價格形成因素之相近程度
    "G30", "I30", "K30", "M30", "O30", "Q30",
    # 試算價格與比較標的權重
    "G31", "I31", "K31", "M31", "O31", "Q31",
    # 比準地比較價格、全案備註
    "G32", "D34",
}

#: 表3 每個地價區段該動的 23 格。四張表結構相同，值不同。
#: `E31`／`E32`（土地改良）與 `Q44`（土地利用現況）是覆寫勾選符號，
#: 其餘 20 格是填入空白格。
TABLE3_EXPECTED = {
    # 年期、區段編號、區段範圍
    "B3", "G3", "L3",
    # 土地使用管制六項
    "H4", "H5", "H6", "H7", "H8", "H9",
    # 主要道路名稱與寬度、區段內道路平均寬度
    "G11", "J11", "G12",
    # 自然條件與道路闢建程度
    "I23", "I24", "I25", "I26", "I27", "I28",
    # 土地改良勾選兩行
    "E31", "E32",
    # 建築密度、建築型態（值在 R 欄，Q 欄是範本印的標籤）
    "R42", "R43",
    # 土地利用現況勾選
    "Q44",
}

#: 表5-1 的表頭與備註。細項的 116／87／24／3 格由 `write_table5()`
#: 回傳的 counts 把關（見 `test_output.py`），這裡只釘住容易被忘記的邊角。
TABLE5_1_HEADER_EXPECTED = {
    "B2",  # 案號
    "G2", "J2", "M2",  # 三個實例編號
    "C3", "E3", "H3", "K3",  # 四個地價區段號
    "C44",  # 全案備註
}

#: 表5-1 動過的總格數 = 116 等級 + 87 修正率 + 24 小計 + 3 總修正數
#: + 8 表頭 + 1 全案備註
TABLE5_1_TOTAL = 239


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("audit")
    computed = compute_all(FACTS)
    paths = {
        "table3": write_table3(FACTS, find_template(TEMPLATES, "table3"), out / "t3.xlsx"),
    }
    p, _ = write_table5(
        FACTS, computed, find_template(TEMPLATES, "table5"), out / "t5.xlsx", live=False
    )
    paths["table5"] = p
    paths["table4"] = write_table4(
        computed, find_template(TEMPLATES, "table4"), out / "t4.xlsx", live=False
    )
    return paths


def _diff(actual: set[str], expected: set[str]) -> str:
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    parts = []
    if missing:
        parts.append(f"該填卻沒填：{missing}")
    if extra:
        parts.append(f"多動了（可能把範本印好的標籤蓋掉）：{extra}")
    return "；".join(parts)


def test_table4_filled_cells_are_exactly_as_expected(built):
    actual = filled_coords(
        find_template(TEMPLATES, "table4"), built["table4"], sheet_title=layout.SHEET_TABLE4
    )
    assert actual == TABLE4_EXPECTED, _diff(actual, TABLE4_EXPECTED)


def test_table3_filled_cells_are_exactly_as_expected(built):
    template = find_template(TEMPLATES, "table3")
    for seg in SEGMENTS:
        title = layout.TABLE3_SHEET_TITLE.format(segment=seg)
        actual = filled_coords(template, built["table3"], sheet_title=title)
        assert actual == TABLE3_EXPECTED, f"{seg}：{_diff(actual, TABLE3_EXPECTED)}"


def test_table5_1_header_and_remark_are_filled(built):
    actual = filled_coords(
        find_template(TEMPLATES, "table5"), built["table5"], sheet_title=layout.SHEET_TABLE5_1
    )
    assert len(actual) == TABLE5_1_TOTAL

    edges = {c for c in actual if c[1:].isdigit() and (int(c[1:]) <= 3 or int(c[1:]) >= 43)}
    assert edges == TABLE5_1_HEADER_EXPECTED, _diff(edges, TABLE5_1_HEADER_EXPECTED)


def test_no_printed_label_is_overwritten_by_a_value(built):
    """覆寫範本原有內容只有兩種情況是對的，其他都是把標籤蓋掉。

    合法的覆寫：
    1. 勾選符號 `□`→`■`（土地改良）、`○`→`●`（土地利用現況）。
    2. 範本印的單位提示換成帶百分比格式的數值：表5-1 小計列與總修正數列的
       `％`，表3 建蔽率與容積率原印的 `-`。

    先前把建築密度的值寫進 `Q42`，蓋掉「建築密度」那個欄位名，
    就是這個測試要抓的東西。
    """
    checks = [
        (find_template(TEMPLATES, "table4"), built["table4"], layout.SHEET_TABLE4),
        (find_template(TEMPLATES, "table5"), built["table5"], layout.SHEET_TABLE5_1),
    ] + [
        (
            find_template(TEMPLATES, "table3"),
            built["table3"],
            layout.TABLE3_SHEET_TITLE.format(segment=seg),
        )
        for seg in SEGMENTS
    ]

    for template, output, title in checks:
        for a in audit_sheet(template, output, sheet_title=title):
            if a.kind != "改":
                continue
            ok = (
                # 勾選符號換掉，項目文字本身要留著
                ("□" in a.template and "■" in a.output)
                or ("○" in a.template and "●" in a.output)
                # 單位提示或佔位符換成數值
                or a.template in ("％", "%", "-", "－")
            )
            assert ok, (
                f"{title} 的 {a.coord} 把範本內容 {a.template!r} 換成 {a.output!r}。"
                f"那一格看起來是範本印好的標籤，值應該填在旁邊的格子。"
            )
