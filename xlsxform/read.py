"""從填好的表3 勘查表 xlsx 讀出勘查事實。

與 `write.py` 對稱，共用 `layout.py` 那份格位對映。讀與寫綁在同一份對映上，
任一邊改壞另一邊的 round-trip 測試就會發現。

輸出是統一的勘查事實格式，與 `kernel/fixtures/shulin_survey_facts.json` 的
`segments` 區塊同一個 schema。三種輸入格式（PDF、xlsx、未來的 OCR）都收斂到
這一層，下游的 `kernel` 完全不必知道資料從哪來。

這個模組不 import `kernel/`，輸出普通 dict，由 `cli.py` 交給 kernel。

`raw` 與 `facts` 分開：`raw` 忠實記錄勘查表寫的，`facts` 是套用案件層級覆寫
（`case_overrides`）之後計算要用的。本案的實例是容積率，勘查表原載 260%，
但地價查估單位指示一律以 200% 計算。兩者都要保留，因為徵收案會被訴願，
「為什麼容積率用 200 不用 260」必須答得出來。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet

from . import layout
from .fill import checked_improvements
from .write import cell

#: 視為「這一格沒有填」的內容。表3 有 13 個細項是圈選未勾、距離空白，
#: 那是事實（沒有那個設施）而不是讀取失敗，所以回 None 讓下游的
#: `absent` 級距處理。全角與半角的圈都要收。
#:
#: ⚠️ 刻意**不含**「無」。「無」在有無禁止建築、有無限制建築這兩個細項是有效答案
#: （表示沒有禁建、沒有限建），規則集把它對映到第 1 級。把它正規化成 None 會讓
#: 那兩格讀不到值。實測踩過：round-trip 比對時期望「無」卻讀到 None。
#: `kernel/src/classify.py` 的 ABSENT_TOKENS 含「無」是另一回事，
#: 那是給距離型細項判「或無」用的，而禁建限建走的是 ordered_category。
_ABSENT_TOKENS = {"", "-", "－", "○", "◯", "〇"}

_SEGMENT_RE = re.compile(layout.TABLE3_SEGMENT_NO_PATTERN)


class SurveyReadError(ValueError):
    """讀取失敗且無法繼續。與「某一格沒有值」區分開。

    刻意繼承 ValueError：讀取失敗本質是輸入值的問題，而 api 層對 ValueError
    已經有「回 400 並附訊息」的處理。若自己另立一支，壞掉的上傳檔案會變成
    500 而讓使用者只看到通用錯誤（實測踩過：壞的 xlsx 讓 zipfile.BadZipFile
    一路逸出）。
    """


def read_table3(path: str | Path) -> dict[str, Any]:
    """讀一份表3 xlsx，回傳 {segments: {...}, warnings: [...]}。

    一個工作表一個地價區段。隱藏工作表一律跳過（官方範本每個檔案有 23 張隱藏的
    舊範本樣例，內容是 ○○鄉／甲一／乙二 這類佔位資料，不是本案資料）。
    """
    path = Path(path)
    if not path.exists():
        raise SurveyReadError(f"找不到檔案 {path}")

    try:
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception as e:
        # openpyxl 對非 xlsx 的檔案丟的是 zipfile.BadZipFile 之類，
        # 那些對呼叫端沒有意義，轉成看得懂的訊息。
        raise SurveyReadError(
            f"{path.name} 無法以 Excel 格式開啟（{type(e).__name__}）。"
            f"請確認上傳的是 .xlsx 檔而不是改過副檔名的其他格式。"
        ) from e
    sheets = [ws for ws in wb.worksheets if ws.sheet_state != "hidden"]
    if not sheets:
        raise SurveyReadError(f"{path.name} 沒有可見的工作表")

    segments: dict[str, Any] = {}
    warnings: list[dict[str, str]] = []

    for ws in sheets:
        seg = _segment_no(ws)
        if seg in segments:
            raise SurveyReadError(
                f"區段編號 {seg} 出現在多張工作表（{ws.title}），無法判斷該用哪一張"
            )
        data, warns = _read_sheet(ws, seg)
        data["source"] = {"file": path.name, "sheet": ws.title}
        segments[seg] = data
        warnings.extend(warns)

    if not segments:
        raise SurveyReadError(f"{path.name} 讀不出任何地價區段")

    return {"segments": segments, "warnings": warnings}


def _segment_no(ws: Worksheet) -> str:
    """取地價區段編號。先從工作表名稱抓，抓不到就讀格子，兩者都沒有就報錯。

    `xlsxform` 產出的工作表叫「表3 P001-00」，官方空白範本只有一張叫
    「表3區段勘查表」，所以兩種都要能吃。
    """
    m = _SEGMENT_RE.search(ws.title)
    if m:
        return m.group(0)

    value = cell(ws, layout.TABLE3_CELL_SEGMENT_NO).value
    text = "" if value is None else str(value).strip()
    m = _SEGMENT_RE.search(text)
    if m:
        return m.group(0)
    if text:
        return text

    raise SurveyReadError(
        f"工作表「{ws.title}」找不到地價區段編號。"
        f"名稱裡沒有 {layout.TABLE3_SEGMENT_NO_PATTERN} 這種樣式，"
        f"格子 {layout.TABLE3_CELL_SEGMENT_NO} 也是空的。"
    )


def _read_sheet(ws: Worksheet, segment: str) -> tuple[dict[str, Any], list[dict[str, str]]]:
    raw: dict[str, Any] = {}
    warnings: list[dict[str, str]] = []

    def note(fid: str, why: str) -> None:
        warnings.append({"segment": segment, "factor_id": fid, "reason": why})

    for fid, coord in {**layout.TABLE3_VALUE_CELLS_A, **layout.TABLE3_VALUE_CELLS_B}.items():
        c = cell(ws, coord)
        if fid in layout.TABLE3_PERCENT_FIELDS:
            raw[fid] = _to_percent(c.value, c.number_format, where=f"{segment} {coord}")
        else:
            raw[fid] = _to_text(c.value)

    raw["regional.transport.main_road_width"] = _to_number(
        cell(ws, layout.TABLE3_CELL_MAIN_ROAD_WIDTH).value
    )
    main_road_name = _to_text(cell(ws, layout.TABLE3_CELL_MAIN_ROAD_NAME).value)
    raw["regional.transport.avg_road_width"] = _to_number(
        cell(ws, layout.TABLE3_CELL_AVG_ROAD_WIDTH).value
    )

    improvement_text = "".join(
        str(cell(ws, c).value or "")
        for c in (layout.TABLE3_CELL_IMPROVEMENT_LINE1, layout.TABLE3_CELL_IMPROVEMENT_LINE2)
    )
    checked = checked_improvements(improvement_text)
    raw["regional.land_improvement.site_improvement"] = len(checked)

    # 本案 13 個細項是圈選未勾、距離空白。那些格子在範本裡是 ○ 或空白，
    # 沒有單一的「值欄」可讀，所以一律記 None 表示「無」。
    # 這是事實不是讀取失敗，所以不進 warnings。
    for fid in layout.TABLE3_UNCHECKED_FACTORS:
        raw.setdefault(fid, None)

    # 其他影響因素在表3 沒有對應的值欄（題目的表5-1 已預填「-」）
    raw.setdefault("regional.other.other_factors", None)

    for fid in (
        "regional.land_control.urban_plan",
        "regional.transport.main_road_width",
        "regional.transport.avg_road_width",
        "regional.transport.road_development",
    ):
        if raw.get(fid) is None:
            note(fid, "這一格應該有值但讀到空白，請確認勘查表是否漏填或格位對映需重新校準")

    return (
        {
            "segment_range": _to_text(cell(ws, layout.TABLE3_CELL_SEGMENT_RANGE).value),
            "year_period": _to_text(cell(ws, layout.TABLE3_CELL_YEAR).value),
            # extras 放「不是評價細項但回填時需要」的附屬資訊。與 raw 分開，
            # 因為 raw 的每個鍵都對應一個 factor_id，而這些沒有。
            # 少了它們 round-trip 會不完整（實測：路名與土地改良勾選會消失）。
            "extras": {
                "main_road_name": main_road_name,
                "improvement_items": sorted(checked),
            },
            "table3_only": {
                "building_density": _to_text(
                    cell(ws, layout.TABLE3_CELL_BUILDING_DENSITY).value
                ),
                "building_type": _to_text(cell(ws, layout.TABLE3_CELL_BUILDING_TYPE).value),
            },
            "raw": raw,
        },
        warnings,
    )


# ---------- 型別轉換 ----------


def _to_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text in _ABSENT_TOKENS else text


def _to_number(value: Any) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if float(value).is_integer() else value
    text = str(value).strip().replace(",", "")
    if text in _ABSENT_TOKENS:
        return None
    text = re.sub(r"(?i)\s*m$", "", text)
    try:
        num = float(text)
    except ValueError:
        return None
    return int(num) if num.is_integer() else num


def _to_percent(value: Any, number_format: str | None, *, where: str) -> int | float | None:
    """把百分比欄位轉成百分點數（50% → 50）。

    xlsx 有三種存法，要靠儲存格格式區分：

        字串 "50%"              → 去掉 % 轉數字
        數值 0.5 且格式含 %     → 乘 100
        數值 50 且格式不含 %    → 原樣

    數值小於 1 而格式又不含 % 時無法判斷（可能是 0.5 個百分點，也可能是 50%
    被存成小數但格式掉了），這種情況報錯而不是猜。我們自己產出的檔案一定帶格式，
    但別人手填的可能沒有。
    """
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().replace("％", "%").replace(" ", "")
        if text in _ABSENT_TOKENS:
            return None
        text = text.rstrip("%")
        try:
            num = float(text)
        except ValueError:
            return None
        return int(num) if num.is_integer() else num

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        has_pct = "%" in (number_format or "")
        if has_pct:
            num = float(value) * 100
        elif 0 < float(value) < 1:
            raise SurveyReadError(
                f"{where} 的百分比欄位是數值 {value} 但儲存格格式不含 %，"
                f"無法判斷它是 {value} 個百分點還是 {float(value) * 100:g}%。"
                f"請在 Excel 把該格設為百分比格式，或直接填成文字「{float(value) * 100:g}%」。"
            )
        else:
            num = float(value)
        return int(num) if num.is_integer() else num

    return None


# ---------- 案件層級覆寫 ----------


def apply_case_overrides(
    segments: dict[str, Any], overrides: list[dict[str, Any]] | None
) -> dict[str, Any]:
    """把 raw 套用覆寫後產生 facts。raw 原樣保留。

    覆寫是案件層級的設定，說明「勘查表上寫的」與「計算要用的」為何不同。
    它不屬於 read.py（只負責讀）也不屬於 kernel（不認識個案特例），
    所以做成可宣告的資料。

    `applies_to` 支援 `"all_segments"` 或區段編號的清單。不做條件式，
    那會變成在資料裡寫程式。
    """
    for seg, data in segments.items():
        data["facts"] = dict(data["raw"])

    for ov in overrides or []:
        fid = ov["factor_id"]
        applies = ov.get("applies_to", "all_segments")
        targets = list(segments) if applies == "all_segments" else list(applies)
        unknown = [t for t in targets if t not in segments]
        if unknown:
            raise SurveyReadError(
                f"case_overrides 指向不存在的區段 {unknown}（factor_id={fid}）"
            )
        for seg in targets:
            segments[seg]["facts"][fid] = ov["value"]

    return segments
