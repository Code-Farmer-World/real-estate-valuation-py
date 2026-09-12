"""決定每一格填什麼。

這一層不 import kernel。表5-1 的計算結果由呼叫端以參數注入（只依賴介面，
不依賴實作），比照 pdfform/ 的既有相依方向。理由寫在 structure.md：
一旦這裡自己算，「每個數字都指得回官方文件」的追溯鏈就斷在這一層。

兩種輸出模式：
    live=True   加總與四則運算寫成 Excel 公式，局處填個別因素後下游自動更新
    live=False  全部寫成規則引擎算好的數值，用於對照答案與轉 PDF

兩者的數字必須一致，那是一道交叉驗證：公式算出來的與引擎算出來的不同，
表示有一邊寫錯了。
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from openpyxl.worksheet.worksheet import Worksheet

from . import formulas, layout
from .write import cell, put, put_formula, put_money, put_percent

#: 表5-1 的備註欄文字。說明兩件事：哪三項的修正移到表4，以及容積率的處理依據。
TABLE5_1_REMARK_ALL_CASE = (
    "一、使用分區、建蔽率、容積率之優劣等級依評價基準明細表評定，"
    "其修正併同於比較法調查估價表宗地個別因素考量調整修正，本表以 0.00% 計，"
    "不列入各群組百分比小計及總修正數。"
    "二、容積率依地價查估單位說明，本案各區段道路寬度均未達八公尺，"
    "一律以 200% 計算（勘查表原載 P001-00、P003-00、P004-00 為 260%，"
    "P002-00 為 200%），四區段同級故修正率為 0.00%。"
    "三、其他影響因素本案未予評定，等級欄以「-」表示，修正率 0.00%。"
)

#: 表4 全案備註。個別因素的前提一定要寫在這裡，否則試算價格會被當成完整答案。
TABLE4_REMARK_ALL_CASE_TEMPLATE = (
    "一、本表個別因素（項目7至25）依本表註記由地價查估單位依「土地徵收補償市價"
    "查估辦法」第20條及「影響地價個別因素評價基準表」辦理，題目未提供宗地個別"
    "條件資料，故未填載。"
    "二、區域因素調整百分率依「新北市樹林區普通住宅用地影響地價區域因素評價基準"
    "明細表」計算，明細見表5-1。"
    "三、本表試算價格、調整百分率絕對值加總、比較標的權重及比準地比較價格均以"
    "個別因素 0% 計算，個別因素填載後須重新計算，權重排序亦可能改變。"
    "四、比準地地價依「土地徵收補償市價查估辦法」第21條分段無條件進位為 {land_price} 元/平方公尺"
    "（本表無此欄位，附記於此）。"
)


# ---------- 表5-1 ----------


def fill_table5_1(
    ws: Worksheet,
    result: Any,
    *,
    case_id: str,
    example_no: dict[str, str],
    live: bool,
) -> dict[str, int]:
    """填表5-1。

    參數：
        result      表5-1 的計算結果。只用到 .benchmark、.comparables、.groups
                    與 .grade()／.correction()／.subtotal()／.totals，
                    不依賴具體型別。
        example_no  {區段編號: 實例編號}，題目表4 已給
        live        True 寫公式，False 寫數值

    回傳各類格子的實際寫入數，供呼叫端與預期格數比對。
    """
    counts = {"grades": 0, "grade_labels": 0, "corrections": 0, "subtotals": 0, "totals": 0}

    put(ws, layout.TABLE5_1_CASE_ID, case_id)

    segments = [result.benchmark] + list(result.comparables)
    grade_cols = [layout.TABLE5_1_GRADE_COL["benchmark"]] + [
        layout.TABLE5_1_GRADE_COL[i] for i in range(len(result.comparables))
    ]

    # 區段編號那一列
    for col, seg in zip(grade_cols, segments):
        put(ws, f"{col}{layout.TABLE5_1_SEGMENT_ROW}", seg)

    # 實例編號
    for i, seg in enumerate(result.comparables):
        if seg in example_no:
            put(ws, layout.TABLE5_1_EXAMPLE_NO[i], example_no[seg])

    # 優劣等級是兩欄：級數與等級文字（新北手冊第 5 章第 42 頁）。
    # 116 格級數（不適用者填「-」，那是 GradeCell.text 決定的）
    # 加 116 格等級文字（「優」「稍優」…，不適用者填「無」）。
    label_cols = [layout.TABLE5_1_GRADE_LABEL_COL["benchmark"]] + [
        layout.TABLE5_1_GRADE_LABEL_COL[i] for i in range(len(result.comparables))
    ]
    for row, fid in layout.TABLE5_1_FACTOR_ROWS.items():
        for col, label_col, seg in zip(grade_cols, label_cols, segments):
            cell = result.grade(seg, fid)
            put(ws, f"{col}{row}", cell.text)
            counts["grades"] += 1
            put(ws, f"{label_col}{row}", cell.label)
            counts["grade_labels"] += 1

    # 87 格修正百分比
    for row, fid in layout.TABLE5_1_FACTOR_ROWS.items():
        for i, seg in enumerate(result.comparables):
            col = layout.TABLE5_1_PCT_COL[i]
            put_percent(ws, f"{col}{row}", result.correction(seg, fid).pct)
            counts["corrections"] += 1

    # 24 格群組小計
    subtotal_rows = layout.TABLE5_1_SUBTOTAL_ROW_ORDER
    if len(subtotal_rows) != len(result.groups):
        raise ValueError(
            f"範本有 {len(subtotal_rows)} 個群組小計列，規則集有 {len(result.groups)} 個群組，"
            f"對不上。請確認 layout.py 與規則集是否同步。"
        )
    for i, seg in enumerate(result.comparables):
        col = layout.TABLE5_1_PCT_COL[i]
        for row, group in zip(subtotal_rows, result.groups):
            if live:
                put_formula(
                    ws,
                    f"{col}{row}",
                    formulas.table5_1_subtotal(col, row),
                    number_format="0.00%;-0.00%",
                )
            else:
                put_percent(ws, f"{col}{row}", result.subtotal(seg, group))
            counts["subtotals"] += 1

    # 3 格總修正數
    for i, seg in enumerate(result.comparables):
        col = layout.TABLE5_1_PCT_COL[i]
        coord = f"{col}{layout.TABLE5_1_TOTAL_ROW}"
        if live:
            put_formula(ws, coord, formulas.table5_1_total(col), number_format="0.00%;-0.00%")
        else:
            put_percent(ws, coord, result.totals[seg])
        counts["totals"] += 1

    put(ws, f"D{layout.TABLE5_1_REMARK_ROW_ALL_CASE}", TABLE5_1_REMARK_ALL_CASE)
    return counts


# ---------- 表4 ----------


def fill_table4(ws: Worksheet, data: dict[str, Any], *, live: bool) -> None:
    """填表4。

    `data` 的結構（全部由呼叫端算好或從題目讀出）：
        benchmark            比準地區段編號
        comparables          [區段編號]，依表上欄位順序
        given[seg]           題目已給：normal_unit_price、transaction_date、
                             date_adjustment_pct、adjusted_unit_price、parcel、example_no
        benchmark_parcel     比準地地號
        appraisal_base_date  估價基準日（表頭 L1）
        case_id              案號（表頭 P1）
        benchmark_parcel_serial  比準地宗地流水號（F2）
        regional_pct[seg]    區域因素調整百分率（我們算的）
        abs_sum_pct[seg]     調整百分率絕對值加總
        similarity[seg]      價格形成因素之相近程度
        weight_pct[seg]      比較標的權重
        trial_price[seg]     試算價格
        benchmark_comparison_price
        benchmark_land_price

    個別因素項目 7 到 25 一律留空。題目未提供宗地個別條件資料，
    依表4 註記由地價查估單位辦理。
    """
    bench = data["benchmark"]
    comps = list(data["comparables"])
    given = data["given"]

    bcol = layout.TABLE4_COND_COL["benchmark"]

    # 表頭。都存成文字：估價基準日是民國日期，宗地流水號 0003 開頭那個 0
    # 一旦被當數字就會掉。
    if data.get("appraisal_base_date") is not None:
        put(ws, layout.TABLE4_CELL_BASE_DATE, str(data["appraisal_base_date"]))
    if data.get("case_id") is not None:
        put(ws, layout.TABLE4_CELL_CASE_ID, str(data["case_id"]))
    if data.get("benchmark_parcel_serial") is not None:
        put(ws, layout.TABLE4_CELL_BENCHMARK_SERIAL, str(data["benchmark_parcel_serial"]))

    # 比準地欄：只有地號與區段編號，沒有交易實例
    put(ws, f"{bcol}{layout.TABLE4_ROW_SEGMENT}", bench)
    if data.get("benchmark_parcel"):
        put(ws, f"{bcol}4", data["benchmark_parcel"])

    for i, seg in enumerate(comps):
        cond = layout.TABLE4_COND_COL[i]
        diff = layout.TABLE4_DIFF_COL[i]
        g = given[seg]

        if g.get("example_no") is not None:
            put(ws, layout.TABLE4_EXAMPLE_NO_CELLS[i], str(g["example_no"]))

        put(ws, f"{cond}4", g.get("parcel"))
        put_money(ws, f"{cond}{layout.TABLE4_ROW_NORMAL_UNIT_PRICE}", g.get("normal_unit_price"))
        put(ws, f"{cond}{layout.TABLE4_ROW_TRANSACTION_DATE}", g.get("transaction_date"))
        put_percent(ws, f"{diff}{layout.TABLE4_ROW_TRANSACTION_DATE}", g.get("date_adjustment_pct"))
        put_money(ws, f"{cond}{layout.TABLE4_ROW_ADJUSTED_UNIT_PRICE}", g.get("adjusted_unit_price"))
        put(ws, f"{cond}{layout.TABLE4_ROW_SEGMENT}", seg)

        # 區域因素調整百分率：我們算的，一律寫數值。不做跨檔案參照。
        put_percent(ws, f"{diff}{layout.TABLE4_ROW_SEGMENT}", data["regional_pct"][seg])

        # 個別因素合計
        total_coord = f"{cond}{layout.TABLE4_ROW_INDIVIDUAL_TOTAL}"
        if live:
            put_formula(
                ws, total_coord, formulas.table4_individual_total(diff), number_format="0.00%;-0.00%"
            )
        else:
            put_percent(ws, total_coord, Decimal(0))

        left = layout.TABLE4_DECISION_LEFT_COL[i]
        right = layout.TABLE4_DECISION_RIGHT_COL[i]

        abs_coord = f"{left}{layout.TABLE4_ROW_ABS_SUM}"
        if live:
            put_formula(ws, abs_coord, formulas.table4_abs_sum(diff), number_format="0.00%;-0.00%")
        else:
            put_percent(ws, abs_coord, data["abs_sum_pct"][seg])

        put(ws, f"{right}{layout.TABLE4_ROW_ABS_SUM}", data["similarity"][seg])

        trial_coord = f"{left}{layout.TABLE4_ROW_TRIAL_PRICE}"
        if live:
            put_formula(
                ws,
                trial_coord,
                formulas.table4_trial_price(cond, diff, cond),
                number_format="#,##0",
            )
        else:
            put_money(ws, trial_coord, data["trial_price"][seg])

        # 權重兩版都寫數值：它含排序分級的判斷，不是純算術
        put_percent(ws, f"{right}{layout.TABLE4_ROW_TRIAL_PRICE}", data["weight_pct"][seg])

    if live:
        put_formula(
            ws,
            layout.TABLE4_BENCHMARK_PRICE_CELL,
            formulas.table4_benchmark_comparison_price(),
            number_format="#,##0",
        )
    else:
        put_money(ws, layout.TABLE4_BENCHMARK_PRICE_CELL, data["benchmark_comparison_price"])

    put(
        ws,
        layout.TABLE4_REMARK_ALL_CASE_CELL,
        TABLE4_REMARK_ALL_CASE_TEMPLATE.format(
            land_price=f"{data['benchmark_land_price']:,}"
        ),
    )


# ---------- 表3 ----------

#: 表3 的建蔽率、容積率填的是勘查表原載值（字串含 %），不是計算用值。
#: 容積率一律以 200% 計算是局處對「計算」的指示，勘查表本身仍應忠實記載現況。
#: 這個區分寫在表5-1 的備註欄。
#: 清單本身在 layout.py，寫入與讀取共用同一份宣告。
_PERCENT_FIELDS = layout.TABLE3_PERCENT_FIELDS


def fill_table3(
    ws: Worksheet,
    segment: str,
    seg_data: dict[str, Any],
    *,
    year_period: str,
    grades: dict[str, Any] | None = None,
    grade_counts: dict[str, int] | None = None,
) -> None:
    """填一張表3（一個區段）。

    圈選類欄位（大型車站、站牌、交流道、學校、市場、公園、觀光遊憩、停車場地、
    服務性設施、電業、殯葬、廢棄物、環境污染）本案全部未勾、距離空白，
    維持範本原狀不動，因為「沒有勾選」本身就是事實。它們的優劣等級照填，
    因為「無」在基準表上是一個有效的等級（多數是最劣級）。

    `grades` 是 {factor_id: 填進等級欄的文字}，`grade_counts` 是
    {factor_id: 總級數}。每個細項名稱左邊有兩個窄欄要填這兩個值，
    依新北市查估書表製作手冊第 3 章第 25 頁的填載範例。
    兩者都沒給就跳過等級欄（讀取端 round-trip 時不需要重填）。
    """
    facts = seg_data["facts"]
    raw = seg_data.get("raw", {})

    put(ws, layout.TABLE3_CELL_YEAR, year_period)
    put(ws, layout.TABLE3_CELL_SEGMENT_NO, segment)
    put(ws, layout.TABLE3_CELL_SEGMENT_RANGE, seg_data.get("segment_range"))

    for fid, coord in layout.TABLE3_VALUE_CELLS_A.items():
        value = raw.get(fid, facts.get(fid))
        if fid in _PERCENT_FIELDS and value is not None:
            value = f"{value}%"
        put(ws, coord, value)

    for fid, coord in layout.TABLE3_VALUE_CELLS_B.items():
        put(ws, coord, facts.get(fid))

    # 路名與土地改良的勾選項目優先取 extras（xlsx reader 產出的），
    # 沒有才從 raw 的原始字串解析（人工核對的 fixtures 是那種格式）。
    # 少了這個 fallback，round-trip 會掉字：raw 經過 reader 之後是型別轉換
    # 後的數值，解析不出路名，也拿不到勾選了哪幾項。
    extras = seg_data.get("extras") or {}

    name = extras.get("main_road_name") or _road_name(
        raw.get("regional.transport.main_road_width", "")
    )
    put(ws, layout.TABLE3_CELL_MAIN_ROAD_NAME, name)
    put(ws, layout.TABLE3_CELL_MAIN_ROAD_WIDTH, facts.get("regional.transport.main_road_width"))
    put(ws, layout.TABLE3_CELL_AVG_ROAD_WIDTH, facts.get("regional.transport.avg_road_width"))

    items = extras.get("improvement_items")
    improvement_source = (
        "".join(f"■{name}" for name in items)
        if items
        else raw.get("regional.land_improvement.site_improvement")
    )
    _fill_improvement(
        ws,
        improvement_source,
        expect_count=facts.get("regional.land_improvement.site_improvement"),
    )

    only = seg_data.get("table3_only", {})
    put(ws, layout.TABLE3_CELL_BUILDING_DENSITY, only.get("building_density"))
    put(ws, layout.TABLE3_CELL_BUILDING_TYPE, only.get("building_type"))
    _fill_land_use(ws, only.get("land_use_current"))

    _fill_grades(ws, segment, grades, grade_counts)


def _fill_grades(
    ws: Worksheet,
    segment: str,
    grades: dict[str, Any] | None,
    grade_counts: dict[str, int] | None,
) -> None:
    """填每個細項的優劣等級與總級數。

    範本上這兩欄在細項名稱左邊，窄窄的兩格（左半 B／C，右半 M／N）。
    先前整批空白，因為只看得到「值欄」而沒注意到那兩欄。
    """
    if not grades and not grade_counts:
        return

    missing = []
    for fid, (grade_cell, count_cell) in layout.TABLE3_GRADE_CELLS.items():
        if grades is not None:
            if fid in grades:
                put(ws, grade_cell, grades[fid])
            else:
                missing.append(fid)
        if grade_counts is not None and fid in grade_counts:
            put(ws, count_cell, grade_counts[fid])

    if missing:
        raise ValueError(
            f"{segment} 的表3 有 {len(missing)} 個細項缺優劣等級："
            f"{sorted(missing)[:5]}。表5-1 的等級必須與勘查表相符"
            f"（新北手冊第 5 章第 42 頁），所以這裡不能靜默留空。"
        )


def _road_name(raw: Any) -> str | None:
    """從「名稱：八德街 寬度：28M」取出路名。

    P003-00 那一頁的「名稱：」被版面吃掉，值長成「東榮街 寬度：10M」，
    所以不能假設一定有「名稱：」前綴。
    """
    if not isinstance(raw, str) or not raw:
        return None
    text = raw.split("寬度")[0]
    text = text.replace("名稱：", "").replace("名稱:", "")
    return text.strip() or None


def checked_improvements(raw: Any) -> set[str]:
    """從勘查表原文取出已勾選的土地改良項目。

    原文長成「■整平或填挖基地 ■開挖水溝 □水土保持 ■鋪築道路 ■埋設管道 □修築駁嵌」。
    要在每個 ■ 與 □ 之前都斷開，不能只依 ■ 切割，否則「■開挖水溝 □水土保持」
    會被當成一個項目名而比對不到範本上的「□開挖水溝」（實測踩過，
    結果是四項只勾到兩項）。
    """
    if not isinstance(raw, str) or not raw:
        return set()
    return {
        name.strip()
        for mark, name in re.findall(r"([■□])([^■□]*)", raw)
        if mark == "■" and name.strip()
    }


def _fill_land_use(ws: Worksheet, names: Any) -> None:
    """土地利用現況的圈選。範本 Q44 印的是 ○，把有勾的改成 ●。

    整格是一段文字：「○商業用　○住宅用　○工業用　○住商混合　…○其他_____」。
    比對時帶著 ○ 前綴一起比，才不會讓「○住宅用」誤中「○住商混合」。
    """
    if not names:
        return
    coord = layout.TABLE3_CELL_LAND_USE
    current = cell(ws, coord).value
    if not isinstance(current, str):
        return

    updated, missed = current, []
    for name in names:
        if f"○{name}" in updated:
            updated = updated.replace(f"○{name}", f"●{name}")
        else:
            missed.append(name)
    if missed:
        raise ValueError(
            f"土地利用現況有 {len(missed)} 個項目在範本 {coord} 找不到對應的「○」："
            f"{missed}。範本的項目文字可能與勘查表不同，需重新核對。"
        )
    put(ws, coord, updated)


def _fill_improvement(ws: Worksheet, raw: Any, *, expect_count: int | None = None) -> None:
    """土地改良的勾選。範本印的是 □，把有勾的改成 ■。

    範本第一行是「□整平或填挖基地　□開挖水溝　□水土保持　□鋪築道路」，
    第二行是「□埋設管道　　　　□修築駁嵌　□其他＿＿＿＿＿＿」。

    `expect_count` 傳進來時會核對實際替換掉的項數。勘查表的改良項數直接決定
    這個細項的優劣等級（四項以上為優），漏勾會讓等級判錯，所以不能靜默失敗。
    """
    checked = checked_improvements(raw)
    if not checked:
        return

    replaced: set[str] = set()
    for coord in (layout.TABLE3_CELL_IMPROVEMENT_LINE1, layout.TABLE3_CELL_IMPROVEMENT_LINE2):
        current = cell(ws, coord).value
        if not isinstance(current, str):
            continue
        updated = current
        for name in checked:
            if f"□{name}" in updated:
                updated = updated.replace(f"□{name}", f"■{name}")
                replaced.add(name)
        put(ws, coord, updated)

    missed = checked - replaced
    if missed:
        raise ValueError(
            f"土地改良有 {len(missed)} 個已勾選項目在範本上找不到對應的「□」："
            f"{sorted(missed)}。範本的項目文字可能與勘查表不同，需重新核對。"
        )
    if expect_count is not None and len(replaced) != expect_count:
        raise ValueError(
            f"土地改良實際勾選 {len(replaced)} 項，與勘查事實記載的 {expect_count} 項不符。"
            f"這個項數決定該細項的優劣等級（四項以上為優），不能不一致。"
        )
