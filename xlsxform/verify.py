"""產出後的自我驗證。

回答「這些數字憑什麼可信」。做法是把活版寫進 xlsx 的 Excel 公式所描述的關係，
套在定版的數值上重算一次，兩者不一致就是有一邊寫錯了。

這不是取代測試，而是讓每一次產出都自帶證據。測試證明程式在開發機上是對的，
這份報告證明「這一份交出去的檔案」內部一致。

⚠️ 為什麼不直接讀活版的公式計算結果：`openpyxl` 寫入公式後檔案裡沒有 cached
value，要在 Excel、Numbers 或 Google Sheets 開啟才會算。所以這裡改用「公式描述
的關係」去驗定版的數值，Excel 開啟活版時會得到同樣的結果。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import openpyxl

from . import layout


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append(Check(name, passed, detail))

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "total": len(self.checks),
            "failed": len(self.failures),
            "checks": [c.to_dict() for c in self.checks],
        }

    def summary_lines(self) -> list[str]:
        out = [
            f"驗證項目 {len(self.checks)} 項，通過 {len(self.checks) - len(self.failures)} 項，"
            f"未通過 {len(self.failures)} 項"
        ]
        for c in self.failures:
            out.append(f"  ✗ {c.name}：{c.detail}")
        return out


def _visible(path: Path, title: str):
    wb = openpyxl.load_workbook(path)
    return wb[title]


def _d(ws, coord: str) -> Decimal:
    raw = ws[coord].value
    return Decimal(str(raw if raw is not None else 0))


def verify_outputs(
    *,
    table5_final: Path,
    table5_live: Path,
    table4_final: Path,
    table4_live: Path,
    expected: dict[str, Any],
    comparables: list[str],
    ruleset_findings: dict[str, int],
) -> Report:
    """比對活版公式與定版數值，並核對已驗證的數字。"""
    r = Report()
    t5 = _visible(table5_final, layout.SHEET_TABLE5_1)
    t5l = _visible(table5_live, layout.SHEET_TABLE5_1)
    t4 = _visible(table4_final, layout.SHEET_TABLE4)
    t4l = _visible(table4_live, layout.SHEET_TABLE4)

    r.add(
        "規則集自檢無 ERROR",
        ruleset_findings.get("errors", 0) == 0,
        f"ERROR {ruleset_findings.get('errors', 0)}、WARN {ruleset_findings.get('warnings', 0)}"
        f"（WARN 為住宅用地內政部上限表尚未編碼，屬已知限制）",
    )
    layout_problems = layout.check_layout()
    r.add(
        "版面對映自檢無問題",
        not layout_problems,
        "; ".join(layout_problems) if layout_problems else "格位對映與規則集的細項一致",
    )

    # 格數。優劣等級是兩欄：級數與等級文字（新北手冊第 5 章第 42 頁），
    # 所以 116 個細項格對應 232 格。只檢級數會漏掉整個文字欄。
    grade_cols = ["C"] + [layout.TABLE5_1_GRADE_COL[i] for i in range(len(comparables))]
    label_cols = [layout.TABLE5_1_GRADE_LABEL_COL["benchmark"]] + [
        layout.TABLE5_1_GRADE_LABEL_COL[i] for i in range(len(comparables))
    ]
    blanks = [
        f"{c}{row}"
        for row in layout.TABLE5_1_FACTOR_ROWS
        for c in grade_cols + label_cols
        if t5[f"{c}{row}"].value in (None, "")
    ]
    r.add(
        "表5-1 的 116 格優劣等級（級數與等級文字兩欄）皆已填寫",
        not blanks,
        f"空白格：{blanks[:5]}" if blanks else "232 格全數有值（116 級數 ＋ 116 等級文字）",
    )

    # 群組小計 == 各細項之和（活版 =SUM(...) 的關係）
    bad: list[str] = []
    for i in range(len(comparables)):
        col = layout.TABLE5_1_PCT_COL[i]
        for row, members in layout.TABLE5_1_SUBTOTAL_ROWS.items():
            want = sum((_d(t5, f"{col}{m}") for m in members), Decimal(0))
            if _d(t5, f"{col}{row}") != want:
                bad.append(f"{col}{row}")
    r.add(
        "群組小計等於各細項相加",
        not bad,
        f"不符：{bad}" if bad else "24 格小計全數相符（對應活版的 =SUM 公式）",
    )

    # 總修正數 == 八個小計之和
    bad = []
    for i in range(len(comparables)):
        col = layout.TABLE5_1_PCT_COL[i]
        want = sum(
            (_d(t5, f"{col}{row}") for row in layout.TABLE5_1_SUBTOTAL_ROW_ORDER), Decimal(0)
        )
        if _d(t5, f"{col}{layout.TABLE5_1_TOTAL_ROW}") != want:
            bad.append(f"{col}{layout.TABLE5_1_TOTAL_ROW}")
    r.add("總修正數等於八個群組小計相加", not bad, f"不符：{bad}" if bad else "3 格全數相符")

    # 活版真的寫了公式
    missing = [
        f"{layout.TABLE5_1_PCT_COL[i]}{row}"
        for i in range(len(comparables))
        for row in list(layout.TABLE5_1_SUBTOTAL_ROW_ORDER) + [layout.TABLE5_1_TOTAL_ROW]
        if not str(t5l[f"{layout.TABLE5_1_PCT_COL[i]}{row}"].value or "").startswith("=SUM(")
    ]
    r.add(
        "活版的小計與總修正數為 Excel 公式",
        not missing,
        f"缺公式：{missing[:5]}" if missing else "24 格小計與 3 格總修正數皆為 =SUM 公式",
    )

    # 表4：絕對值加總、試算價格、比準地比較價格
    bad = []
    for i, seg in enumerate(comparables):
        cond = layout.TABLE4_COND_COL[i]
        diff = layout.TABLE4_DIFF_COL[i]
        left = layout.TABLE4_DECISION_LEFT_COL[i]
        want_abs = abs(_d(t4, f"{diff}{layout.TABLE4_ROW_TRANSACTION_DATE}")) + abs(
            _d(t4, f"{diff}{layout.TABLE4_ROW_SEGMENT}")
        )
        if _d(t4, f"{left}{layout.TABLE4_ROW_ABS_SUM}") != want_abs:
            bad.append(f"{seg} 絕對值加總")
        price = _d(t4, f"{cond}{layout.TABLE4_ROW_ADJUSTED_UNIT_PRICE}")
        regional = _d(t4, f"{diff}{layout.TABLE4_ROW_SEGMENT}")
        individual = _d(t4, f"{cond}{layout.TABLE4_ROW_INDIVIDUAL_TOTAL}")
        want_trial = (price * (1 + regional) * (1 + individual)).quantize(Decimal(1))
        if _d(t4, f"{left}{layout.TABLE4_ROW_TRIAL_PRICE}") != want_trial:
            bad.append(f"{seg} 試算價格")
    r.add(
        "表4 絕對值加總與試算價格符合公式關係",
        not bad,
        f"不符：{bad}" if bad else "三個比較標的全數相符",
    )

    acc = Decimal(0)
    for i in range(len(comparables)):
        left = layout.TABLE4_DECISION_LEFT_COL[i]
        right = layout.TABLE4_DECISION_RIGHT_COL[i]
        acc += _d(t4, f"{left}{layout.TABLE4_ROW_TRIAL_PRICE}") * _d(
            t4, f"{right}{layout.TABLE4_ROW_TRIAL_PRICE}"
        )
    got_bcp = _d(t4, layout.TABLE4_BENCHMARK_PRICE_CELL)
    r.add(
        "比準地比較價格等於試算價格的加權平均",
        got_bcp == acc.quantize(Decimal(1)),
        f"表上 {got_bcp}、重算 {acc.quantize(Decimal(1))}",
    )

    missing = [
        c
        for c in (
            layout.TABLE4_BENCHMARK_PRICE_CELL,
            f"{layout.TABLE4_DECISION_LEFT_COL[0]}{layout.TABLE4_ROW_ABS_SUM}",
            f"{layout.TABLE4_DECISION_LEFT_COL[0]}{layout.TABLE4_ROW_TRIAL_PRICE}",
        )
        if not str(t4l[c].value or "").startswith("=")
    ]
    r.add(
        "活版的表4 計算欄為 Excel 公式",
        not missing,
        f"缺公式：{missing}" if missing else "絕對值加總、試算價格、比準地比較價格皆為公式",
    )

    # 與已驗證的數字核對
    bad = []
    for i, seg in enumerate(comparables):
        col = layout.TABLE5_1_PCT_COL[i]
        got = _d(t5, f"{col}{layout.TABLE5_1_TOTAL_ROW}") * 100
        want = Decimal(expected["total_correction_pct"][seg])
        if got != want:
            bad.append(f"{seg} 總修正數 {got} != {want}")
        left = layout.TABLE4_DECISION_LEFT_COL[i]
        got_trial = int(_d(t4, f"{left}{layout.TABLE4_ROW_TRIAL_PRICE}"))
        if got_trial != expected["trial_price"][seg]:
            bad.append(f"{seg} 試算價格 {got_trial} != {expected['trial_price'][seg]}")
    if int(got_bcp) != expected["benchmark_comparison_price"]:
        bad.append(f"比準地比較價格 {int(got_bcp)} != {expected['benchmark_comparison_price']}")
    r.add(
        "與已驗證的數字一致",
        not bad,
        "; ".join(bad) if bad else "總修正數、試算價格、比準地比較價格全數相符",
    )

    return r
