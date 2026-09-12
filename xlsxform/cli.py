"""一行指令產出填好的三份書表。

    .venv/bin/python -m xlsxform.cli --templates ../正式題目 --out /tmp/out
    .venv/bin/python -m xlsxform.cli --from-xlsx <填好的表3.xlsx> \
        --templates ../正式題目 --out /tmp/out

這個檔案只做參數解析與輸出排版。組裝邏輯在 pipeline.py，API 走同一份，
避免兩條路各自漂移。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import layout
from .pipeline import (
    DEFAULT_FACTS,
    OUTPUT_STEM,
    compute_all,
    find_template,
    load_facts,
    write_delivery_note,
    write_table3,
    write_table4,
    write_table5,
)
from .verify import verify_outputs


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
    print("═══ 自我驗證 ═══")
    report = verify_outputs(
        table5_final=args.out / f"{OUTPUT_STEM['table5']}-final.xlsx",
        table5_live=args.out / f"{OUTPUT_STEM['table5']}-live.xlsx",
        table4_final=args.out / f"{OUTPUT_STEM['table4']}-final.xlsx",
        table4_live=args.out / f"{OUTPUT_STEM['table4']}-live.xlsx",
        expected=facts["expected"],
        comparables=t4["comparables"],
        ruleset_findings=computed["ruleset_findings"],
    )
    for c in report.checks:
        print(f"  {'✓' if c.passed else '✗'} {c.name}")
        if c.detail:
            print(f"      {c.detail}")
    report_path = args.out / "verification-report.json"
    report_path.write_text(
        json.dumps(
            {
                "case_id": facts["case_id"],
                "ruleset_id": computed["table5_1"].ruleset_id,
                "facts_source": facts.get("_read_from") or str(args.facts),
                "premise": "表4 個別因素（項目7至25）題目未提供宗地個別條件資料，"
                "依表4 註記由地價查估單位辦理，本次計算以 0% 計。",
                **report.to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    produced.append(report_path)
    produced.append(write_delivery_note(args.out, facts, computed, report))

    print()
    print("═══ 產出 ═══")
    for p in produced:
        print(f"  {p}")

    if not report.passed:
        print()
        for line in report.summary_lines():
            print(line)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
