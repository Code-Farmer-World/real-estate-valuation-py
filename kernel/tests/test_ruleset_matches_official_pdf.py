"""把樹林住宅規則集的修正率矩陣跟官方評價基準明細表 PDF 逐格對照。

## 這組測試在防什麼

`shulin_residential_regional.json` 的 29 個細項是人工從官方 PDF 編碼進來的。
矩陣抄錯一個數字，計算全程不會有任何異狀：判級照樣成功、小計照樣加得起來、
自我驗證照樣通過、金山 Golden Case 照樣全綠（那是另一組規則集）。
錯的答案會安靜地一路走到交件的書表上。

這是整個專案剩下最大的正確性風險，而且沒有官方答案可以對，因為題目的表5-1
與表4 是空白待填的。

能做的是反過來驗來源：從 PDF 把矩陣抽出來，跟 JSON 比對。
兩邊都是機器讀的，不經過人的眼睛。

## 為什麼用多重集合比對

PDF 的細項名稱是縱排單字（「土 蔽 地 率」這樣一個字一列夾在矩陣中間），
沒辦法可靠地把矩陣歸屬到細項名。所以比對的是「矩陣的多重集合」：
29 個矩陣的內容與出現次數兩邊必須完全一致。

這抓得到任何一個數字抄錯（集合會對不上），抓不到「兩個細項的矩陣互換」
（集合仍相同）。後者的風險低得多，而且互換會讓等級定義與矩陣不搭，
`check_ruleset()` 的 `max_range` 一致性檢查會擋下大部分情況。

## 都市計畫那一格為什麼另外驗

`都市計畫（內、外）` 是 PDF 上唯一數字排在等級文字前面的矩陣
（`0 +20 優：` 與 `-20 0 劣：`，等級標籤被縱排的「都市計畫內外」擠掉了），
通用的抽取樣式抓不到，所以單獨用文字比對。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
RULESET_PATH = ROOT / "kernel" / "rules" / "shulin_residential_regional.json"

#: 官方基準表 PDF。與 `xlsxform` 的範本同一個目錄。
TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "正式題目"
PDF_PATH = TEMPLATE_DIR / "評價基準明細表.pdf"

#: 區域因素在前 5 頁，第 6 到 9 頁是個別因素的基準表（本案不用，題目未給宗地資料）
REGIONAL_PAGES = 5

pytestmark = pytest.mark.skipif(
    not PDF_PATH.exists(), reason=f"找不到官方基準表 {PDF_PATH}"
)

#: 等級文字。長的排前面，否則 `優` 會先吃掉 `極優` 的後半
_GRADE = r"極優|稍優|極劣|稍劣|普通|優|劣"

#: 一列矩陣：等級文字後面跟 2 到 7 個帶正負號的數字。
#: 上限 7 是因為「其他影響因素」是七級制，設 5 會把它截斷。
_ROW = re.compile(r"(%s)((?:\s+[+-]?\d+(?:\.\d+)?){2,7})(?:\s|$)" % _GRADE)

#: 矩陣第一列的等級文字。七級制從「極優」開始
_FIRST_ROW_GRADES = {"優", "極優"}

#: 都市計畫（內、外）：PDF 上數字排在等級文字前面，通用樣式抓不到
URBAN_PLAN_PDF_ROWS = ("0 +20", "-20 0")
URBAN_PLAN_FACTOR_ID = "regional.land_control.urban_plan"


def _cells_from_ruleset(factor: dict) -> tuple[tuple[float, ...], ...]:
    """把 JSON 的矩陣展開成完整的 cells。

    `linear_step` 是 `step × (欄 - 列)`，`cells` 直接用。
    展開之後兩種寫法可以放在一起比。
    """
    m = factor["matrix"]
    n = factor["grade_count"]
    if m["kind"] == "cells":
        return tuple(tuple(round(float(v), 2) for v in row) for row in m["cells"])
    if m["kind"] == "linear_step":
        step = float(m["step"])
        return tuple(
            tuple(round(step * (j - i), 2) for j in range(n)) for i in range(n)
        )
    raise AssertionError(f"未知的 matrix kind {m['kind']!r}（{factor['factor_id']}）")


def _matrices_from_pdf() -> list[tuple[tuple[float, ...], ...]]:
    """從 PDF 前 5 頁抽出所有矩陣。

    分組規則：等級是「優」或「極優」而且目前那個矩陣已經收滿
    （列數等於欄數）就開新的一個。基準表的矩陣都是方陣。
    """
    import pdfplumber

    rows: list[tuple[str, tuple[float, ...]]] = []
    with pdfplumber.open(PDF_PATH) as pdf:
        for page in pdf.pages[:REGIONAL_PAGES]:
            for line in (page.extract_text() or "").split("\n"):
                m = _ROW.search(line)
                if m:
                    nums = tuple(round(float(x), 2) for x in m.group(2).split())
                    rows.append((m.group(1), nums))

    mats: list[list[tuple[float, ...]]] = []
    cur: list[tuple[float, ...]] | None = None
    for grade, nums in rows:
        starts_new = grade in _FIRST_ROW_GRADES and (cur is None or len(cur) >= len(cur[0]))
        if starts_new:
            if cur:
                mats.append(cur)
            cur = [nums]
        elif cur is not None:
            cur.append(nums)
    if cur:
        mats.append(cur)

    return [tuple(m) for m in mats]


@pytest.fixture(scope="module")
def ruleset() -> dict:
    return json.loads(RULESET_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pdf_matrices() -> list[tuple[tuple[float, ...], ...]]:
    pytest.importorskip("pdfplumber")
    return _matrices_from_pdf()


def test_pdf_yields_the_expected_number_of_matrices(pdf_matrices):
    """29 個細項扣掉單獨處理的都市計畫，應該抽到 28 個矩陣。

    抽到的數量變了就代表 PDF 換版或抽取樣式失效，後面的比對會失去意義，
    所以先把數量釘住。
    """
    assert len(pdf_matrices) == 28, [len(m) for m in pdf_matrices]


def test_every_pdf_matrix_is_square_and_antisymmetric(pdf_matrices):
    """矩陣必須是方陣，而且對角線為 0、上下三角互為相反數。

    這是基準表矩陣的結構性質（比準地與比較標的互換時修正率反向），
    也順便確認抽取沒有把兩個矩陣接在一起。
    """
    for mat in pdf_matrices:
        n = len(mat)
        assert all(len(row) == n for row in mat), mat
        for i in range(n):
            assert mat[i][i] == 0, mat
            for j in range(n):
                assert mat[i][j] == pytest.approx(-mat[j][i]), mat


def test_ruleset_matrices_match_the_official_pdf(ruleset, pdf_matrices):
    """29 個細項的矩陣與 PDF 逐格一致（多重集合比對）。"""
    from_json = Counter(
        _cells_from_ruleset(f)
        for f in ruleset["factors"]
        if f["factor_id"] != URBAN_PLAN_FACTOR_ID
    )
    from_pdf = Counter(pdf_matrices)

    only_json = from_json - from_pdf
    only_pdf = from_pdf - from_json
    assert not only_json and not only_pdf, (
        f"規則集有而 PDF 沒有的矩陣：{list(only_json)}；"
        f"PDF 有而規則集沒有的：{list(only_pdf)}"
    )


def test_urban_plan_matrix_matches_the_pdf(ruleset):
    """都市計畫（內、外）：兩級制，0／+20 與 -20／0。"""
    import pdfplumber

    with pdfplumber.open(PDF_PATH) as pdf:
        text = pdf.pages[0].extract_text() or ""
    for expected in URBAN_PLAN_PDF_ROWS:
        assert expected in text, f"PDF 第 1 頁找不到都市計畫的矩陣列 {expected!r}"

    factor = next(f for f in ruleset["factors"] if f["factor_id"] == URBAN_PLAN_FACTOR_ID)
    assert _cells_from_ruleset(factor) == ((0.0, 20.0), (-20.0, 0.0))


#: 一條等級定義：「優： 80%以上」這種形式
_DEFINITION = re.compile(r"(?:%s)\s*[：:]\s*(.+)" % _GRADE)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")

#: 門檻數字對不上的兩處，都是表示法差異不是抄錯。
#: 各出現兩次是因為相鄰等級共用一個門檻（「三項」的 3 同時是上界與下界）。
#:
#: 1. 建築基地改良：基準表寫中文數字「四項以上／三項／二項／一項／無」，
#:    規則集記阿拉伯數字 4／3／2／1。勘查表填的是勾選項數，所以要數字。
#: 2. 傾斜度：基準表寫數值區間「平均坡度未滿5度／5度以上未滿10度…」，
#:    規則集用 `ordered_category` 比對整串文字而不解析數字，因為勘查表
#:    填的就是「平均坡度未滿5度」這串字。所以它的 5／10／15／20
#:    不會出現在 numeric_bands 的門檻裡。
EXPECTED_THRESHOLD_GAPS = {
    "只在規則集": {4.0: 2, 3.0: 2, 2.0: 2, 1.0: 2},
    "只在基準表": {20.0: 2, 15.0: 2, 10.0: 2, 5.0: 2},
}


def _pdf_definition_numbers() -> Counter:
    """基準表備註欄裡每條等級定義的門檻數字。"""
    import pdfplumber

    nums: list[float] = []
    with pdfplumber.open(PDF_PATH) as pdf:
        for page in pdf.pages[:REGIONAL_PAGES]:
            for line in (page.extract_text() or "").split("\n"):
                m = _DEFINITION.search(line)
                if m:
                    nums += [float(x) for x in _NUMBER.findall(m.group(1))]
    return Counter(nums)


def test_numeric_band_thresholds_match_the_official_pdf(ruleset):
    """18 個數值門檻型細項的門檻值與基準表一致。

    矩陣對了還不夠。等級的判準抄錯（例如建蔽率「優：80%以上」記成 70%）
    會讓判級整排位移，答案一樣是錯的，而且同樣不會有任何異狀。
    """
    pytest.importorskip("pdfplumber")

    from_json: list[float] = []
    for f in ruleset["factors"]:
        c = f["classifier"]
        if c["type"] != "numeric_bands":
            continue
        for band in c["bands"]:
            for key in ("min", "max"):
                if key in band:
                    from_json.append(float(band[key]))

    cj, cp = Counter(from_json), _pdf_definition_numbers()
    assert dict(cj - cp) == EXPECTED_THRESHOLD_GAPS["只在規則集"], (
        f"規則集有而基準表沒有的門檻：{dict(cj - cp)}。"
        f"預期只有建築基地改良的中文數字那組。"
    )
    assert dict(cp - cj) == EXPECTED_THRESHOLD_GAPS["只在基準表"], (
        f"基準表有而規則集沒有的門檻：{dict(cp - cj)}。"
        f"預期只有傾斜度那組（它用文字類別比對，不解析數字）。"
    )


def test_every_category_grade_is_anchored_to_the_official_pdf(ruleset):
    """類別型細項的每個等級，至少要有一個寫法真的印在基準表上。

    這是防止把等級文字寫成自己的講法。判級靠字串比對，
    勘查表寫「大部分規劃及闢建」而規則集記「大部分已開闢」就永遠比不中，
    那一格會落到最劣等級而沒有人發現。

    要求「至少一個」而不是「每一個」，因為規則集刻意收了容錯變體：
    基準表印「普通完善」，勘查表可能寫「排水普通完善」，兩種都收。
    變體不會出現在基準表上，那是正常的。只要有一個寫法對得回基準表，
    這個等級就有依據。
    """
    pytest.importorskip("pdfplumber")
    import pdfplumber

    with pdfplumber.open(PDF_PATH) as pdf:
        pages = [(i + 1, page.extract_text() or "") for i, page in enumerate(pdf.pages[:REGIONAL_PAGES])]

    #: 基準表換行會把字串切開，所以比對前把空白全部去掉
    flat = {n: re.sub(r"\s+", "", text) for n, text in pages}
    whole = "".join(flat.values())

    unanchored = []
    for f in ruleset["factors"]:
        c = f["classifier"]
        if c["type"] != "ordered_category":
            continue
        for cat in c["categories"]:
            values = [re.sub(r"\s+", "", v) for v in cat["values"]]
            if not any(v in whole for v in values):
                unanchored.append((f["factor_id"], cat["grade"], cat["values"]))

    assert not unanchored, "這些等級的每一種寫法都在基準表上找不到：" + "；".join(
        f"{fid} 第{g}級 {vs}" for fid, g, vs in unanchored
    )


def test_every_factor_records_the_page_it_came_from(ruleset):
    """每個細項都要記來源頁碼，而且落在區域因素那 5 頁之內。

    頁碼會印在表5-1 附的計算依據工作表上，讓人翻得回基準表核對。
    """
    for f in ruleset["factors"]:
        page = f.get("source_page")
        assert isinstance(page, int), f["factor_id"]
        assert 1 <= page <= REGIONAL_PAGES, (f["factor_id"], page)


def test_max_range_equals_the_matrix_span(ruleset):
    """`max_range` 必須等於矩陣的最大值，那是該細項的調整上限。"""
    for f in ruleset["factors"]:
        cells = _cells_from_ruleset(f)
        span = max(max(row) for row in cells)
        assert span == pytest.approx(float(f["max_range"])), (
            f"{f['factor_id']} 的 max_range 記 {f['max_range']}，矩陣最大值是 {span}"
        )
