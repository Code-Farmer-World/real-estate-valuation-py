"""一行指令產出填好的三份書表。

    .venv/bin/python -m xlsxform.cli --templates ../正式題目 --out /tmp/out

這裡是唯一知道 kernel 與 xlsxform 兩邊的地方。計算由 kernel 做，寫入由 xlsxform
做，相依方向由這一層決定（xlsxform 不 import kernel），比照 pdfform 的既有慣例。

輸出六個檔案：三份表各有活版與定版。

    表3地價區段勘查表-live.xlsx    / -final.xlsx    四張工作表，一個區段一張
    表5影響地價區域因素分析明細表-live.xlsx / -final.xlsx
    表4比較法調查估價表-live.xlsx  / -final.xlsx

活版把加總與四則運算寫成 Excel 公式，局處把個別因素填進表4 之後下游自動更新。
定版全部是規則引擎算好的數值，用於對照答案與轉 PDF。
"""

from __future__ import annotations

import argparse
import json
import sys
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
from kernel.src.ruleset import load_ruleset
from kernel.src.validate import check_ruleset, errors

from . import fill, layout
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
    errs = errors(check_ruleset(rs))
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

    return {
        "ruleset": rs,
        "table5_1": t5,
        "table4": {
            "benchmark": facts["benchmark"],
            "comparables": comps,
            "given": given,
            "benchmark_parcel": given.get(facts["benchmark"], {}).get("parcel"),
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="產出填好的樹林住宅三份查估書表")
    ap.add_argument(
        "--facts",
        type=Path,
        default=DEFAULT_FACTS,
        help="案件設定 JSON（案號、比準地、表4 已給資料、case_overrides）。"
        "未搭配 --from-xlsx 時，勘查事實也從這裡讀",
    )
    ap.add_argument(
        "--from-xlsx",
        type=Path,
        default=None,
        help="填好的表3 勘查表 xlsx。給了就用它取代 --facts 裡的 segments 區塊",
    )
    ap.add_argument(
        "--templates", type=Path, required=True, help="官方 xlsx 空白範本所在目錄"
    )
    ap.add_argument("--out", type=Path, required=True, help="輸出目錄")
    args = ap.parse_args(argv)

    facts = load_facts(Path(args.facts), args.from_xlsx)
    if facts.get("_read_from"):
        print(f"勘查事實來源：{facts['_read_from']}")
        for w in facts.get("_read_warnings") or []:
            print(f"  ⚠️ {w['segment']} {w['factor_id']}：{w['reason']}")
        print()
    computed = compute_all(facts)
    t5, t4 = computed["table5_1"], computed["table4"]

    problems = layout.check_layout()
    if problems:
        raise SystemExit("layout 自檢有問題，拒絕產表：\n" + "\n".join(problems))

    args.out.mkdir(parents=True, exist_ok=True)
    produced: list[Path] = []

    produced.append(
        write_table3(
            facts,
            find_template(args.templates, "table3"),
            args.out / f"{OUTPUT_STEM['table3']}-filled.xlsx",
        )
    )

    for live, tag in ((True, "live"), (False, "final")):
        p, counts = write_table5(
            facts,
            computed,
            find_template(args.templates, "table5"),
            args.out / f"{OUTPUT_STEM['table5']}-{tag}.xlsx",
            live=live,
        )
        produced.append(p)
        expected = {"grades": 116, "corrections": 87, "subtotals": 24, "totals": 3}
        if counts != expected:
            raise SystemExit(f"表5-1 寫入格數 {counts} 與預期 {expected} 不符")

        produced.append(
            write_table4(
                computed,
                find_template(args.templates, "table4"),
                args.out / f"{OUTPUT_STEM['table4']}-{tag}.xlsx",
                live=live,
            )
        )

    print("═══ 表5-1 影響地價區域因素 ═══")
    for seg in t5.comparables:
        nz = {g: str(t5.subtotal(seg, g)) for g in t5.groups if t5.subtotal(seg, g) != 0}
        print(f"  {seg}  總修正數 {t5.totals[seg]:+}%   非零群組 {nz}")
    print()
    print("═══ 表4（個別因素以 0 計）═══")
    for seg in t4["comparables"]:
        print(
            "  %s  絕對值加總 %s%%  相近程度 %s  權重 %s%%  試算價格 %s 元/㎡"
            % (
                seg,
                t4["abs_sum_pct"][seg],
                t4["similarity"][seg],
                t4["weight_pct"][seg],
                f"{t4['trial_price'][seg]:,}",
            )
        )
    print(f"  比準地比較價格 {t4['benchmark_comparison_price']:,} 元/㎡")
    print(f"  比準地地價（第21條進位）{t4['benchmark_land_price']:,} 元/㎡")
    print()
    print("═══ 產出 ═══")
    for p in produced:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
