"""樹林區普通住宅用地區域因素規則集的驗收。

這份規則集是「規則即資料」主張的第二個實例：新增 29 個細項時 kernel/ 的程式碼
一行都沒有改。測試要守住兩件事。

1. 規則集結構自身正確（0 ERROR、29 個細項、8 個群組）。
2. 拿正式題目的四張表3 重算，必須重現已驗證的數字。只做第 1 項不夠，那只證明
   規則集內部一致，不證明級距抄對了。

案件事實一律從 kernel/fixtures/shulin_survey_facts.json 讀，不在測試裡另寫一份。
那份 JSON 是整條鏈的唯一輸入，期望值也記在它的 expected 區塊，改動事實就會
自動反映到這裡。

已驗證的期望值（2026-09-12）：

    P002-00 比較標的1  總修正數 +23.50%   137,925 × 1.2350 = 170,337 元/㎡
    P003-00 比較標的2  總修正數 +14.75%   140,808 × 1.1475 = 161,577 元/㎡
    P004-00 比較標的3  總修正數 +14.75%   180,292 × 1.1475 = 206,885 元/㎡

八個群組裡只有交通運輸(2) 非零，其餘七組四個區段等級相同故修正率為 0。
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from src.classify import classify
from src.matrix import lookup, matrix_cells
from src.ruleset import load_ruleset
from src.validate import check_ruleset, errors

FACTS_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "shulin_survey_facts.json"
FACTS = json.loads(FACTS_PATH.read_text(encoding="utf-8"))

RS = load_ruleset(FACTS["ruleset_regional"])

BENCHMARK = FACTS["benchmark"]
COMPARABLES = tuple(FACTS["comparables"])

# 兩種不計入群組小計的情況，差別在填表時的寫法：
#   EXCLUDED       表5-1 備註說修正併同於表4 宗地個別因素，等級照填數字
#   NOT_APPLICABLE 題目已預填「-」與 0.00，等級欄填「-」而不是級數
EXCLUDED = frozenset(FACTS["excluded_from_regional_subtotal"])
NOT_APPLICABLE = frozenset(FACTS["not_applicable_factors"])
SKIP_SUBTOTAL = EXCLUDED | NOT_APPLICABLE

EXPECTED = FACTS["expected"]
EXPECTED_TOTAL = {k: Decimal(v) for k, v in EXPECTED["total_correction_pct"].items()}
EXPECTED_TRIAL = EXPECTED["trial_price"]
EXPECTED_REGIONAL_ABS_SUM = {k: Decimal(v) for k, v in EXPECTED["regional_abs_sum_pct"].items()}

ADJUSTED_PRICE = {
    seg: d["adjusted_unit_price"]
    for seg, d in FACTS["table4_given"]["segments"].items()
    if "adjusted_unit_price" in d
}

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


def _graded_factors():
    """要判級的細項：29 項扣掉本案不適用的那些。"""
    return [fid for fid in RS.factor_ids if fid not in NOT_APPLICABLE]


def _grades():
    """{區段: {factor_id: 等級}}，不適用的細項不出現在裡面。"""
    out = {}
    for seg, d in FACTS["segments"].items():
        out[seg] = {fid: classify(RS[fid], d["facts"][fid]).grade for fid in _graded_factors()}
    return out


def _total(seg, grades):
    return sum(
        lookup(RS[fid], grades[BENCHMARK][fid], grades[seg][fid]).pct
        for fid in RS.factor_ids
        if fid not in SKIP_SUBTOTAL
    )


# ---------- 規則集結構 ----------


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


# ---------- 事實 JSON 與規則集的一致性 ----------


def test_facts_cover_every_factor():
    """四個區段的 facts 都要涵蓋 29 個細項，多一個少一個都要被抓到。"""
    for seg, d in FACTS["segments"].items():
        assert set(d["facts"]) == set(RS.factor_ids), seg


def test_grade_cell_count_is_116():
    """29 細項 × 4 區段 = 116 格等級欄都要有內容，不能留空。

    其中 112 格是判出來的等級數字，4 格是本案不適用的「-」
    （其他影響因素，題目已預填）。26 個細項四個區段等級相同（修正率必為 0），
    但等級欄一律要填。
    """
    grades = _grades()
    numeric = sum(len(v) for v in grades.values())
    dash = len(NOT_APPLICABLE) * len(FACTS["segments"])
    assert numeric == 112, numeric
    assert dash == 4, dash
    assert numeric + dash == 116

    for seg, per in grades.items():
        for fid, g in per.items():
            assert 1 <= g <= RS[fid].grade_count, f"{seg} {fid} 等級 {g} 超出範圍"


def test_not_applicable_factor_is_not_classifiable_by_design():
    """本案不適用的細項，事實是 null 而條文沒有對應類別，classify 應該報錯。

    這是刻意的：引擎不為「沒有評定」猜一個等級。填表時填「-」，
    那個決定記在 fixtures 的 not_applicable_factors，不是靠引擎推論。
    """
    assert NOT_APPLICABLE == {"regional.other.other_factors"}
    for seg in FACTS["segments"]:
        for fid in NOT_APPLICABLE:
            assert FACTS["segments"][seg]["facts"][fid] is None
            with pytest.raises(ValueError):
                classify(RS[fid], None)


# ---------- 重現已驗證的數字 ----------


@pytest.mark.parametrize("seg", COMPARABLES)
def test_total_correction_matches_verified_value(seg):
    assert _total(seg, _grades()) == EXPECTED_TOTAL[seg]


@pytest.mark.parametrize("seg", COMPARABLES)
def test_trial_price_matches_verified_value(seg):
    total = _total(seg, _grades())
    base = Decimal(ADJUSTED_PRICE[seg])
    trial = (base * (Decimal(1) + total / Decimal(100))).quantize(Decimal("1"))
    assert int(trial) == EXPECTED_TRIAL[seg]


@pytest.mark.parametrize("seg", COMPARABLES)
def test_regional_abs_sum_matches_verified_value(seg):
    """表5-1 內部的絕對值加總：29 個細項各自修正率取絕對值後相加。

    這不是表4 那一格。表4 的「調整百分率絕對值加總」是
    |交易日期調整| ＋ |區域因素總修正數| ＋ Σ|個別因素各項|，定義不同，
    見 fixtures 的 table4_abs_sum_note。
    """
    grades = _grades()
    got = sum(
        abs(lookup(RS[fid], grades[BENCHMARK][fid], grades[seg][fid]).pct)
        for fid in RS.factor_ids
        if fid not in SKIP_SUBTOTAL
    )
    assert got == EXPECTED_REGIONAL_ABS_SUM[seg]


@pytest.mark.parametrize("seg", COMPARABLES)
def test_only_transport_group_is_nonzero(seg):
    """其餘七個群組四個區段等級相同，小計必須是 0。

    這一條在防的是「某個細項的級距抄錯，害得原本應該同級的四個區段被判成不同級」。
    那種錯誤不會讓總修正數變成離譜的數字，只會悄悄多出幾個百分點。
    """
    grades = _grades()
    subtotals = {}
    for fid in RS.factor_ids:
        if fid in SKIP_SUBTOTAL:
            continue
        f = RS[fid]
        subtotals[f.group] = subtotals.get(f.group, Decimal(0)) + lookup(
            f, grades[BENCHMARK][fid], grades[seg][fid]
        ).pct
    nonzero = {g: v for g, v in subtotals.items() if v != 0}
    assert nonzero == {EXPECTED["nonzero_group"]: EXPECTED_TOTAL[seg]}


# ---------- 容易抄錯的地方 ----------


def test_other_factors_is_seven_grade_and_uses_explicit_cells():
    """其他影響因素是全表唯一的七級制，矩陣必須用 cells 明列。

    基準表印的是 3.33／6.67／10／13.33／16.67／20，那是 20×k/6 四捨五入到小數
    第二位的結果。linear_step 3.33 會算出 6.66 而與基準表不符，所以這裡守住
    matrix.kind 不被改回 linear_step。本案雖然不適用這一項，規則仍要正確。
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


def test_bureau_verbal_rule_on_floor_area_ratio_is_recorded():
    """容積率一律用 200% 是局處口頭指示，原值必須留在 raw 裡才追溯得回去。

    表3 原填 P001 260%、P002 200%、P003 260%、P004 260%（已用座標核對）。
    facts 一律 200，所以四個區段同級、修正率 0。
    """
    fid = "regional.land_control.floor_area_ratio"
    raws = {seg: d["raw"].get(fid) for seg, d in FACTS["segments"].items()}
    assert raws == {"P001-00": 260, "P002-00": 200, "P003-00": 260, "P004-00": 260}
    for seg, d in FACTS["segments"].items():
        assert d["facts"][fid] == 200, seg
    grades = _grades()
    assert len({grades[seg][fid] for seg in FACTS["segments"]}) == 1
