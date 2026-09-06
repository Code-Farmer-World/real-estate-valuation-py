"""分級：fact -> 優劣等級。

純函式，不碰檔案、不碰 AI。每次回傳都帶 reason，供 provenance UI 顯示
「這個等級是依哪一條級距判出來的」。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .ruleset import Factor, dec

ABSENT_TOKENS = {"無", "", "-", "－", "無此設施"}


@dataclass(frozen=True)
class Grade:
    factor_id: str
    grade: int
    label: str
    reason: str
    source_page: int | None = None

    def __int__(self) -> int:
        return self.grade


def _is_absent(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() in ABSENT_TOKENS:
        return True
    return False


def _band_contains(band: dict, v: Decimal) -> bool:
    """min 含、max 不含。只有 min = 以上；只有 max = 未滿。"""
    lo = band.get("min")
    hi = band.get("max")
    if lo is not None and v < dec(lo):
        return False
    if hi is not None and v >= dec(hi):
        return False
    return lo is not None or hi is not None


def _band_desc(band: dict, unit: str | None) -> str:
    u = {"m": "m", "m2": "m²", "percent": "%"}.get(unit or "", "")
    lo, hi = band.get("min"), band.get("max")
    if "or_ranges" in band:
        parts = [_band_desc(r, unit) for r in band["or_ranges"]]
        return " 或 ".join(parts)
    if lo is not None and hi is not None:
        return f"{lo}{u}以上未滿{hi}{u}"
    if lo is not None:
        return f"{lo}{u}以上"
    if hi is not None:
        return f"未滿{hi}{u}"
    return "（無級距條件）"


def classify(factor: Factor, value: Any) -> Grade:
    c = factor.classifier
    kind = c["type"]

    if kind == "numeric_bands":
        return _classify_numeric(factor, value)
    if kind == "ordered_category":
        return _classify_category(factor, value)
    raise ValueError(f"{factor.factor_id}: 未支援的 classifier type {kind!r}")


def _classify_numeric(factor: Factor, value: Any) -> Grade:
    c = factor.classifier
    bands = c["bands"]

    if _is_absent(value):
        for b in bands:
            if b.get("absent"):
                return Grade(
                    factor.factor_id, b["grade"], factor.label_of(b["grade"]),
                    f"值為「無」，條文明文含「或無」→ 第{b['grade']}級",
                    factor.source_page,
                )
        raise ValueError(
            f"{factor.factor_id}（{factor.label}）: 值為「無」，"
            f"但級距條文未載明「或無」，無法判級。"
            f"此為已知待確認事項，需人工判定或補充規則。"
        )

    v = dec(value)
    for b in bands:
        if "or_ranges" in b:
            if any(_band_contains(r, v) for r in b["or_ranges"]):
                return Grade(
                    factor.factor_id, b["grade"], factor.label_of(b["grade"]),
                    f"{value}{factor.unit or ''} 落在「{_band_desc(b, factor.unit)}」→ 第{b['grade']}級",
                    factor.source_page,
                )
            continue
        if _band_contains(b, v):
            return Grade(
                factor.factor_id, b["grade"], factor.label_of(b["grade"]),
                f"{value}{factor.unit or ''} 落在「{_band_desc(b, factor.unit)}」→ 第{b['grade']}級",
                factor.source_page,
            )

    raise ValueError(
        f"{factor.factor_id}（{factor.label}）: 值 {value} 不落在任何級距，"
        f"級距可能有缺口。請跑 validate.check_ruleset()。"
    )


def _classify_category(factor: Factor, value: Any) -> Grade:
    c = factor.classifier
    mode = c.get("match", "exact")
    s = "" if value is None else str(value).strip()

    for cat in c["categories"]:
        for want in cat["values"]:
            hit = (s == want) if mode == "exact" else (want in s)
            if hit:
                how = "完全相符" if mode == "exact" else "包含關鍵字"
                return Grade(
                    factor.factor_id, cat["grade"], factor.label_of(cat["grade"]),
                    f"「{s}」{how}「{want}」→ 第{cat['grade']}級",
                    factor.source_page,
                )

    raise ValueError(
        f"{factor.factor_id}（{factor.label}）: 值「{s}」不符合任何類別。"
        f"可接受值：{[v for cat in c['categories'] for v in cat['values']]}"
    )


def classify_worst(factor: Factor, values: list[Any]) -> Grade:
    """多設施取最劣（等級數字最大者）。

    依據：作業手冊 p.24「同一細項有多個設施存在，則以對當地地價影響最大者填寫」。
    Golden Case 佐證：電業設施 變電所700m(稍劣) + 儲油槽440m(劣) → 表5-2 填「劣」。
    """
    if factor.classifier.get("aggregation") != "worst":
        raise ValueError(f"{factor.factor_id} 未宣告 aggregation=worst，不應呼叫 classify_worst")
    graded = [classify(factor, v) for v in values]
    worst = max(graded, key=lambda g: g.grade)
    return Grade(
        worst.factor_id, worst.grade, worst.label,
        f"多設施取最劣：{[g.grade for g in graded]} → 第{worst.grade}級（{worst.reason}）",
        worst.source_page,
    )
