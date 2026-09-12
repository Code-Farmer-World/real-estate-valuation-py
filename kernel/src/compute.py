"""加總與價格計算。

三條硬規則（皆有官方出處）：
1. 小計／合計是「各項直接相加」，不是連乘。
   佐證：作業手冊 p.96 表5-1 範例 0+(-36.16)+12.50+(-5.00)+2.25+13.75+10.00+(-2.50) = -5.16
2. 全程保留精度，只在最終取整。
   佐證：184763×1.02×1.13 = 212957.83 → 212,958（官方值）；
   若先用表上顯示的 188,459 續算會得 212,959，與官方不符。
3. 尾數規則分兩種：
   - 表4 比準地比較價格：四捨五入至個位數（作業手冊 p.53）
   - 表14 比準地地價／表6 宗地市價：分段無條件進位（查估辦法第21條）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any

from .classify import Grade, classify
from .matrix import Correction, lookup
from .ruleset import RuleSet, dec

ONE = Decimal(1)
HUNDRED = Decimal(100)


# ---------- 加總 ----------

def total_pct(corrections: list[Correction]) -> Decimal:
    """個別因素合計／區域因素總修正數：各項直接相加。"""
    return sum((c.pct for c in corrections), Decimal(0))


def abs_sum_pct(
    corrections: list[Correction],
    date_pct: Decimal | float = 0,
    regional_pct: Decimal | float = 0,
) -> Decimal:
    """調整百分率絕對值加總（作業手冊 p.53：各項調整百分率先取絕對值後加總）。

    Golden Case: |2.00| + |0.00| + |1|+|2|+|5|+|3|+|2| = 15.00
    """
    return (
        abs(dec(date_pct))
        + abs(dec(regional_pct))
        + sum((abs(c.pct) for c in corrections), Decimal(0))
    )


def similarity_and_weights(abs_sums: list[Decimal]) -> list[tuple[str, Decimal]]:
    """依「調整百分率絕對值加總」決定相近程度與權重。

    作業手冊 p.53 範例：3件 7%/10%/15% → 較高/普通/較低 → 50%/30%/20%
                       2件 7%/10%     → 較高/普通      → 70%/30%
                       1件            → 普通           → 100%
    加總愈多者權重愈少；惟手冊亦要求配合蒐集資料可信度綜合決定，故此為預設建議值。
    """
    n = len(abs_sums)
    presets = {
        1: [("普通", Decimal(100))],
        2: [("較高", Decimal(70)), ("普通", Decimal(30))],
        3: [("較高", Decimal(50)), ("普通", Decimal(30)), ("較低", Decimal(20))],
    }
    if n not in presets:
        raise ValueError(f"比較標的件數 {n} 超出辦法第19條規定之 1~3 件")

    order = sorted(range(n), key=lambda i: abs_sums[i])  # 加總小 → 相近程度高
    out: list[tuple[str, Decimal]] = [("", Decimal(0))] * n
    for rank, idx in enumerate(order):
        out[idx] = presets[n][rank]
    return out


# ---------- 尾數 ----------

def round_half_up(value: Decimal | float) -> int:
    """四捨五入至個位數（作業手冊 p.53，比準地比較價格）。"""
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def round_up_by_tier(value: Decimal | float) -> int:
    """查估辦法第21條分段無條件進位（比準地地價、宗地市價）。

    100元以下→個位；逾100至1000→十位；逾1000至10萬→百位；逾10萬→千位。
    """
    v = dec(value)
    if v <= 100:
        unit = Decimal(1)
    elif v <= 1000:
        unit = Decimal(10)
    elif v <= 100_000:
        unit = Decimal(100)
    else:
        unit = Decimal(1000)
    return int((v / unit).to_integral_value(rounding=ROUND_CEILING) * unit)


# ---------- 價格 ----------

def trial_price(
    normal_unit_price: Decimal | float,
    date_pct: Decimal | float,
    regional_pct: Decimal | float,
    individual_pct: Decimal | float,
) -> tuple[int, Decimal]:
    """試算價格。回傳 (顯示用整數, 未取整原值)。

    原值必須傳給下游，不可用取整後的值續算。
    """
    raw = (
        dec(normal_unit_price, field="表4 土地正常單價")
        * (ONE + dec(date_pct, field="表4 調整百分率（日期）") / HUNDRED)
        * (ONE + dec(regional_pct, field="表4 區域因素調整百分率") / HUNDRED)
        * (ONE + dec(individual_pct, field="表4 個別因素合計") / HUNDRED)
    )
    return round_half_up(raw), raw


# 權重合計的容差。書表上的權重是整數百分比，3 件比較標的各填 33% 就只有
# 99%——這是估價師的正常填法，不是錯誤。容差內按比例正規化後續算，並發警告；
# 超出容差才視為填載錯誤。
WEIGHT_TOLERANCE = Decimal(1)


def benchmark_comparison_price(
    trials: list[int],
    weights_pct: list[Decimal],
    *,
    warnings: list[str] | None = None,
) -> int:
    """比準地比較價格 = Σ(試算價格 × 權重)，四捨五入至個位數。

    權重合計不是 100% 時：容差（±1%）內按比例正規化並記錄警告，
    超出容差才 raise。`warnings` 傳進來就會把訊息 append 上去。
    """
    if len(trials) != len(weights_pct):
        raise ValueError("試算價格與權重數量不符")
    if not weights_pct:
        raise ValueError("沒有比較標的，無法計算比準地比較價格")

    tw = sum(weights_pct, Decimal(0))
    if tw <= 0:
        raise ValueError(f"權重合計必須為正數，實得 {tw}%")

    if tw != HUNDRED:
        if abs(tw - HUNDRED) > WEIGHT_TOLERANCE:
            raise ValueError(
                f"權重合計必須為 100%（容差 ±{WEIGHT_TOLERANCE}%），實得 {tw}%。"
                f"請確認表4 的權重欄是否誤讀或填錯。"
            )
        # 容差內：按比例正規化。不直接沿用原權重，否則加總 99% 會讓價格偏低 1%。
        msg = (
            f"表4 權重合計為 {tw}%，不是 100%（在 ±{WEIGHT_TOLERANCE}% 容差內）。"
            f"已按比例正規化後計算，建議人工確認權重欄。"
        )
        if warnings is not None:
            warnings.append(msg)
        weights_pct = [w * HUNDRED / tw for w in weights_pct]

    acc = sum((dec(t) * w / HUNDRED for t, w in zip(trials, weights_pct)), Decimal(0))
    return round_half_up(acc)


# ---------- 全鏈路 ----------

@dataclass
class FactorRow:
    factor_id: str
    label: str
    table4_row: int | None
    benchmark_value: Any
    comparable_value: Any
    benchmark_grade: Grade
    comparable_grade: Grade
    correction: Correction

    def as_evidence(self) -> dict:
        return {
            "細項": self.label,
            "比準地": f"{self.benchmark_value}（{self.benchmark_grade.label}）",
            "比較標的": f"{self.comparable_value}（{self.comparable_grade.label}）",
            "差異率": f"{self.correction.pct}%",
            "依據": [
                self.benchmark_grade.reason,
                self.comparable_grade.reason,
                self.correction.reason,
            ],
            "來源頁": self.correction.source_page,
        }


@dataclass
class ComparableResult:
    index: int
    rows: list[FactorRow]
    date_pct: Decimal
    regional_pct: Decimal
    individual_total_pct: Decimal
    abs_sum_pct: Decimal
    trial_price: int
    trial_price_raw: Decimal = field(repr=False)
    similarity: str = ""
    weight_pct: Decimal = Decimal(0)

    @property
    def nonzero(self) -> dict[str, Decimal]:
        return {r.factor_id: r.correction.pct for r in self.rows if r.correction.pct != 0}


def appraise_comparable(
    rs: RuleSet,
    benchmark_facts: dict[str, Any],
    comparable: dict[str, Any],
    *,
    only: list[str] | None = None,
) -> ComparableResult:
    """對單一比較標的跑完個別因素調整與試算價格。"""
    ids = only if only is not None else rs.factor_ids
    cfacts = comparable["facts"]

    rows: list[FactorRow] = []
    for fid in ids:
        if fid not in benchmark_facts or fid not in cfacts:
            continue  # 免修正項目（表4 以「-」表示），與差異率為 0 者區分
        f = rs[fid]
        bg = classify(f, benchmark_facts[fid])
        cg = classify(f, cfacts[fid])
        rows.append(
            FactorRow(
                factor_id=fid,
                label=f.label,
                table4_row=f.table4_row,
                benchmark_value=benchmark_facts[fid],
                comparable_value=cfacts[fid],
                benchmark_grade=bg,
                comparable_grade=cg,
                correction=lookup(f, bg.grade, cg.grade),
            )
        )

    corrections = [r.correction for r in rows]
    date_pct = dec(comparable.get("date_adjustment_pct", 0))
    regional_pct = dec(comparable.get("regional_adjustment_pct", 0))
    ind_total = total_pct(corrections)
    price, raw = trial_price(
        comparable["normal_unit_price"], date_pct, regional_pct, ind_total
    )

    return ComparableResult(
        index=comparable.get("index", 1),
        rows=rows,
        date_pct=date_pct,
        regional_pct=regional_pct,
        individual_total_pct=ind_total,
        abs_sum_pct=abs_sum_pct(corrections, date_pct, regional_pct),
        trial_price=price,
        trial_price_raw=raw,
    )


@dataclass
class Table4Result:
    comparables: list[ComparableResult]
    benchmark_comparison_price: int
    benchmark_land_price: int
    # 「算得出來但需要人工確認」的事項。與 raise 的差別：這些不阻擋計算，
    # 但必須讓審查員看到，不能靜默吞掉。
    warnings: list[str] = field(default_factory=list)


def appraise_table4(
    rs: RuleSet,
    case: dict[str, Any],
    *,
    weights_pct: list[Decimal] | None = None,
) -> Table4Result:
    """表4 全鏈路 → 比準地比較價格 → 表14 比準地地價（尾數進位）。"""
    bfacts = case["benchmark"]["facts"]
    results = [appraise_comparable(rs, bfacts, c) for c in case["comparables"]]

    if weights_pct is None:
        given = [c.get("weight_pct") for c in case["comparables"]]
        if all(g is not None for g in given):
            weights_pct = [dec(g) for g in given]
            for r, w in zip(results, weights_pct):
                r.weight_pct = w
                r.similarity = similarity_and_weights([x.abs_sum_pct for x in results])[
                    results.index(r)
                ][0]
        else:
            sw = similarity_and_weights([r.abs_sum_pct for r in results])
            weights_pct = [w for _, w in sw]
            for r, (lab, w) in zip(results, sw):
                r.similarity, r.weight_pct = lab, w
    else:
        for r, w in zip(results, weights_pct):
            r.weight_pct = w

    warnings: list[str] = []
    bcp = benchmark_comparison_price(
        [r.trial_price for r in results], weights_pct, warnings=warnings
    )
    return Table4Result(results, bcp, round_up_by_tier(bcp), warnings)


# ---------- 表5-1 產出 ----------
#
# 與 appraise_table4 的差別在方向。那條路是「已經有填好的表，重算一遍去比對」，
# 這條路是「表是空的，算出每一格該填什麼」。正式題目的表5-1 與表4 是空白待填，
# 而勘查表（表3）根本沒有優劣等級這一欄，所以沒有對照對象可比。
#
# 計算仍然全部在 kernel。api 只負責把結果轉成 JSON，xlsxform 只負責寫進格子。


def group_order(rs: RuleSet) -> list[str]:
    """群組的出現順序，供表5-1 的八個小計欄依序排列。

    取自規則集裡細項的定義順序（dict 保序），不另外寫死一份清單，
    這樣換行政區時順序自動跟著規則集走。
    """
    seen: list[str] = []
    for f in rs.factors.values():
        if f.group and f.group not in seen:
            seen.append(f.group)
    return seen


def group_subtotals(rs: RuleSet, corrections: dict[str, Correction]) -> dict[str, Decimal]:
    """按 factor.group 分組加總修正百分比，供表5-1 的「百分比小計」欄。

    `total_pct()` 是全部加總（表4 的個別因素合計要的是那個），表5-1 需要的是
    分成八個群組各自加總再相加。

    沒有出現在 `corrections` 裡的細項視為不計入，這涵蓋兩種情況：
    表5-1 備註說修正併同於表4 處理的三項（使用分區、建蔽率、容積率），
    以及本案不適用的細項（題目已預填「-」者）。
    """
    out = {g: Decimal(0) for g in group_order(rs)}
    for fid, c in corrections.items():
        g = rs[fid].group
        if g not in out:
            raise KeyError(f"{fid} 的群組 {g!r} 不在規則集的群組清單裡")
        out[g] += c.pct
    return out


@dataclass
class GradeCell:
    """表5-1 的一格優劣等級。

    `grade` 為 None 表示本案不適用這個細項，書表上填「-」。這與「等級是某個
    數字但修正率剛好為 0」不同，後者是四個區段同級的正常結果。
    """

    factor_id: str
    segment: str
    grade: int | None
    label: str
    reason: str
    source_page: int | None = None
    applicable: bool = True
    # 判級所依據的量測值。留著才能把依據講成一句完整的話
    # （「主要道路寬度 7m，落在未滿8m 這一級」），也才追溯得回勘查表。
    value: Any = None

    @property
    def text(self) -> str:
        """填進書表的文字。"""
        return "-" if self.grade is None else str(self.grade)


@dataclass
class CorrectionCell:
    """表5-1 的一格修正百分比。

    `counted` 為 False 表示這一格填 0.00 但不計入群組小計。刻意填 0 而不留空，
    才分得出「已移轉到表4 處理」與「漏填」。
    """

    factor_id: str
    segment: str
    pct: Decimal
    reason: str
    source_page: int | None = None
    counted: bool = True


@dataclass
class Table5_1Result:
    """表5-1 的全部格子。

    格數（樹林住宅 29 個細項、四個區段、三個比較標的）：
        grades       29 × 4 = 116
        corrections  29 × 3 =  87
        subtotals     8 × 3 =  24
        totals                 3
    """

    ruleset_id: str
    benchmark: str
    comparables: list[str]
    groups: list[str]
    grades: dict[tuple[str, str], GradeCell]
    corrections: dict[tuple[str, str], CorrectionCell]
    subtotals: dict[tuple[str, str], Decimal]
    totals: dict[str, Decimal]

    def grade(self, segment: str, factor_id: str) -> GradeCell:
        return self.grades[(segment, factor_id)]

    def correction(self, segment: str, factor_id: str) -> CorrectionCell:
        return self.corrections[(segment, factor_id)]

    def subtotal(self, segment: str, group: str) -> Decimal:
        return self.subtotals[(segment, group)]

    @property
    def cell_counts(self) -> dict[str, int]:
        return {
            "grades": len(self.grades),
            "corrections": len(self.corrections),
            "subtotals": len(self.subtotals),
            "totals": len(self.totals),
        }

    def abs_sum_pct(self, segment: str) -> Decimal:
        """該比較標的的區域因素調整百分率絕對值加總。

        只計入 counted 的格子。表4 的「調整百分率絕對值加總」還要再加上個別因素
        各項與日期調整，那一段在 abs_sum_pct() 函式處理。
        """
        return sum(
            (abs(c.pct) for (seg, _), c in self.corrections.items() if seg == segment and c.counted),
            Decimal(0),
        )


def build_table5_1(
    rs: RuleSet,
    facts_by_segment: dict[str, dict[str, Any]],
    *,
    benchmark: str,
    comparables: list[str],
    excluded: tuple[str, ...] = (),
    not_applicable: tuple[str, ...] = (),
) -> Table5_1Result:
    """從勘查事實算出表5-1 的每一格。

    參數：
        facts_by_segment  {區段編號: {factor_id: 量測值}}，四個區段都要有 29 項
        benchmark         比準地的區段編號
        comparables       比較標的的區段編號，依表上欄位順序
        excluded          修正併同於表4 處理者。等級照算，修正率填 0 且不計入小計
        not_applicable    本案不適用者。等級填「-」，修正率填 0 且不計入小計

    `excluded` 與 `not_applicable` 都不計入小計，差別在等級欄的填法。
    這個區分來自書表本身：表5-1 備註說前者的修正併同於表4，而後者是題目已經
    預填「-」表示不作評定。
    """
    ex, na = set(excluded), set(not_applicable)
    overlap = ex & na
    if overlap:
        raise ValueError(f"細項不能同時列為 excluded 與 not_applicable：{sorted(overlap)}")

    segments = [benchmark] + list(comparables)
    for seg in segments:
        if seg not in facts_by_segment:
            raise KeyError(f"缺少區段 {seg} 的勘查事實")
        missing = set(rs.factor_ids) - set(facts_by_segment[seg])
        if missing:
            raise KeyError(f"區段 {seg} 缺少 {len(missing)} 個細項的事實：{sorted(missing)[:5]}")

    grades: dict[tuple[str, str], GradeCell] = {}
    for seg in segments:
        facts = facts_by_segment[seg]
        for fid in rs.factor_ids:
            f = rs[fid]
            if fid in na:
                grades[(seg, fid)] = GradeCell(
                    factor_id=fid,
                    segment=seg,
                    grade=None,
                    label="-",
                    reason="本案不適用，書表填「-」（不作評定，非等級為 0）",
                    source_page=f.source_page,
                    applicable=False,
                    value=facts[fid],
                )
                continue
            g = classify(f, facts[fid])
            grades[(seg, fid)] = GradeCell(
                factor_id=fid,
                segment=seg,
                grade=g.grade,
                label=g.label,
                reason=g.reason,
                source_page=g.source_page,
                value=facts[fid],
            )

    corrections: dict[tuple[str, str], CorrectionCell] = {}
    for seg in comparables:
        for fid in rs.factor_ids:
            f = rs[fid]
            if fid in na:
                corrections[(seg, fid)] = CorrectionCell(
                    factor_id=fid,
                    segment=seg,
                    pct=Decimal(0),
                    reason="本案不適用，修正率 0.00 且不計入小計",
                    source_page=f.source_page,
                    counted=False,
                )
                continue
            if fid in ex:
                corrections[(seg, fid)] = CorrectionCell(
                    factor_id=fid,
                    segment=seg,
                    pct=Decimal(0),
                    reason="修正併同於比較法調查估價表宗地個別因素考量調整，本表以 0.00 計且不計入小計",
                    source_page=f.source_page,
                    counted=False,
                )
                continue
            c = lookup(f, grades[(benchmark, fid)].grade, grades[(seg, fid)].grade)
            corrections[(seg, fid)] = CorrectionCell(
                factor_id=fid,
                segment=seg,
                pct=c.pct,
                reason=c.reason,
                source_page=c.source_page,
            )

    groups = group_order(rs)
    subtotals: dict[tuple[str, str], Decimal] = {}
    totals: dict[str, Decimal] = {}
    for seg in comparables:
        counted = {
            fid: Correction(
                factor_id=fid,
                benchmark_grade=grades[(benchmark, fid)].grade or 0,
                comparable_grade=grades[(seg, fid)].grade or 0,
                pct=cell.pct,
                reason=cell.reason,
                source_page=cell.source_page,
            )
            for fid in rs.factor_ids
            if (cell := corrections[(seg, fid)]).counted
        }
        subs = group_subtotals(rs, counted)
        for g in groups:
            subtotals[(seg, g)] = subs[g]
        totals[seg] = sum(subs.values(), Decimal(0))

    return Table5_1Result(
        ruleset_id=rs.ruleset_id,
        benchmark=benchmark,
        comparables=list(comparables),
        groups=groups,
        grades=grades,
        corrections=corrections,
        subtotals=subtotals,
        totals=totals,
    )
