"""樹林案的表4 計算鏈：區域因素 → 絕對值加總 → 權重 → 比準地比較價格 → 比準地地價。

前提：個別因素（表4 項目 7 到 25）以 0 計。題目未提供宗地個別條件資料，
而表4 註記載明那一段由地價查估單位辦理。局處填入個別因素之後，這裡每一個
數字都會變，包含權重的排序。

這份測試守住一個容易搞錯的定義。表4 的「調整百分率絕對值加總」是

    |交易日期調整| ＋ |區域因素總修正數| ＋ Σ|個別因素各項|

而不是「區域因素各細項的絕對值加總」。兩者在本案分別是 29.46／18.84／20.24
與 23.50／19.75／19.75，會導出不同的權重。依作業手冊 p.53，金山 Golden Case 的
|2.00|＋|0.00|＋|1|＋|2|＋|5|＋|3|＋|2|＝15.00 就是前者的結構。

用錯定義的後果是實際發生過的：先前的紀錄以為標的2 與標的3 打平在 19.75%，
權重需要人工判斷。改用正確定義後三個值都不同，權重不需要人工介入。
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from src.compute import (
    abs_sum_pct,
    benchmark_comparison_price,
    build_table5_1,
    round_up_by_tier,
    similarity_and_weights,
    trial_price,
)
from src.ruleset import load_ruleset

FACTS = json.loads(
    (Path(__file__).resolve().parent.parent / "fixtures" / "shulin_survey_facts.json").read_text(
        encoding="utf-8"
    )
)
RS = load_ruleset(FACTS["ruleset_regional"])
GIVEN = FACTS["table4_given"]["segments"]
COMPS = list(FACTS["comparables"])
EXPECTED = FACTS["expected"]


@pytest.fixture(scope="module")
def chain():
    """跑完整條鏈，回傳每個比較標的的中間值與最終價格。"""
    t5 = build_table5_1(
        RS,
        {seg: d["facts"] for seg, d in FACTS["segments"].items()},
        benchmark=FACTS["benchmark"],
        comparables=COMPS,
        excluded=tuple(FACTS["excluded_from_regional_subtotal"]),
        not_applicable=tuple(FACTS["not_applicable_factors"]),
    )
    rows = []
    for seg in COMPS:
        date = Decimal(str(GIVEN[seg]["date_adjustment_pct"]))
        regional = t5.totals[seg]
        # 個別因素以空列表代入，代表題目未提供
        s = abs_sum_pct([], date, regional)
        price, raw = trial_price(GIVEN[seg]["normal_unit_price"], date, regional, 0)
        rows.append(
            {
                "segment": seg,
                "date_pct": date,
                "regional_pct": regional,
                "abs_sum": s,
                "trial": price,
                "trial_raw": raw,
            }
        )
    sw = similarity_and_weights([r["abs_sum"] for r in rows])
    for r, (label, w) in zip(rows, sw):
        r["similarity"], r["weight_pct"] = label, w
    bcp = benchmark_comparison_price([r["trial"] for r in rows], [r["weight_pct"] for r in rows])
    return {"rows": rows, "bcp": bcp, "land_price": round_up_by_tier(bcp)}


def _row(chain, seg):
    return next(r for r in chain["rows"] if r["segment"] == seg)


@pytest.mark.parametrize("seg", COMPS)
def test_adjusted_unit_price_is_given_not_computed(seg):
    """調整至估價基準日單價是題目給的，不是我們算的。這裡驗它自洽。

    正常單價 × (1 + 交易日期調整百分率) 應該等於題目填的調整後單價。
    """
    g = GIVEN[seg]
    base = Decimal(str(g["normal_unit_price"]))
    pct = Decimal(str(g["date_adjustment_pct"]))
    got = (base * (Decimal(1) + pct / Decimal(100))).quantize(Decimal(1))
    assert int(got) == g["adjusted_unit_price"], seg


@pytest.mark.parametrize("seg", COMPS)
def test_table4_abs_sum_uses_date_plus_regional_total(seg, chain):
    """表4 那一格 = |日期| + |區域因素總修正數| + Σ|個別因素各項|。"""
    r = _row(chain, seg)
    assert r["abs_sum"] == Decimal(EXPECTED["table4_abs_sum_pct"][seg])
    # 個別因素為 0 時，就是前兩項相加
    assert r["abs_sum"] == abs(r["date_pct"]) + abs(r["regional_pct"])


def test_table4_abs_sum_differs_from_regional_abs_sum():
    """兩種絕對值加總必須是不同的數字，否則就是又搞混了。"""
    t4 = {k: Decimal(v) for k, v in EXPECTED["table4_abs_sum_pct"].items()}
    reg = {k: Decimal(v) for k, v in EXPECTED["regional_abs_sum_pct"].items()}
    assert t4 != reg
    # 區域因素那組有打平，表4 那組沒有
    assert len(set(reg.values())) == 2
    assert len(set(t4.values())) == 3


def test_no_tie_so_weights_need_no_manual_call(chain):
    """三個絕對值加總都不同，權重不需要人工判斷。

    這一條在防退回舊的誤解。若哪天真的打平了，這個 assert 會失敗，
    那時要回頭看作業手冊「惟需另配合蒐集資料可信度等綜合決定」那句。
    """
    sums = [r["abs_sum"] for r in chain["rows"]]
    assert len(set(sums)) == 3, f"絕對值加總出現打平：{sums}"


@pytest.mark.parametrize("seg", COMPS)
def test_weight_matches_verified_value(seg, chain):
    r = _row(chain, seg)
    exp = EXPECTED["weights"][seg]
    assert r["similarity"] == exp["similarity"]
    assert r["weight_pct"] == Decimal(exp["weight_pct"])


def test_smaller_abs_sum_gets_bigger_weight(chain):
    """絕對值加總越小代表越相近，權重越大。方向搞反會讓價格整個偏掉。"""
    ordered = sorted(chain["rows"], key=lambda r: r["abs_sum"])
    weights = [r["weight_pct"] for r in ordered]
    assert weights == [Decimal(50), Decimal(30), Decimal(20)]


@pytest.mark.parametrize("seg", COMPS)
def test_trial_price_matches_verified_value(seg, chain):
    assert _row(chain, seg)["trial"] == EXPECTED["trial_price"][seg]


def test_benchmark_comparison_price(chain):
    """161,577×50% + 206,885×30% + 170,337×20% = 176,921.4 → 176,921。"""
    assert chain["bcp"] == EXPECTED["benchmark_comparison_price"]


def test_benchmark_land_price_uses_tier_rounding(chain):
    """查估辦法第21條分段無條件進位：逾 10 萬元者進位至千位。"""
    assert chain["land_price"] == EXPECTED["benchmark_land_price"]
    assert chain["land_price"] >= chain["bcp"], "無條件進位不可能變小"
    assert chain["land_price"] % 1000 == 0


def test_weights_sum_to_100(chain):
    assert sum(r["weight_pct"] for r in chain["rows"]) == Decimal(100)
