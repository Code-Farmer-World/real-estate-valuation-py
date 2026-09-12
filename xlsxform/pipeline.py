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
from typing import Any

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


#: 產出目錄裡給收件人看的說明檔
DELIVERY_NOTE_NAME = "交付說明.txt"

_DELIVERY_NOTE = """\
{case_id} 查估書表 產出說明
產出時間：{produced_at}
規則集：{ruleset_id}
勘查事實來源：{facts_source}

══ 這個目錄裡有什麼 ══

  {t3}-filled.xlsx
      地價區段勘查表。四個地價區段各一張工作表（{segments}），
      回填現地勘查值。這一份是計算的輸入，附在這裡供對照。

  {t5}-final.xlsx      ← 交件用這一份
  {t4}-final.xlsx      ← 交件用這一份
      定版。所有欄位都是算好的數值。用來對照答案、列印、轉 PDF。
      表5-1 另附一張「計算依據」工作表，逐列寫出每一格的量測值、
      優劣等級、判級依據、矩陣查表結果與評價基準明細表頁碼。

  {t5}-live.xlsx
  {t4}-live.xlsx
      活版。群組小計、總修正數、個別因素合計、調整百分率絕對值加總、
      試算價格、比準地比較價格這些欄位是 Excel 公式而不是數值。
      把表4 的個別因素（項目 7 至 25）填進去之後，下游會自動重算。

  verification-report.json
      產出時的自我驗證紀錄，{verify_passed} / {verify_total} 項通過。

  {note_name}
      這一份。

  兩份 xlsx 的數字一致。分成兩份的原因是寫入公式的檔案裡不會留下計算結果，
  程式讀回來只拿得到公式字串，所以驗證要對定版做，而後續修改要用活版。

══ 計算結果（個別因素以 0 計）══

{numbers}

══ 三個必須知道的前提 ══

  一、表4 的個別因素（項目 7 至 25）留空。題目未提供宗地個別條件資料，
      而表4 註記載明該段由地價查估單位依「土地徵收補償市價查估辦法」
      第 20 條及「影響地價個別因素評價基準表」辦理。所以上面的試算價格、
      調整百分率絕對值加總、比較標的權重與比準地地價都是個別因素以 0 計
      的結果。填入個別因素之後這些數字都會變，權重的排序也可能改變。

  二、使用分區、建蔽率、容積率三項的優劣等級照填，修正百分比以 0.00% 計
      且不列入群組小計與總修正數。依表5-1 備註欄，這三項的修正併同於
      比較法調查估價表的宗地個別因素考量調整。

  三、容積率一律以 200% 計算（依地價查估單位說明，本案各區段道路寬度
      均未達八公尺）。勘查表忠實記載原載值，四個區段同級故修正率 0.00%。

══ 這些數字是怎麼來的 ══

  優劣等級依「新北市樹林區普通住宅用地影響地價區域因素評價基準明細表」
  的級距條文判定，修正百分比查該表的修正矩陣。29 個細項的矩陣與門檻值
  已與該基準表 PDF 逐格比對一致。

  計算全程不經過任何生成式模型，包含計算依據工作表上的敘述文字。
  同一份勘查表輸入永遠得到同一份結果。
"""


def _delivery_numbers(computed: dict) -> str:
    t5, t4 = computed["table5_1"], computed["table4"]
    lines = [
        "  區段       總修正數   絕對值加總  相近程度  權重    試算價格(元/㎡)",
        "  " + "─" * 66,
    ]
    for seg in t4["comparables"]:
        lines.append(
            "  %-9s %9s %10s   %-6s %5s %14s"
            % (
                seg,
                f"{t5.totals[seg]:+}%",
                f"{t4['abs_sum_pct'][seg]}%",
                t4["similarity"][seg],
                f"{t4['weight_pct'][seg]}%",
                f"{t4['trial_price'][seg]:,}",
            )
        )
    lines.append("")
    lines.append(
        "  比準地 %s 比較價格：%s 元/㎡"
        % (t4["benchmark"], f"{t4['benchmark_comparison_price']:,}")
    )
    lines.append(
        "  比準地地價：%s 元/㎡（查估辦法第 21 條分段進位）"
        % f"{t4['benchmark_land_price']:,}"
    )
    return "\n".join(lines)


def write_delivery_note(out_dir: Path, facts: dict, computed: dict, report: Any) -> Path:
    """在產出目錄放一份說明，讓交付物自己講得清楚。

    收件的人拿到六個檔案，光看檔名分不出該用哪一份，也看不出
    「個別因素以 0 計」這個前提。那個前提有寫在表4 的全案備註欄裡，
    但那是一格窄長的合併格，很容易被忽略。
    """
    from datetime import datetime

    checks = getattr(report, "checks", None) or []
    note = _DELIVERY_NOTE.format(
        case_id=facts["case_id"],
        produced_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        ruleset_id=computed["table5_1"].ruleset_id,
        facts_source=facts.get("_read_from") or "案件設定 JSON",
        segments="、".join([facts["benchmark"]] + list(facts["comparables"])),
        t3=OUTPUT_STEM["table3"],
        t5=OUTPUT_STEM["table5"],
        t4=OUTPUT_STEM["table4"],
        verify_passed=sum(1 for c in checks if c.passed),
        verify_total=len(checks),
        note_name=DELIVERY_NOTE_NAME,
        numbers=_delivery_numbers(computed),
    )
    path = out_dir / DELIVERY_NOTE_NAME
    path.write_text(note, encoding="utf-8")
    return path


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
