"""樹林區普通住宅用地區域因素規則集的驗收。

這份規則集是「規則即資料」主張的第二個實例：新增 29 個細項時 kernel/ 的程式碼
一行都沒有改。測試要守住兩件事。

1. 規則集結構自身正確（0 ERROR、29 個細項、8 個群組）。
2. 拿正式題目的四張表3 重算，必須重現已驗證的數字。只做第 1 項不夠，那只證明
   規則集內部一致，不證明級距抄對了。

已驗證的期望值（2026-09-12，來源見 docs/ 與交接紀錄）：

    P002-00 比較標的1  總修正數 +23.50%   137,925 × 1.2350 = 170,337 元/㎡
    P003-00 比較標的2  總修正數 +14.75%   140,808 × 1.1475 = 161,577 元/㎡
    P004-00 比較標的3  總修正數 +14.75%   180,292 × 1.1475 = 206,885 元/㎡

八個群組裡只有交通運輸(2) 非零，其餘七組四個區段等級相同故修正率為 0。
"""

from decimal import Decimal

import pytest
from src.classify import classify
from src.matrix import lookup, matrix_cells
from src.ruleset import load_ruleset
from src.validate import check_ruleset, errors

RS = load_ruleset("shulin_residential_regional")

# 表5-1 備註：這三項併同於表4 宗地個別因素調整，區域因素不重複調整。
EXCLUDED = {
    "regional.land_control.zoning",
    "regional.land_control.building_coverage",
    "regional.land_control.floor_area_ratio",
}

# 四張表3 的實測值。四個區段只有三項不同，其餘共用。
# 未勾選的細項以 None 表示「無」，由各細項條文的「或無」落在哪一級決定等級：
# 便利類（車站、站牌、交流道、學校、市場、公園、觀光遊憩、停車、服務性設施）在第 5 級，
# 嫌惡類（電業、殯葬、廢棄物、環境污染）在第 1 級。
COMMON = {
    "regional.land_control.urban_plan": "都市計畫內",
    "regional.land_control.zoning": "第一種住宅區",
    "regional.land_control.building_coverage": 50,
    "regional.land_control.floor_area_ratio": 200,
    "regional.land_control.build_prohibition": "無",
    "regional.land_control.build_restriction": "無",
    "regional.nature.sunlight": "日照充分",
    "regional.nature.view": "景觀尚可",
    "regional.nature.slope": "坡度未滿5度",
    "regional.nature.drainage": "排水普通完善",
    "regional.nature.terrain": "地勢極平坦堅硬",
    "regional.land_improvement.site_improvement": 4,
    "regional.transport.large_station": None,
    "regional.transport.bus_stop": None,
    "regional.transport.interchange": None,
    "regional.public.school": None,
    "regional.public.market": None,
    "regional.public.park": None,
    "regional.public.tourism": None,
    "regional.public.parking": None,
    "regional.public.service_facility": None,
    "regional.special.utility": None,
    "regional.special.funeral": None,
    "regional.special.waste": None,
    "regional.pollution.environmental": None,
    "regional.other.other_factors": "普通",
}

# 主要道路寬度、區段內道路平均寬度、區段內道路規劃及闢建程度
DIFF = {
    "P001-00": (28, 12, "大部分規劃及闢建"),
    "P002-00": (7, 6, "部分規劃及闢建"),
    "P003-00": (10, 7, "全部規劃及闢建"),
    "P004-00": (10, 7, "全部規劃及闢建"),
}

BENCHMARK = "P001-00"
COMPARABLES = ("P002-00", "P003-00", "P004-00")

# 表4 已給的「調整至估價基準日單價(元/M2)」，不是算出來的
ADJUSTED_PRICE = {"P002-00": 137925, "P003-00": 140808, "P004-00": 180292}

EXPECTED_TOTAL = {
    "P002-00": Decimal("23.50"),
    "P003-00": Decimal("14.75"),
    "P004-00": Decimal("14.75"),
}
EXPECTED_TRIAL = {"P002-00": 170337, "P003-00": 161577, "P004-00": 206885}

EXPECTED_GROUPS = {
    "土地使用管制(1)": 6,
    "交通運輸(2)": 6,
    "自然條件(3)": 5,
    "土地改良(4)": 1,
    "公共建設(5)": 6,
    "特殊設施(6)": 3,
    "環境污染(7)": 1,
    "其他影響因素(8)": 1,
}


def _facts(seg):
    main_w, avg_w, road_dev = DIFF[seg]
    d = dict(COMMON)
    d["regional.transport.main_road_width"] = main_w
    d["regional.transport.avg_road_width"] = avg_w
    d["regional.transport.road_development"] = road_dev
    return d


def _grades():
    return {seg: {fid: classify(RS[fid], _facts(seg)[fid]).grade for fid in RS.factor_ids} for seg in DIFF}


def test_no_structural_errors():
    found = errors(check_ruleset(RS))
    assert found == [], "\n".join(str(f) for f in found)


def test_factor_count_and_scope():
    assert len(RS) == 29
    assert RS.scope["district"] == "新北市樹林區"
    assert RS.scope["land_use"] == "普通住宅用地"
    assert RS.scope["factor_kind"] == "regional"


def test_group_distribution():
    """8 個群組，分佈須與表5-1 範本一致（群組小計是 8 格 × 3 個標的）。"""
    got = {}
    for f in RS.factors.values():
        got[f.group] = got.get(f.group, 0) + 1
    assert got == EXPECTED_GROUPS


def test_all_116_grade_cells_are_classifiable():
    """29 細項 × 4 區段 = 116 格等級都要判得出來，不能有細項因為缺級距而拋錯。

    其中 26 個細項四個區段等級相同（修正率必為 0），但 116 格等級都要填，
    不能留空，所以每一格都必須判得動。
    """
    grades = _grades()
    cells = sum(len(v) for v in grades.values())
    assert cells == 116
    for seg, per in grades.items():
        for fid, g in per.items():
            assert 1 <= g <= RS[fid].grade_count, f"{seg} {fid} 等級 {g} 超出範圍"


@pytest.mark.parametrize("seg", COMPARABLES)
def test_total_correction_matches_verified_value(seg):
    grades = _grades()
    total = sum(
        lookup(RS[fid], grades[BENCHMARK][fid], grades[seg][fid]).pct
        for fid in RS.factor_ids
        if fid not in EXCLUDED
    )
    assert total == EXPECTED_TOTAL[seg]


@pytest.mark.parametrize("seg", COMPARABLES)
def test_trial_price_matches_verified_value(seg):
    grades = _grades()
    total = sum(
        lookup(RS[fid], grades[BENCHMARK][fid], grades[seg][fid]).pct
        for fid in RS.factor_ids
        if fid not in EXCLUDED
    )
    base = Decimal(ADJUSTED_PRICE[seg])
    trial = (base * (Decimal(1) + total / Decimal(100))).quantize(Decimal("1"))
    assert int(trial) == EXPECTED_TRIAL[seg]


@pytest.mark.parametrize("seg", COMPARABLES)
def test_only_transport_group_is_nonzero(seg):
    """其餘七個群組四個區段等級相同，小計必須是 0。

    這一條在防的是「某個細項的級距抄錯，害得原本應該同級的四個區段被判成不同級」。
    那種錯誤不會讓總修正數變成離譜的數字，只會悄悄多出幾個百分點。
    """
    grades = _grades()
    subtotals = {}
    for fid in RS.factor_ids:
        if fid in EXCLUDED:
            continue
        f = RS[fid]
        subtotals[f.group] = subtotals.get(f.group, Decimal(0)) + lookup(
            f, grades[BENCHMARK][fid], grades[seg][fid]
        ).pct
    nonzero = {g: v for g, v in subtotals.items() if v != 0}
    assert nonzero == {"交通運輸(2)": EXPECTED_TOTAL[seg]}


def test_other_factors_is_seven_grade_and_uses_explicit_cells():
    """其他影響因素是全表唯一的七級制，矩陣必須用 cells 明列。

    基準表印的是 3.33／6.67／10／13.33／16.67／20，那是 20×k/6 四捨五入到小數
    第二位的結果。linear_step 3.33 會算出 6.66 而與基準表不符，所以這裡守住
    matrix.kind 不被改回 linear_step。
    """
    f = RS["regional.other.other_factors"]
    assert f.grade_count == 7
    assert f.matrix["kind"] == "cells"
    cells = matrix_cells(f)
    assert cells[0][6] == f.max_range == Decimal("20")
    assert cells[0][2] == Decimal("6.67")
    assert cells[0][2] != Decimal("3.33") * 2  # linear_step 會給 6.66


def test_hazard_and_amenity_absent_directions_are_opposite():
    """嫌惡設施與便利設施的「無」判在相反的等級，編規則集時最容易複製貼上出錯。"""
    for fid in ("regional.public.school", "regional.public.market", "regional.public.parking"):
        assert classify(RS[fid], None).grade == 5, f"{fid} 便利設施「無」應為第 5 級"
    for fid in (
        "regional.special.utility",
        "regional.special.funeral",
        "regional.special.waste",
        "regional.pollution.environmental",
    ):
        assert classify(RS[fid], None).grade == 1, f"{fid} 嫌惡設施「無」應為第 1 級"


def test_band_semantics_min_inclusive_max_exclusive():
    """主要道路寬度的級距邊界：28 判優、27.99 判稍優。min 含、max 不含。"""
    f = RS["regional.transport.main_road_width"]
    assert classify(f, 28).grade == 1
    assert classify(f, Decimal("27.99")).grade == 2
    assert classify(f, 8).grade == 4
    assert classify(f, Decimal("7.99")).grade == 5


def test_build_restriction_refuses_to_guess():
    """有無限制建築是三級制，「有」分不出屬部分限制或整體開發，必須報錯不猜。"""
    f = RS["regional.land_control.build_restriction"]
    assert f.grade_count == 3
    assert classify(f, "無").grade == 1
    with pytest.raises(ValueError):
        classify(f, "有")
