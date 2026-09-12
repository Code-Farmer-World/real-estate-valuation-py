"""從勘查事實到填好的 xlsx：可重用的組裝邏輯。

CLI 與 API 都走這裡，避免兩份邏輯各自漂移。這一層是唯一同時知道 kernel 與
xlsxform 的地方，相依方向由它決定（xlsxform 的其他模組不 import kernel），
比照 pdfform 的既有慣例。

`api/` 從這裡取用而不是自己組裝，因為一旦 API 自己算，
「每個數字都指得回官方文件」的追溯鏈就斷在那一層。
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from kernel.src.compute import (
    abs_sum_pct,
    benchmark_comparison_price,
    build_table5_1,
    round_up_by_tier,
    similarity_and_weights,
    trial_price,
)
from kernel.src.evidence import build_evidence
from kernel.src.ruleset import load_ruleset
from kernel.src.validate import check_ruleset, errors

from . import fill, layout
from .evidence_sheet import add_evidence_sheet
from .verify import verify_outputs
from .read import apply_case_overrides, read_table3
from .write import duplicate_sheet, load_template, save, the_visible_sheet

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FACTS = ROOT / "kernel" / "fixtures" / "shulin_survey_facts.json"

#: 官方範本的檔名。帶「的副本」是題目原始檔名，兩種都找。
TEMPLATE_CANDIDATES = {
    "table3": ("表3地價區段勘查表.xlsx 的副本.xlsx", "表3地價區段勘查表.xlsx"),
    "table5": (
        "表5影響地價區域因素分析明細表(住宅用地).xlsx 的副本.xlsx",
        "表5影響地價區域因素分析明細表(住宅用地).xlsx",
    ),
    "table4": ("表4比較法調查估價表.xlsx 的副本.xlsx", "表4比較法調查估價表.xlsx"),
}

OUTPUT_STEM = {
    "table3": "表3地價區段勘查表",
    "table5": "表5影響地價區域因素分析明細表(住宅用地)",
    "table4": "表4比較法調查估價表",
}


def find_template(templates_dir: Path, key: str) -> Path:
    for name in TEMPLATE_CANDIDATES[key]:
        p = templates_dir / name
        if p.exists():
            return p
    raise FileNotFoundError(
        f"在 {templates_dir} 找不到 {key} 的範本。找過：{TEMPLATE_CANDIDATES[key]}"
    )


def compute_all(facts: dict) -> dict:
    """跑完整條計算鏈。回傳給 fill 用的普通資料結構。"""
    rs = load_ruleset(facts["ruleset_regional"])
    findings = check_ruleset(rs)
    errs = errors(findings)
    if errs:
        raise SystemExit(
            "規則集自檢有 ERROR，拒絕產表：\n" + "\n".join(str(e) for e in errs)
        )

    t5 = build_table5_1(
        rs,
        {seg: d["facts"] for seg, d in facts["segments"].items()},
        benchmark=facts["benchmark"],
        comparables=facts["comparables"],
        excluded=tuple(facts["excluded_from_regional_subtotal"]),
        not_applicable=tuple(facts["not_applicable_factors"]),
    )

    given = facts["table4_given"]["segments"]
    comps = list(facts["comparables"])

    regional_pct, abs_sums, trials = {}, {}, {}
    for seg in comps:
        date = Decimal(str(given[seg]["date_adjustment_pct"]))
        reg = t5.totals[seg]
        regional_pct[seg] = reg
        # 個別因素題目未提供，以空列表代入即為 0
        abs_sums[seg] = abs_sum_pct([], date, reg)
        trials[seg], _ = trial_price(given[seg]["normal_unit_price"], date, reg, 0)

    sw = similarity_and_weights([abs_sums[s] for s in comps])
    similarity = {seg: lab for seg, (lab, _) in zip(comps, sw)}
    weights = {seg: w for seg, (_, w) in zip(comps, sw)}

    bcp = benchmark_comparison_price([trials[s] for s in comps], [weights[s] for s in comps])

    evidence = build_evidence(
        rs,
        t5,
        excluded=tuple(facts["excluded_from_regional_subtotal"]),
        not_applicable=tuple(facts["not_applicable_factors"]),
        raw_by_segment={seg: d.get("raw", {}) for seg, d in facts["segments"].items()},
        overrides=facts.get("case_overrides"),
    )

    return {
        "ruleset": rs,
        "ruleset_findings": {
            "errors": len(errs),
            "warnings": len(findings) - len(errs),
        },
        "table5_1": t5,
        "evidence": evidence,
        "table4": {
            "benchmark": facts["benchmark"],
            "comparables": comps,
            "given": given,
            "benchmark_parcel": given.get(facts["benchmark"], {}).get("parcel"),
            "appraisal_base_date": facts["table4_given"].get("appraisal_base_date"),
            "case_id": facts["table4_given"].get("case_id"),
            "benchmark_parcel_serial": facts["table4_given"].get("benchmark_parcel_serial"),
            "regional_pct": regional_pct,
            "abs_sum_pct": abs_sums,
            "similarity": similarity,
            "weight_pct": weights,
            "trial_price": trials,
            "benchmark_comparison_price": bcp,
            "benchmark_land_price": round_up_by_tier(bcp),
        },
    }


def write_table3(facts: dict, template: Path, out: Path) -> Path:
    wb = load_template(template, out)
    ws = the_visible_sheet(wb, expect_title=layout.SHEET_TABLE3)
    segments = [facts["benchmark"]] + list(facts["comparables"])
    titles = [layout.TABLE3_SHEET_TITLE.format(segment=s) for s in segments]
    sheets = duplicate_sheet(wb, ws, titles)
    for sheet, seg in zip(sheets, segments):
        fill.fill_table3(
            sheet, seg, facts["segments"][seg], year_period=facts["year_period"]
        )
    return save(wb, out)


def write_table5(facts: dict, computed: dict, template: Path, out: Path, *, live: bool) -> tuple[Path, dict]:
    wb = load_template(template, out)
    ws = the_visible_sheet(wb, expect_title=layout.SHEET_TABLE5_1)
    example_no = {
        seg: str(d["example_no"])
        for seg, d in facts["table4_given"]["segments"].items()
        if "example_no" in d
    }
    counts = fill.fill_table5_1(
        ws,
        computed["table5_1"],
        case_id=facts["case_id"],
        example_no=example_no,
        live=live,
    )
    # 官方書表只有數字，沒有地方寫「這一格為什麼是這個值」。另開一張表把依據
    # 攤出來，與書表放在同一個檔案，審查或訴願時不會分家。
    add_evidence_sheet(
        wb,
        computed["evidence"],
        case_id=facts["case_id"],
        ruleset_id=computed["table5_1"].ruleset_id,
        notes=[n for n in (facts.get("not_applicable_reason"), facts.get("excluded_reason")) if n],
    )
    return save(wb, out), counts


def write_table4(computed: dict, template: Path, out: Path, *, live: bool) -> Path:
    wb = load_template(template, out)
    ws = the_visible_sheet(wb, expect_title=layout.SHEET_TABLE4)
    fill.fill_table4(ws, computed["table4"], live=live)
    return save(wb, out)


def load_facts(settings_path: Path, from_xlsx: Path | None) -> dict:
    """組出勘查事實。

    `settings_path` 那份 JSON 提供勘查表上沒有的資訊：案號、比準地是哪個區段、
    表4 已給的交易實例資料（正常單價、交易日期、調整百分率）、以及
    `case_overrides`。

    `from_xlsx` 給了就用填好的表3 xlsx 覆蓋 `segments` 區塊，沒給就直接用
    JSON 裡的（人工核對版本）。兩條路徑往下走的程式完全相同。
    """
    facts = json.loads(settings_path.read_text(encoding="utf-8"))
    if from_xlsx is None:
        return facts

    read = read_table3(from_xlsx)
    segments = apply_case_overrides(read["segments"], facts.get("case_overrides"))

    expected = set([facts["benchmark"]] + list(facts["comparables"]))
    got = set(segments)
    if got != expected:
        raise SystemExit(
            f"表3 xlsx 讀到的區段 {sorted(got)} 與案件設定的 {sorted(expected)} 不符。"
            f"請確認上傳的檔案是本案的勘查表。"
        )

    for seg, data in segments.items():
        merged = dict(facts["segments"].get(seg, {}))
        merged.update(
            {
                "raw": data["raw"],
                "facts": data["facts"],
                "segment_range": data.get("segment_range") or merged.get("segment_range"),
                "table3_only": data.get("table3_only") or merged.get("table3_only"),
                # extras 是路名與土地改良勾選項目。漏傳的話回填表3 時那幾格會消失，
                # 因為 reader 產出的 raw 是型別轉換後的數值，解析不出路名。
                "extras": data.get("extras") or merged.get("extras"),
                "source": data.get("source"),
            }
        )
        facts["segments"][seg] = merged

    facts["_read_warnings"] = read["warnings"]
    facts["_read_from"] = str(from_xlsx)
    return facts
