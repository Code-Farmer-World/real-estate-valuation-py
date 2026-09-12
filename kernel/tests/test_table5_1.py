"""build_table5_1() 的測試：從勘查事實算出表5-1 的每一格。

這條路與 appraise_table4() 方向相反。那條是「已有填好的表，重算去比對」，
這條是「表是空的，算出每一格該填什麼」。正式題目的表5-1 與表4 空白待填，
而勘查表（表3）根本沒有優劣等級這一欄，所以沒有對照對象。

案件事實從 kernel/fixtures/shulin_survey_facts.json 讀，與
test_shulin_residential.py 共用同一份輸入。
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from src.compute import build_table5_1, group_order, group_subtotals
from src.matrix import Correction
from src.ruleset import load_ruleset

FACTS = json.loads(
    (Path(__file__).resolve().parent.parent / "fixtures" / "shulin_survey_facts.json").read_text(
        encoding="utf-8"
    )
)
RS = load_ruleset(FACTS["ruleset_regional"])

BENCH = FACTS["benchmark"]
COMPS = list(FACTS["comparables"])
EXCLUDED = tuple(FACTS["excluded_from_regional_subtotal"])
NOT_APPLICABLE = tuple(FACTS["not_applicable_factors"])
FACTS_BY_SEG = {seg: d["facts"] for seg, d in FACTS["segments"].items()}
EXPECTED = FACTS["expected"]


@pytest.fixture(scope="module")
def result():
    return build_table5_1(
        RS,
        FACTS_BY_SEG,
        benchmark=BENCH,
        comparables=COMPS,
        excluded=EXCLUDED,
        not_applicable=NOT_APPLICABLE,
    )


# ---------- 格數 ----------


def test_cell_counts(result):
    """29 細項 × 4 區段 = 116 格等級；× 3 標的 = 87 格修正率；
    8 群組 × 3 標的 = 24 格小計；3 格總修正數。"""
    assert result.cell_counts == {
        "grades": 116,
        "corrections": 87,
        "subtotals": 24,
        "totals": 3,
    }
    assert result.cell_counts["grades"] == EXPECTED["grade_cells"]
    assert result.cell_counts["corrections"] == EXPECTED["correction_cells"]
    assert result.cell_counts["subtotals"] == EXPECTED["subtotal_cells"]


def test_every_grade_cell_has_text(result):
    """116 格等級欄都要有內容，不能留空。不適用者填「-」。"""
    for (seg, fid), cell in result.grades.items():
        assert cell.text, f"{seg} {fid} 的等級欄是空的"
        assert cell.reason, f"{seg} {fid} 沒有依據字串"


# ---------- 重現已驗證的數字 ----------


@pytest.mark.parametrize("seg", COMPS)
def test_total_matches_verified_value(seg, result):
    assert result.totals[seg] == Decimal(EXPECTED["total_correction_pct"][seg])


@pytest.mark.parametrize("seg", COMPS)
def test_only_transport_group_is_nonzero(seg, result):
    nonzero = {g: result.subtotal(seg, g) for g in result.groups if result.subtotal(seg, g) != 0}
    assert nonzero == {EXPECTED["nonzero_group"]: Decimal(EXPECTED["total_correction_pct"][seg])}


@pytest.mark.parametrize("seg", COMPS)
def test_abs_sum_matches_verified_value(seg, result):
    assert result.abs_sum_pct(seg) == Decimal(EXPECTED["abs_sum_pct"][seg])


def test_subtotals_add_up_to_total(result):
    """八個群組小計相加必須等於總修正數，這是書表上 =(1)+...+(8) 那一格的定義。"""
    for seg in COMPS:
        assert sum((result.subtotal(seg, g) for g in result.groups), Decimal(0)) == result.totals[seg]


# ---------- 兩種不計入小計的情況 ----------


def test_not_applicable_grade_is_dash_and_not_counted(result):
    """本案不適用者：等級填「-」、修正率 0.00、不計入小計。"""
    for fid in NOT_APPLICABLE:
        for seg in [BENCH] + COMPS:
            g = result.grade(seg, fid)
            assert g.grade is None
            assert g.text == "-"
            assert g.applicable is False
        for seg in COMPS:
            c = result.correction(seg, fid)
            assert c.pct == Decimal(0)
            assert c.counted is False


def test_excluded_keeps_grade_but_is_not_counted(result):
    """移到表4 處理者：等級照填數字、修正率 0.00、不計入小計。

    刻意填 0 而不留空，才分得出「已移轉」與「漏填」。
    """
    for fid in EXCLUDED:
        for seg in [BENCH] + COMPS:
            g = result.grade(seg, fid)
            assert g.grade is not None, fid
            assert g.applicable is True
            assert g.text.isdigit()
        for seg in COMPS:
            c = result.correction(seg, fid)
            assert c.pct == Decimal(0)
            assert c.counted is False
            assert "併同" in c.reason


def test_excluded_would_change_the_total_if_counted(result):
    """反面驗證：使用分區、建蔽率、容積率若計入，總修正數會不同。

    這一條在確認「不計入」是真的有效果，而不是剛好三項都是 0。
    本案四個區段這三項同級所以修正率本來就是 0，因此這裡驗的是等級確實算出來了
    （有數字可以查矩陣），只是刻意不計入。
    """
    for fid in EXCLUDED:
        bench_grade = result.grade(BENCH, fid).grade
        assert bench_grade is not None
        for seg in COMPS:
            assert result.grade(seg, fid).grade == bench_grade, (
                f"{fid} 在 {seg} 與比準地不同級，那麼「不計入」就會影響答案，"
                f"需要重新確認表5-1 備註的處理方式"
            )


# ---------- 分組 ----------


def test_group_order_follows_ruleset(result):
    assert result.groups == group_order(RS)
    assert result.groups == [
        "土地使用管制(1)",
        "交通運輸(2)",
        "自然條件(3)",
        "土地改良(4)",
        "公共建設(5)",
        "特殊設施(6)",
        "環境污染(7)",
        "其他影響因素(8)",
    ]


def test_group_subtotals_sums_by_group():
    corr = {
        "regional.transport.main_road_width": Correction(
            "regional.transport.main_road_width", 1, 5, Decimal("15"), "r"
        ),
        "regional.transport.avg_road_width": Correction(
            "regional.transport.avg_road_width", 3, 5, Decimal("6"), "r"
        ),
        "regional.nature.sunlight": Correction(
            "regional.nature.sunlight", 1, 2, Decimal("2.5"), "r"
        ),
    }
    got = group_subtotals(RS, corr)
    assert got["交通運輸(2)"] == Decimal("21")
    assert got["自然條件(3)"] == Decimal("2.5")
    assert got["土地使用管制(1)"] == Decimal(0)
    assert set(got) == set(group_order(RS)), "沒有出現的群組也要有 0，書表上那一格要填"


# ---------- 輸入檢查 ----------


def test_missing_segment_raises():
    with pytest.raises(KeyError, match="缺少區段"):
        build_table5_1(
            RS,
            {BENCH: FACTS_BY_SEG[BENCH]},
            benchmark=BENCH,
            comparables=COMPS,
            not_applicable=NOT_APPLICABLE,
        )


def test_missing_factor_raises():
    facts = {seg: dict(v) for seg, v in FACTS_BY_SEG.items()}
    facts[COMPS[0]].pop("regional.nature.sunlight")
    with pytest.raises(KeyError, match="缺少 1 個細項"):
        build_table5_1(
            RS,
            facts,
            benchmark=BENCH,
            comparables=COMPS,
            not_applicable=NOT_APPLICABLE,
        )


def test_excluded_and_not_applicable_cannot_overlap():
    with pytest.raises(ValueError, match="不能同時列為"):
        build_table5_1(
            RS,
            FACTS_BY_SEG,
            benchmark=BENCH,
            comparables=COMPS,
            excluded=("regional.other.other_factors",),
            not_applicable=("regional.other.other_factors",),
        )
