"""審查模式的 Demo：改壞兩格，看系統抓不抓得到，以及賠償金差多少。

    python scripts/demo-review.py

跑三段：

1. 拿官方範本原封不動送進審查，應該逐格相符。
2. 程式化改壞兩格（把一個優劣等級改錯、把跨表抄填的總修正數抄錯），
   再送一次，系統要指出是哪兩格、依據是什麼、以及每平方米價差多少。
3. 同一份輸入換一組規則集（金山商業 → 樹林住宅），
   結果會變，因為判級與矩陣都跟著換。這說明規則是資料不是程式碼。

為什麼要有這一支：Demo 現場沒辦法真的拿筆去改 PDF，而改壞兩格是這個題目
最能講清楚價值的動作（審查人員平常就是在找那兩格）。所以把「改壞」做在
辨識完的資料結構上，讓它可重複、可錄影、每次結果一樣。

改的是記憶體裡的 dict，原始 PDF 完全不動。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paths  # noqa: E402
from api.review import review  # noqa: E402
from kernel.src.ruleset import load_ruleset  # noqa: E402
from parser import table1, table4, table5_2  # noqa: E402
from parser.detect import detect_table  # noqa: E402
from parser.extract import load_pages  # noqa: E402

PARSERS = {"表1": table1.parse, "表5-2": table5_2.parse, "表4": table4.parse}

#: 開發期用的金山商業用地範本，三張表都已填好，是唯一有官方答案可對的案子。
SAMPLE_PDF = paths.DOC_DIR / "查估書表範本.pdf"

REGIONAL = "jinshan_commercial_regional"
INDIVIDUAL = "jinshan_commercial_individual"
OTHER_REGIONAL = "shulin_residential_regional"


def hr(title: str) -> None:
    print()
    print("═" * 74)
    print(title)
    print("═" * 74)


def parse_all(pdf: Path) -> dict[str, Any]:
    tables: dict[str, Any] = {}
    for page in load_pages(pdf):
        code = detect_table(page)
        if code is None or code in tables:
            continue
        tables[code] = PARSERS[code](page).to_dict()
    return tables


def show(result: dict[str, Any]) -> None:
    v = result["verdict"]
    print(
        "  判定：%s　　查了 %d 格，發現 %d 處不符"
        % ("逐格相符" if v == "match" else "有不符", result["checked_total"], result["finding_count"])
    )
    for layer, findings in result["layers"].items():
        if not findings:
            continue
        print(f"  ── {layer}")
        for f in findings:
            filed, computed = f.get("filed"), f.get("computed")
            print(f"     {f.get('factor_id')}")
            print(f"       書表填的：{filed}")
            print(f"       依基準表應為：{computed}")
            if f.get("basis"):
                print(f"       依據：{f['basis']}")
            if f.get("source_page"):
                print(f"       基準表頁碼：第 {f['source_page']} 頁")
    pi = result.get("price_impact")
    if pi and pi.get("diff_per_sqm") is not None:
        print(
            "  價格影響：書表 %s，依基準表重算 %s，每平方米差 %s 元"
            % (
                f"{pi['filed']:,}" if pi["filed"] is not None else "—",
                f"{pi['computed']:,}",
                f"{pi['diff_per_sqm']:+,}",
            )
        )
        if pi.get("benchmark_land_price"):
            print(
                "  　　　　　比準地地價（第21條分段進位）%s 元/㎡"
                % f"{pi['benchmark_land_price']:,}"
            )


def break_two_cells(tables: dict[str, Any]) -> list[str]:
    """改壞兩格，回傳做了什麼的說明。

    刻意挑不同層的兩格：一格是表1 內部（量測值與所填等級不一致），
    一格是跨表抄填（表5-2 的總修正數抄到表4 時抄錯）。
    這兩類是實務上最常見的錯誤，而且分屬審查重點的不同項。
    """
    done = []

    t1 = tables.get("表1")
    if t1:
        cells = t1.get("cells") or t1.get("grades") or {}
        target = None
        for fid, cell in cells.items():
            if isinstance(cell, dict) and cell.get("grade") is not None:
                target = (fid, cell)
                break
        if target:
            fid, cell = target
            before = cell["grade"]
            cell["grade"] = 1 if before != 1 else 2
            done.append(
                "表1 的「%s」把等級從第 %s 級改成第 %s 級（量測值沒動，所以會對不上）"
                % (fid, before, cell["grade"])
            )

    t4 = tables.get("表4")
    if t4 and t4.get("comparables"):
        comp = t4["comparables"][0]
        corrections = comp.get("filed_corrections") or {}
        # 挑影響最大的那一項抄成 0。模擬估價師漏抄一格，
        # 而且把合計與試算價格一路算下去（實務上錯誤就是這樣傳遞的）。
        # 取最大是為了讓價差看得出來，取最小的話差額只有一兩千。
        nonzero = {k: v for k, v in corrections.items() if v}
        target = max(nonzero, key=lambda k: abs(nonzero[k])) if nonzero else None
        if target is not None:
            before = corrections[target]
            corrections[target] = 0
            old_total = comp.get("individual_total_pct")
            if old_total is not None:
                new_total = old_total - before
                comp["individual_total_pct"] = new_total
                base = comp.get("date_adjusted_unit_price_displayed")
                if base is not None:
                    comp["trial_price"] = round(base * (1 + new_total / 100))
                done.append(
                    "表4 的「%s」把 %+g%% 抄成 0，合計從 %g%% 變 %g%%，"
                    "試算價格從 %s 變 %s"
                    % (
                        target,
                        before,
                        old_total,
                        new_total,
                        f"{base * (1 + old_total / 100):,.0f}" if base else "—",
                        f"{comp['trial_price']:,}",
                    )
                )

    return done


def main() -> int:
    if not SAMPLE_PDF.exists():
        print(f"找不到範本 {SAMPLE_PDF}")
        print("官方 PDF 不在版控裡，需自行補檔。見 docs/README.md")
        return 1

    rs_regional = load_ruleset(REGIONAL)
    rs_individual = load_ruleset(INDIVIDUAL)

    hr("一、官方範本原封不動送審")
    clean = parse_all(SAMPLE_PDF)
    print(f"  辨識到的表：{list(clean)}")
    show(review(clean, rs_individual, rs_regional))

    hr("二、改壞兩格再送一次")
    broken = parse_all(SAMPLE_PDF)
    changes = break_two_cells(broken)
    if not changes:
        print("  找不到可以改的格子，資料結構可能變了")
        return 1
    for c in changes:
        print(f"  改動：{c}")
    print()
    result = review(broken, rs_individual, rs_regional)
    show(result)
    print()
    print("  改兩格但抓到 %d 處不符，那不是重複計算。" % result["finding_count"])
    print("  一個優劣等級填錯會同時違反兩件事：表1 內部的量測值與等級不一致，")
    print("  以及表1 與表5-2 的等級不一致（審查重點第 vi 項）。錯誤沿著鏈擴散，")
    print("  這正是人工逐格核對容易漏掉的地方。")

    hr("三、同一份輸入，換一組規則集")
    print(f"  規則集：{REGIONAL} → {OTHER_REGIONAL}")
    print("  換的是資料不是程式碼。判級級距與修正矩陣都跟著換，所以結果會變。")
    try:
        other = load_ruleset(OTHER_REGIONAL)
    except Exception as e:  # noqa: BLE001
        print(f"  載入失敗：{e}")
        return 1
    print()
    show(review(parse_all(SAMPLE_PDF), rs_individual, other))
    print()
    print("  這一段的不符是預期的：金山商業用地的案子拿樹林住宅用地的基準表去對，")
    print("  級距與矩陣都不同。它證明規則集是可抽換的，而不是寫死在程式裡。")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
