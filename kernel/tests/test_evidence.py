"""依據鏈與敘述的測試。

敘述是規則式的，不經過任何模型。這份測試守的是「每一格都講得出依據，
而且每次講的都一樣」。徵收案會被訴願，「為什麼這一格是第 5 級」必須答得出來。

三件事特別要守住：

1. 負號要講出方向。比較標的條件優於比準地時修正率為負，那不是 bug。
2. 不計入小計的兩種原因講法不同（移到表4 處理 vs 本案未予評定）。
3. 勘查表原載值與計算用值不同時要說明。少了那句，看到「容積率 200%」
   會對不上勘查表上的 260%。
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from src.compute import build_table5_1
from src.evidence import (
    REASON_MOVED_TO_TABLE4,
    REASON_NOT_APPLICABLE,
    build_evidence,
)
from src.ruleset import load_ruleset

FACTS = json.loads(
    (Path(__file__).resolve().parent.parent / "fixtures" / "shulin_survey_facts.json").read_text(
        encoding="utf-8"
    )
)
RS = load_ruleset(FACTS["ruleset_regional"])
EXCLUDED = tuple(FACTS["excluded_from_regional_subtotal"])
NOT_APPLICABLE = tuple(FACTS["not_applicable_factors"])
COMPS = list(FACTS["comparables"])
EXPECTED = FACTS["expected"]


@pytest.fixture(scope="module")
def evidence():
    t5 = build_table5_1(
        RS,
        {s: d["facts"] for s, d in FACTS["segments"].items()},
        benchmark=FACTS["benchmark"],
        comparables=COMPS,
        excluded=EXCLUDED,
        not_applicable=NOT_APPLICABLE,
    )
    return build_evidence(
        RS,
        t5,
        excluded=EXCLUDED,
        not_applicable=NOT_APPLICABLE,
        raw_by_segment={s: d.get("raw", {}) for s, d in FACTS["segments"].items()},
        overrides=FACTS["case_overrides"],
    )


def _factor(evidence, seg, fid):
    seg_ev = next(s for s in evidence if s.segment == seg)
    return next(f for f in seg_ev.factors if f.factor_id == fid)


# ---------- 覆蓋率 ----------


def test_every_factor_of_every_comparable_has_evidence(evidence):
    """29 細項 × 3 標的 = 87 列依據，一列都不能少。"""
    assert len(evidence) == len(COMPS)
    assert sum(len(s.factors) for s in evidence) == 87


def test_every_factor_has_a_narrative(evidence):
    for seg_ev in evidence:
        for fe in seg_ev.factors:
            assert fe.narrative().strip(), f"{seg_ev.segment} {fe.factor_id} 沒有敘述"
            assert fe.narrative().endswith("。"), fe.factor_id


def test_every_group_and_segment_has_a_narrative(evidence):
    for seg_ev in evidence:
        assert seg_ev.narrative().strip()
        assert len(seg_ev.groups) == 8
        for g in seg_ev.groups:
            assert g.narrative().strip()


def test_source_page_is_cited(evidence):
    """判級的敘述要指得回評價基準明細表第幾頁。"""
    for seg_ev in evidence:
        for fe in seg_ev.factors:
            if fe.factor_id in NOT_APPLICABLE:
                continue
            assert fe.source_page is not None, fe.factor_id
            assert f"第 {fe.source_page} 頁" in fe.narrative(), fe.factor_id


# ---------- 敘述的內容 ----------


def test_narrative_states_both_values_and_grades(evidence):
    """一句話要交代四件事：比準地的值與等級、比較標的的值與等級。"""
    fe = _factor(evidence, "P002-00", "regional.transport.main_road_width")
    text = fe.narrative()
    for expect in ("28m", "第 1 級", "7m", "第 5 級", "+15.00%"):
        assert expect in text, f"敘述缺少 {expect}：{text}"


def test_negative_correction_explains_direction(evidence):
    """負值要講出方向，否則會被當成 bug。

    P003-00 的道路規劃闢建程度是「全部規劃及闢建」（第 1 級），比比準地的
    「大部分規劃及闢建」（第 2 級）好，所以修正率是 -2.50%。
    """
    fe = _factor(evidence, "P003-00", "regional.transport.road_development")
    assert fe.correction_pct == Decimal("-2.5")
    text = fe.narrative()
    assert "-2.50%" in text
    assert "優於比準地" in text
    assert "往下修正" in text


def test_zero_correction_has_no_plus_sign(evidence):
    """0 不帶正號。「+0.00%」讀起來像刻意標記。"""
    fe = _factor(evidence, "P002-00", "regional.public.school")
    assert fe.correction_pct == 0
    assert "0.00%" in fe.narrative()
    assert "+0.00%" not in fe.narrative()


def test_absent_factor_is_described_as_none(evidence):
    """未勾選的細項要講成「無」而不是空白，那是事實不是漏填。"""
    fe = _factor(evidence, "P002-00", "regional.public.school")
    assert fe.comparable_value is None
    assert "無（未勾選或無此設施）" in fe.narrative()


# ---------- 兩種不計入小計的原因 ----------


def test_moved_to_table4_says_so(evidence):
    """使用分區、建蔽率、容積率：等級照判，但說明修正併同於表4。"""
    for fid in EXCLUDED:
        fe = _factor(evidence, "P002-00", fid)
        assert fe.counted is False
        assert fe.exclusion_reason == REASON_MOVED_TO_TABLE4
        assert REASON_MOVED_TO_TABLE4 in fe.narrative()
        assert fe.comparable_grade is not None, "這三項的等級仍要判出來"


def test_not_applicable_says_so(evidence):
    """其他影響因素：題目已預填「-」，敘述要講不作評定。"""
    for fid in NOT_APPLICABLE:
        fe = _factor(evidence, "P002-00", fid)
        assert fe.counted is False
        assert fe.comparable_grade is None
        text = fe.narrative()
        assert REASON_NOT_APPLICABLE in text
        assert "「-」" in text


def test_two_exclusion_reasons_are_different():
    """兩種原因的講法必須不同，混用會讓人以為是同一件事。"""
    assert REASON_MOVED_TO_TABLE4 != REASON_NOT_APPLICABLE


# ---------- 勘查表原載值與計算用值的差異 ----------


def test_override_is_explained_when_values_differ(evidence):
    """容積率勘查表原載 260%、計算用 200%，敘述要把這件事講出來。"""
    fe = _factor(evidence, "P002-00", "regional.land_control.floor_area_ratio")
    text = fe.narrative()
    assert "原載 260%" in text
    assert "200% 計算" in text
    assert "地價查估單位" in text


def test_override_note_is_omitted_when_values_match(evidence):
    """P002-00 的容積率原載就是 200%，與計算用值相同，不必多一句話。

    只有真的不同才產生說明，否則每一格都掛一句廢話。
    """
    fe = _factor(evidence, "P002-00", "regional.land_control.floor_area_ratio")
    # 比準地 P001-00 原載 260 所以有說明，但不該提到 P002-00 自己
    assert "P002-00 勘查表原載" not in fe.override_note


def test_no_override_note_without_raw_data():
    """沒傳 raw 就不編故事。"""
    t5 = build_table5_1(
        RS,
        {s: d["facts"] for s, d in FACTS["segments"].items()},
        benchmark=FACTS["benchmark"],
        comparables=COMPS,
        excluded=EXCLUDED,
        not_applicable=NOT_APPLICABLE,
    )
    ev = build_evidence(RS, t5, excluded=EXCLUDED, not_applicable=NOT_APPLICABLE)
    fe = _factor(ev, "P002-00", "regional.land_control.floor_area_ratio")
    assert fe.override_note == ""


# ---------- 群組與總修正數 ----------


def test_group_narrative_lists_members_and_skipped(evidence):
    seg_ev = next(s for s in evidence if s.segment == "P002-00")
    land = next(g for g in seg_ev.groups if g.group == "土地使用管制(1)")
    text = land.narrative()
    assert "3 個細項相加" in text
    assert "未列入計算" in text
    assert len(land.counted_factors) == 3
    assert len(land.skipped_factors) == 3


def test_transport_group_narrative_shows_the_nonzero_terms(evidence):
    seg_ev = next(s for s in evidence if s.segment == "P002-00")
    transport = next(g for g in seg_ev.groups if g.group == "交通運輸(2)")
    text = transport.narrative()
    assert "+23.50%" in text
    assert "主要道路寬度 +15.00%" in text
    assert "區段內道路平均寬度 +6.00%" in text


@pytest.mark.parametrize("seg", COMPS)
def test_segment_narrative_matches_verified_total(seg, evidence):
    seg_ev = next(s for s in evidence if s.segment == seg)
    expect = Decimal(EXPECTED["total_correction_pct"][seg])
    assert seg_ev.total_pct == expect
    assert f"{expect.quantize(Decimal('0.01')):+}%" in seg_ev.narrative()
    assert "交通運輸(2)" in seg_ev.narrative()


def test_segment_narrative_explains_the_zero_groups(evidence):
    """七個群組為 0 的理由要講出來，不能只顯示 0。"""
    seg_ev = next(s for s in evidence if s.segment == "P002-00")
    text = seg_ev.narrative()
    assert "其餘 7 個群組" in text
    assert "優劣等級相同" in text


# ---------- 可序列化 ----------


def test_to_dict_is_json_serialisable(evidence):
    payload = [s.to_dict() for s in evidence]
    text = json.dumps(payload, ensure_ascii=False)
    assert len(text) > 1000
    back = json.loads(text)
    assert back[0]["segment"] == COMPS[0]
    assert len(back[0]["factors"]) == 29
    assert len(back[0]["groups"]) == 8
    assert back[0]["factors"][0]["narrative"]


def test_to_dict_keeps_decimal_as_string(evidence):
    """百分比用字串傳，不要變成浮點數而失去精度。"""
    d = _factor(evidence, "P002-00", "regional.transport.main_road_width").to_dict()
    assert d["correction_pct"] == "15.00"
    assert isinstance(d["correction_pct"], str)
