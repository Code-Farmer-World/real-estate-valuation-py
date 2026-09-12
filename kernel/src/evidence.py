"""依據鏈的結構化輸出與敘述。

計算過程本來就每一格都帶依據（`Grade.reason`、`Correction.reason`、
`source_page`），但那些字串只存在記憶體裡。這個模組把它們攤成可序列化的列，
供 API 透出、前端顯示、寫進 xlsx 的「計算依據」工作表。

敘述是**規則式**的，不經過任何模型。理由是徵收案會被訴願，
「為什麼這一格是第 5 級」必須答得出來而且答案要每次都一樣。模型潤飾可以加在
這之上（把這裡產生的句子改寫得更通順），但不能取代它，也不能碰數字。

三層依據，對應審查時真正會被問的三個問題：

    這個等級是怎麼判的      量測值 → 級距條文 → 等級（附基準表頁碼）
    這個修正率是怎麼來的    比準地等級 + 比較標的等級 → 查 5×5 矩陣
    這個小計是怎麼加的      哪幾個細項相加，哪些刻意不計入
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .classify import unit_suffix
from .ruleset import RuleSet

#: 不計入群組小計的兩種原因，講法不同（書表上的填法也不同）
REASON_MOVED_TO_TABLE4 = "修正併同於比較法調查估價表宗地個別因素考量調整"
REASON_NOT_APPLICABLE = "本案未予評定"


@dataclass
class FactorEvidence:
    """一個細項、一個比較標的的完整依據。"""

    factor_id: str
    label: str
    group: str
    unit: str | None
    source_page: int | None

    benchmark_segment: str
    benchmark_value: Any
    benchmark_grade: int | None
    benchmark_label: str
    benchmark_reason: str

    comparable_segment: str
    comparable_value: Any
    comparable_grade: int | None
    comparable_label: str
    comparable_reason: str

    correction_pct: Decimal
    correction_reason: str
    counted: bool
    exclusion_reason: str = ""
    #: 勘查表原載值與計算用值不同時的說明。追溯時最需要這一句，
    #: 否則看到「容積率 200%」會對不上勘查表上寫的 260%。
    override_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "label": self.label,
            "group": self.group,
            "unit": self.unit,
            "source_page": self.source_page,
            "benchmark": {
                "segment": self.benchmark_segment,
                "value": _plain(self.benchmark_value),
                "grade": self.benchmark_grade,
                "grade_label": self.benchmark_label,
                "reason": self.benchmark_reason,
            },
            "comparable": {
                "segment": self.comparable_segment,
                "value": _plain(self.comparable_value),
                "grade": self.comparable_grade,
                "grade_label": self.comparable_label,
                "reason": self.comparable_reason,
            },
            "correction_pct": str(self.correction_pct),
            "correction_reason": self.correction_reason,
            "counted": self.counted,
            "exclusion_reason": self.exclusion_reason,
            "override_note": self.override_note,
            "narrative": self.narrative(),
        }

    def narrative(self) -> str:
        """把依據講成一段完整的話。

        刻意不用模型。這段話必須每次都一樣，而且每個數字都指得回基準表，
        否則被訴願時答不出來。
        """
        parts: list[str] = []
        b_desc = _value_with_unit(self.benchmark_value, self.unit)
        c_desc = _value_with_unit(self.comparable_value, self.unit)
        page = f"（評價基準明細表第 {self.source_page} 頁）" if self.source_page else ""

        if self.comparable_grade is None or self.benchmark_grade is None:
            parts.append(
                f"「{self.label}」{self.exclusion_reason or REASON_NOT_APPLICABLE}，"
                f"等級欄以「-」表示，修正率 0.00%，不列入群組小計。"
            )
            return "".join(parts)

        parts.append(
            f"比準地（{self.benchmark_segment}）的「{self.label}」為{b_desc}，"
            f"判為第 {self.benchmark_grade} 級（{self.benchmark_label}）{page}；"
        )
        parts.append(
            f"比較標的（{self.comparable_segment}）為{c_desc}，"
            f"判為第 {self.comparable_grade} 級（{self.comparable_label}）。"
        )
        if self.override_note:
            parts.append(self.override_note)
        parts.append(
            f"查修正矩陣第 {self.benchmark_grade} 列第 {self.comparable_grade} 欄，"
            f"得修正率 {_signed(self.correction_pct)}。"
        )
        if self.correction_pct < 0:
            parts.append(
                "此為負值，因為比較標的的條件優於比準地，價格須往下修正才能與比準地比較。"
            )
        if not self.counted:
            parts.append(f"惟{self.exclusion_reason}，本表不列入群組小計。")
        return "".join(parts)


@dataclass
class GroupEvidence:
    """一個群組小計的依據：哪幾項相加、哪些不計入。"""

    group: str
    segment: str
    subtotal_pct: Decimal
    counted_factors: list[tuple[str, Decimal]] = field(default_factory=list)
    skipped_factors: list[tuple[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "group": self.group,
            "segment": self.segment,
            "subtotal_pct": str(self.subtotal_pct),
            "counted": [{"label": lab, "pct": str(p)} for lab, p in self.counted_factors],
            "skipped": [{"label": lab, "reason": r} for lab, r in self.skipped_factors],
            "narrative": self.narrative(),
        }

    def narrative(self) -> str:
        if not self.counted_factors:
            return f"「{self.group}」本表無計入項目，小計 0.00%。"
        terms = "、".join(f"{lab} {_signed(p)}" for lab, p in self.counted_factors)
        text = (
            f"「{self.group}」小計 {_signed(self.subtotal_pct)}，"
            f"由 {len(self.counted_factors)} 個細項相加：{terms}。"
        )
        if self.skipped_factors:
            skipped = "、".join(lab for lab, _ in self.skipped_factors)
            text += f"另有 {skipped} 未列入計算（{self.skipped_factors[0][1]}）。"
        return text


@dataclass
class SegmentEvidence:
    """一個比較標的的完整依據：每個細項、每個群組、總修正數。"""

    segment: str
    factors: list[FactorEvidence]
    groups: list[GroupEvidence]
    total_pct: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment": self.segment,
            "total_pct": str(self.total_pct),
            "factors": [f.to_dict() for f in self.factors],
            "groups": [g.to_dict() for g in self.groups],
            "narrative": self.narrative(),
        }

    def narrative(self) -> str:
        nonzero = [g for g in self.groups if g.subtotal_pct != 0]
        text = (
            f"比較標的 {self.segment} 的影響地價區域因素總修正數為 "
            f"{_signed(self.total_pct)}，由 {len(self.groups)} 個群組小計相加。"
        )
        if nonzero:
            names = "、".join(f"{g.group} {_signed(g.subtotal_pct)}" for g in nonzero)
            zero_count = len(self.groups) - len(nonzero)
            text += f"其中 {names} 為非零；"
            if zero_count:
                text += (
                    f"其餘 {zero_count} 個群組因四個地價區段的優劣等級相同，"
                    f"查矩陣同級對同級得 0.00%。"
                )
        else:
            text += "所有群組的優劣等級皆與比準地相同，故總修正數為 0.00%。"
        return text


def build_evidence(
    rs: RuleSet,
    result: Any,
    *,
    excluded: tuple[str, ...] = (),
    not_applicable: tuple[str, ...] = (),
    raw_by_segment: dict[str, dict[str, Any]] | None = None,
    overrides: list[dict[str, Any]] | None = None,
) -> list[SegmentEvidence]:
    """把 `build_table5_1()` 的結果攤成依據鏈。

    `result` 只需要提供 `.benchmark`、`.comparables`、`.groups` 與
    `.grade()`／`.correction()`／`.subtotal()`／`.totals`，不依賴具體型別。

    `raw_by_segment` 與 `overrides` 給了才能說明「勘查表原載值與計算用值不同」
    這件事。少了它，看到敘述寫「容積率 200%」會對不上勘查表上的 260%。
    """
    ex, na = set(excluded), set(not_applicable)
    override_by_fid = {o["factor_id"]: o for o in overrides or []}
    out: list[SegmentEvidence] = []

    for seg in result.comparables:
        factors: list[FactorEvidence] = []
        for fid in rs.factor_ids:
            f = rs[fid]
            bg = result.grade(result.benchmark, fid)
            cg = result.grade(seg, fid)
            corr = result.correction(seg, fid)
            factors.append(
                FactorEvidence(
                    factor_id=fid,
                    label=f.label,
                    group=f.group,
                    unit=f.unit,
                    source_page=f.source_page,
                    benchmark_segment=result.benchmark,
                    benchmark_value=bg.value,
                    benchmark_grade=bg.grade,
                    benchmark_label=bg.label,
                    benchmark_reason=bg.reason,
                    comparable_segment=seg,
                    comparable_value=cg.value,
                    comparable_grade=cg.grade,
                    comparable_label=cg.label,
                    comparable_reason=cg.reason,
                    correction_pct=corr.pct,
                    correction_reason=corr.reason,
                    counted=corr.counted,
                    exclusion_reason=_exclusion_reason(fid, ex, na),
                    override_note=_override_note(
                        fid, seg, result.benchmark, override_by_fid, raw_by_segment, f.unit
                    ),
                )
            )

        groups: list[GroupEvidence] = []
        for group in result.groups:
            members = [fe for fe in factors if fe.group == group]
            groups.append(
                GroupEvidence(
                    group=group,
                    segment=seg,
                    subtotal_pct=result.subtotal(seg, group),
                    counted_factors=[
                        (fe.label, fe.correction_pct) for fe in members if fe.counted
                    ],
                    skipped_factors=[
                        (fe.label, fe.exclusion_reason or REASON_NOT_APPLICABLE)
                        for fe in members
                        if not fe.counted
                    ],
                )
            )

        out.append(
            SegmentEvidence(
                segment=seg, factors=factors, groups=groups, total_pct=result.totals[seg]
            )
        )
    return out


def _override_note(
    fid: str,
    segment: str,
    benchmark: str,
    overrides: dict[str, dict[str, Any]],
    raw_by_segment: dict[str, dict[str, Any]] | None,
    unit: str | None,
) -> str:
    """勘查表原載值與計算用值不同時的說明。

    只有真的不同才產生說明。本案容積率 P002-00 原載就是 200%，與計算用值相同，
    那一格不需要多一句話。
    """
    ov = overrides.get(fid)
    if not ov or not raw_by_segment:
        return ""
    parts = []
    for seg in (benchmark, segment):
        raw = (raw_by_segment.get(seg) or {}).get(fid)
        if raw is not None and raw != ov.get("value"):
            parts.append(f"{seg} 勘查表原載 {_value_with_unit(raw, unit)}")
    if not parts:
        return ""
    source = ov.get("source") or "案件層級覆寫"
    return f"（{'、'.join(parts)}，依{source}以 {_value_with_unit(ov.get('value'), unit)} 計算）"


def _exclusion_reason(fid: str, excluded: set[str], not_applicable: set[str]) -> str:
    if fid in excluded:
        return REASON_MOVED_TO_TABLE4
    if fid in not_applicable:
        return REASON_NOT_APPLICABLE
    return ""


def _signed(pct: Decimal) -> str:
    """百分比固定兩位小數，非零時帶正負號。

    負號很重要：比較標的條件優於比準地時修正率為負，那不是 bug，
    而且書表上要看得出方向。零不帶號，「+0.00%」讀起來像刻意標記。
    """
    q = pct.quantize(Decimal("0.01"))
    return f"{q}%" if q == 0 else f"{q:+}%"


def _value_with_unit(value: Any, unit: str | None) -> str:
    if value is None:
        return "無（未勾選或無此設施）"
    return f"{value}{unit_suffix(unit)}"


def _plain(value: Any) -> Any:
    """轉成可序列化的型別。"""
    if isinstance(value, Decimal):
        return str(value)
    return value
