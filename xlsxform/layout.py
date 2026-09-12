"""官方 xlsx 範本的格位對映。

純資料，沒有邏輯。全部座標是 2026-09-12 用 openpyxl 實測量出來的，不是從 PDF
版面推測。若範本更換，先重新量測再改這裡。

量測方式與完整說明見 .kiro/specs/fill-shulin-forms/design.md 第 3 節。

三份範本的可見工作表名稱（各自的工作簿裡還有 23 張隱藏的舊範本樣例，不要動）：
    表3   「表3區段勘查表」
    表4   「表4比較法調查估價表」
    表5-1 「表5-1區域因素明細表(住)」
"""

from __future__ import annotations

# ---------- 工作表名稱 ----------

SHEET_TABLE3 = "表3區段勘查表"
SHEET_TABLE4 = "表4比較法調查估價表"
SHEET_TABLE5_1 = "表5-1區域因素明細表(住)"

#: 表3 每個區段一張工作表，命名規則
TABLE3_SHEET_TITLE = "表3 {segment}"


# ---------- 表5-1 ----------

#: 優劣等級欄。比準地一欄，三個比較標的各一欄。
TABLE5_1_GRADE_COL = {
    "benchmark": "C",
    0: "E",
    1: "H",
    2: "K",
}

#: 優劣等級的「等級文字」欄，緊接在級數欄右邊。
#:
#: 新北市土地徵收補償市價查估書表製作手冊第 5 章第 42 頁：
#: 「左欄填載各該地價區段之優劣等級級數，右欄填載優劣等級細項」。
#: 表頭的 C4:D4 是合併格所以看起來只有一欄，但細項列的 C 與 D 各自獨立。
#:
#: 官方已填好的金山範本（查估書表範本.pdf 的表5-2）逐列都是兩欄，
#: 例如「1 優」、「3 普通」、「5 劣」。題目的表5-1 在其他影響因素那列
#: 也自己填了「- 無」。先前只填級數欄，漏了這 116 格。
TABLE5_1_GRADE_LABEL_COL = {
    "benchmark": "D",
    0: "F",
    1: "I",
    2: "L",
}

#: 修正百分比欄。只有比較標的有，比準地沒有這一欄。
TABLE5_1_PCT_COL = {
    0: "G",
    1: "J",
    2: "M",
}

#: 表頭格位
TABLE5_1_CASE_ID = "B2"
TABLE5_1_EXAMPLE_NO = {0: "G2", 1: "J2", 2: "M2"}
TABLE5_1_SEGMENT_ROW = 3

#: 29 個修正細項的列號 → factor_id。順序與範本上的列順序一致。
TABLE5_1_FACTOR_ROWS: dict[int, str] = {
    5: "regional.land_control.urban_plan",
    6: "regional.land_control.zoning",
    7: "regional.land_control.building_coverage",
    8: "regional.land_control.floor_area_ratio",
    9: "regional.land_control.build_prohibition",
    10: "regional.land_control.build_restriction",
    12: "regional.transport.main_road_width",
    13: "regional.transport.avg_road_width",
    14: "regional.transport.large_station",
    15: "regional.transport.bus_stop",
    16: "regional.transport.interchange",
    17: "regional.transport.road_development",
    19: "regional.nature.sunlight",
    20: "regional.nature.view",
    21: "regional.nature.slope",
    22: "regional.nature.drainage",
    23: "regional.nature.terrain",
    25: "regional.land_improvement.site_improvement",
    27: "regional.public.school",
    28: "regional.public.market",
    29: "regional.public.park",
    30: "regional.public.tourism",
    31: "regional.public.parking",
    32: "regional.public.service_facility",
    34: "regional.special.utility",
    35: "regional.special.funeral",
    36: "regional.special.waste",
    38: "regional.pollution.environmental",
    40: "regional.other.other_factors",
}

#: 刻意不計入任何群組小計的細項列。
#: 表5-1 備註載明「使用分區、建蔽率、容積率修正併同於比較法調查估價表宗地個別
#: 因素考量調整修正」，所以第 6、7、8 列的等級照填、修正率填 0.00，但不進小計。
#: 第 40 列（其他影響因素）不列在這裡：它有自己的小計列（41），只是本案題目
#: 已預填 0.00，那是案件層級的事實，記在 kernel/fixtures 而不是版面對映。
TABLE5_1_ROWS_NOT_IN_SUBTOTAL = (6, 7, 8)

#: 八個群組的「百分比小計」列號 → 該群組涵蓋的細項列號。
#: 第 11 列不含 6、7、8，理由見 TABLE5_1_ROWS_NOT_IN_SUBTOTAL。
TABLE5_1_SUBTOTAL_ROWS: dict[int, tuple[int, ...]] = {
    11: (5, 9, 10),
    18: (12, 13, 14, 15, 16, 17),
    24: (19, 20, 21, 22, 23),
    26: (25,),
    33: (27, 28, 29, 30, 31, 32),
    37: (34, 35, 36),
    39: (38,),
    41: (40,),
}

#: 群組小計列的順序，與 kernel 的 group_order() 對應
TABLE5_1_SUBTOTAL_ROW_ORDER = (11, 18, 24, 26, 33, 37, 39, 41)

#: 影響地價區域因素總修正數
TABLE5_1_TOTAL_ROW = 42

#: 備註欄
TABLE5_1_REMARK_ROW_PER_SEGMENT = 43
TABLE5_1_REMARK_ROW_ALL_CASE = 44

#: B42 印的是 =(1)+(2)+(3)+(4)+(5)+(6)+(7)+(8)，那是說明文字不是公式
#: （(1) 不是合法的儲存格參照），不要覆寫。
TABLE5_1_DO_NOT_TOUCH = ("B42",)


# ---------- 表4 ----------

#: 「條件」欄的合併主格欄位。每個標的佔三欄。
TABLE4_COND_COL = {
    "benchmark": "D",
    0: "G",
    1: "K",
    2: "O",
}

#: 「差異率」欄。比準地沒有。
TABLE4_DIFF_COL = {
    0: "J",
    1: "N",
    2: "R",
}

#: 表頭。標籤印在左邊那一格，值填在右邊：
#: K1「估價基準日：」→ L1、O1「案號：」→ P1、
#: D2「比準地：宗地流水號」→ F2、H2/L2/P2「實例編號：」→ J2/N2/R2。
#: 這幾格題目都有給值，先前漏填（實測產出後逐格盤點才發現）。
TABLE4_CELL_BASE_DATE = "L1"
TABLE4_CELL_CASE_ID = "P1"
TABLE4_CELL_BENCHMARK_SERIAL = "F2"
TABLE4_EXAMPLE_NO_CELLS = {0: "J2", 1: "N2", 2: "R2"}

TABLE4_ROW_NORMAL_UNIT_PRICE = 5
TABLE4_ROW_TRANSACTION_DATE = 6
TABLE4_ROW_ADJUSTED_UNIT_PRICE = 7
TABLE4_ROW_SEGMENT = 8

#: 個別因素項目 7 到 25 的列號範圍（含端點）。題目未提供宗地個別條件資料，
#: 依表4 註記由地價查估單位辦理，這一段留空。
TABLE4_INDIVIDUAL_ROWS = tuple(range(9, 29))

TABLE4_ROW_INDIVIDUAL_TOTAL = 29

#: 第 30、31 列各有兩組值欄（左邊一組、右邊一組），與上面的三欄制不同。
#: 左：調整百分率絕對值加總 / 試算價格。右：價格形成因素之相近程度 / 比較標的權重。
TABLE4_DECISION_LEFT_COL = {0: "G", 1: "K", 2: "O"}
TABLE4_DECISION_RIGHT_COL = {0: "I", 1: "M", 2: "Q"}

TABLE4_ROW_ABS_SUM = 30
TABLE4_ROW_TRIAL_PRICE = 31

#: 比準地比較價格，G:R 單一合併格
TABLE4_BENCHMARK_PRICE_CELL = "G32"

TABLE4_ROW_REMARK_PER_SEGMENT = 33
TABLE4_REMARK_ALL_CASE_CELL = "D34"

#: xlsx 版的表4 沒有「比準地地價」（查估辦法第21條分段進位後的值）那一格，
#: 題目 PDF 版才有。算得出來但沒有欄位可填，寫進備註。
TABLE4_HAS_NO_LAND_PRICE_CELL = True


# ---------- 表3 ----------

TABLE3_CELL_YEAR = "B3"
TABLE3_CELL_SEGMENT_NO = "G3"
TABLE3_CELL_SEGMENT_RANGE = "L3"

#: 佈局 A（土地使用管制，第 4 到 9 列）：標籤在 D:G，值在 H:K。
TABLE3_VALUE_CELLS_A: dict[str, str] = {
    "regional.land_control.urban_plan": "H4",
    "regional.land_control.zoning": "H5",
    "regional.land_control.building_coverage": "H6",
    "regional.land_control.floor_area_ratio": "H7",
    "regional.land_control.build_prohibition": "H8",
    "regional.land_control.build_restriction": "H9",
}

#: 佈局 B（第 23 到 30 列）：標籤在 D:H，值在 I:K。
TABLE3_VALUE_CELLS_B: dict[str, str] = {
    "regional.transport.road_development": "I23",
    "regional.nature.sunlight": "I24",
    "regional.nature.view": "I25",
    "regional.nature.slope": "I26",
    "regional.nature.drainage": "I27",
    "regional.nature.terrain": "I28",
}

#: 主要道路那一列的結構特殊：F11 印「名稱：」、I11 印「寬度：」、K11 印「M」。
TABLE3_CELL_MAIN_ROAD_NAME = "G11"
TABLE3_CELL_MAIN_ROAD_WIDTH = "J11"

#: 區段內道路平均寬度：D12 是標籤，H12 印「M」，值填 G12。
TABLE3_CELL_AVG_ROAD_WIDTH = "G12"

#: 表3 每個細項的優劣等級欄與總級數欄。
#:
#: 新北市查估書表製作手冊第 3 章第 25 頁的「土地使用管制填載範例」顯示，
#: 每個細項名稱左邊有兩個窄欄，填「優劣等級／總級數」，
#: 例如「1 2 都市計畫(內外) 內」、「3 3 有無限制建築 有(限制整體開發)」、
#: 「5 5 建蔽率 尚未發佈」。
#:
#: 這也是為什麼手冊第 5 章第 42 頁要求表5-1 的等級「應與地價區段勘查表內
#: 所調查之基本資料及優劣等級相符」：勘查表本身就有等級欄。
#:
#: 表3 是雙欄版面。左半的大標籤在 A 欄，等級在 B、總級數在 C；
#: 右半的大標籤在 L 欄，等級在 M、總級數在 N。B 與 M 同寬（3.625），
#: 兩邊完全對稱。跨多列的細項（例如大型車站四列）等級欄是合併格，
#: 這裡記主格座標，`put()` 會自動導向。
#:
#: 「其他影響因素」沒有等級欄，它的 L40:N41 是整個合併掉的標籤格。
TABLE3_GRADE_CELLS = {
    # 左半：土地使用管制
    "regional.land_control.urban_plan": ("B4", "C4"),
    "regional.land_control.zoning": ("B5", "C5"),
    "regional.land_control.building_coverage": ("B6", "C6"),
    "regional.land_control.floor_area_ratio": ("B7", "C7"),
    "regional.land_control.build_prohibition": ("B8", "C8"),
    "regional.land_control.build_restriction": ("B9", "C9"),
    # 左半：交通運輸
    "regional.transport.main_road_width": ("B11", "C11"),
    "regional.transport.avg_road_width": ("B12", "C12"),
    "regional.transport.large_station": ("B13", "C13"),
    "regional.transport.bus_stop": ("B17", "C17"),
    "regional.transport.interchange": ("B19", "C19"),
    "regional.transport.road_development": ("B23", "C23"),
    # 左半：自然條件
    "regional.nature.sunlight": ("B24", "C24"),
    "regional.nature.view": ("B25", "C25"),
    "regional.nature.slope": ("B26", "C26"),
    "regional.nature.drainage": ("B27", "C27"),
    "regional.nature.terrain": ("B28", "C28"),
    # 左半：土地改良
    "regional.land_improvement.site_improvement": ("B31", "C31"),
    # 左半：公共建設（學校、市場、公園）
    "regional.public.school": ("B35", "C35"),
    "regional.public.market": ("B39", "C39"),
    "regional.public.park": ("B42", "C42"),
    # 右半：公共建設（觀光遊憩、停車場地、服務性設施）
    "regional.public.tourism": ("M4", "N4"),
    "regional.public.parking": ("M6", "N6"),
    "regional.public.service_facility": ("M8", "N8"),
    # 右半：特殊設施
    "regional.special.utility": ("M14", "N14"),
    "regional.special.funeral": ("M18", "N18"),
    "regional.special.waste": ("M22", "N22"),
    # 右半：環境污染
    "regional.pollution.environmental": ("M25", "N25"),
}

#: 表3 上沒有等級欄的細項。範本把它的標籤格連同等級欄一起合併掉了。
TABLE3_NO_GRADE_CELL = ("regional.other.other_factors",)

#: 土地改良的勾選文字。範本印的是 □，要勾的改成 ■。
TABLE3_CELL_IMPROVEMENT_LINE1 = "E31"
TABLE3_CELL_IMPROVEMENT_LINE2 = "E32"

#: 表3 專屬欄位（不在表5-1 的 29 項裡，但回填要填）。
#: Q42「建築密度」與 Q43「建築型態」是範本印好的標籤，值欄在右邊的
#: R42:V42 與 R43:V43。先前誤填在 Q 欄，把標籤蓋掉了。
TABLE3_CELL_BUILDING_DENSITY = "R42"
TABLE3_CELL_BUILDING_TYPE = "R43"

#: 土地利用現況：Q44:V44 是一整格圈選文字
#: 「○商業用　○住宅用　○工業用…」，要勾的把 ○ 改成 ●。
TABLE3_CELL_LAND_USE = "Q44"

#: 表3 上以百分比形式記載的細項。寫入時要加 % 尾綴，讀取時要把 % 去掉。
#: 寫入與讀取共用這一份宣告，先前只有 fill.py 有，讀取端若自己再寫一份會不同步。
TABLE3_PERCENT_FIELDS = (
    "regional.land_control.building_coverage",
    "regional.land_control.floor_area_ratio",
)

#: 從工作表名稱抓地價區段編號的樣式（例如「表3 P001-00」→「P001-00」）。
#: 抓不到就退回讀 TABLE3_CELL_SEGMENT_NO 那一格，兩者都沒有就報錯不猜。
TABLE3_SEGMENT_NO_PATTERN = r"P\d{3}-\d{2}"

#: 本案有 13 個細項是圈選未勾、距離空白。那些格子維持範本原狀不動，
#: 因為「沒有勾選」本身就是事實。清單放在這裡是為了讓讀程式的人知道
#: 這不是漏填。
TABLE3_UNCHECKED_FACTORS = (
    "regional.transport.large_station",
    "regional.transport.bus_stop",
    "regional.transport.interchange",
    "regional.public.school",
    "regional.public.market",
    "regional.public.park",
    "regional.public.tourism",
    "regional.public.parking",
    "regional.public.service_facility",
    "regional.special.utility",
    "regional.special.funeral",
    "regional.special.waste",
    "regional.pollution.environmental",
)


# ---------- 一致性自檢 ----------

def check_layout() -> list[str]:
    """對映表自身的一致性檢查。回傳問題清單，空的表示沒問題。

    這裡抓的是「對映表打錯了」，不是「案件算錯了」。
    """
    problems: list[str] = []

    if len(TABLE5_1_FACTOR_ROWS) != 29:
        problems.append(f"表5-1 應有 29 個細項列，實得 {len(TABLE5_1_FACTOR_ROWS)}")

    ids = list(TABLE5_1_FACTOR_ROWS.values())
    if len(set(ids)) != len(ids):
        dupes = sorted({x for x in ids if ids.count(x) > 1})
        problems.append(f"表5-1 有重複的 factor_id：{dupes}")

    covered: list[int] = []
    for rows in TABLE5_1_SUBTOTAL_ROWS.values():
        covered.extend(rows)
    if len(covered) != len(set(covered)):
        dupes = sorted({r for r in covered if covered.count(r) > 1})
        problems.append(f"同一個細項列被算進多個群組小計：{dupes}")

    expected_covered = set(TABLE5_1_FACTOR_ROWS) - set(TABLE5_1_ROWS_NOT_IN_SUBTOTAL)
    if set(covered) != expected_covered:
        missing = sorted(expected_covered - set(covered))
        extra = sorted(set(covered) - expected_covered)
        problems.append(
            f"群組小計涵蓋的列與預期不符。應計入卻沒有：{missing}；"
            f"不該計入卻有：{extra}（刻意排除的是 {list(TABLE5_1_ROWS_NOT_IN_SUBTOTAL)}）"
        )

    for r in TABLE5_1_ROWS_NOT_IN_SUBTOTAL:
        if r not in TABLE5_1_FACTOR_ROWS:
            problems.append(f"第 {r} 列列為不計入小計，但它不是細項列")

    if len(TABLE5_1_SUBTOTAL_ROWS) != 8:
        problems.append(f"表5-1 應有 8 個群組小計列，實得 {len(TABLE5_1_SUBTOTAL_ROWS)}")

    if tuple(sorted(TABLE5_1_SUBTOTAL_ROWS)) != tuple(sorted(TABLE5_1_SUBTOTAL_ROW_ORDER)):
        problems.append("TABLE5_1_SUBTOTAL_ROW_ORDER 與 TABLE5_1_SUBTOTAL_ROWS 的列號不一致")

    overlap = set(TABLE5_1_FACTOR_ROWS) & set(TABLE5_1_SUBTOTAL_ROWS)
    if overlap:
        problems.append(f"細項列與小計列重疊：{sorted(overlap)}")

    if TABLE5_1_TOTAL_ROW in TABLE5_1_FACTOR_ROWS or TABLE5_1_TOTAL_ROW in TABLE5_1_SUBTOTAL_ROWS:
        problems.append(f"總修正數列 {TABLE5_1_TOTAL_ROW} 與細項或小計列衝突")

    if len(TABLE4_INDIVIDUAL_ROWS) != 20:
        problems.append(
            f"表4 個別因素應涵蓋第 9 到 28 列共 20 列，實得 {len(TABLE4_INDIVIDUAL_ROWS)}"
        )

    for name, mapping in (
        ("TABLE5_1_PCT_COL", TABLE5_1_PCT_COL),
        ("TABLE4_DIFF_COL", TABLE4_DIFF_COL),
        ("TABLE4_DECISION_LEFT_COL", TABLE4_DECISION_LEFT_COL),
        ("TABLE4_DECISION_RIGHT_COL", TABLE4_DECISION_RIGHT_COL),
    ):
        if sorted(mapping) != [0, 1, 2]:
            problems.append(f"{name} 的鍵應為 0、1、2（三個比較標的），實得 {sorted(mapping)}")

    return problems
