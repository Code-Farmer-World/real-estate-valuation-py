"""openpyxl 寫入的底層工具。

這一層只管「怎麼把值放進格子而不弄壞範本」，不知道任何業務規則。
決定填什麼是 fill.py 的事。

三個實測踩過的坑：

1. **合併格只能寫主格。** 對從格賦值會拋
   `AttributeError: 'MergedCell' object has no attribute 'value'`。
   主格是合併範圍左上角那一格。`cell()` 會自動把從格導向主格並回報。
2. **`copy_worksheet()` 不能跨工作簿。** 同一個工作簿內可以，而且保真度足夠
   （實測表3 範本複製後 188 個合併格、20 個欄寬、46 個列高與列印版面設定
   全部一致）。三份範本要併成單一檔案就得逐格重建格式，那會失真。
3. **百分比要存實際小數。** Excel 的百分比格式顯示 `23.50%` 時儲存格裡是
   `0.235`。存成字串 `"23.50%"` 會讓公式無法運算。
"""

from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import openpyxl
from openpyxl.cell.cell import Cell
from openpyxl.utils import get_column_letter, range_boundaries
from openpyxl.worksheet.worksheet import Worksheet

#: 百分比欄位的顯示格式。負值也要帶正負號，因為修正率會是負數
#: （比較標的比比準地好時要往下修，那個負號是對的）。
PERCENT_FORMAT = "0.00%;-0.00%"

#: 金額欄位（元/㎡），千分位無小數
MONEY_FORMAT = "#,##0"


def load_template(template: str | Path, dest: str | Path) -> openpyxl.Workbook:
    """把範本複製到 dest 再開啟，永不動到原始範本。

    用 `data_only=False`（預設）載入，否則會丟掉範本裡既有的公式與文字。
    官方範本沒有任何有效公式，但保險起見不改這個預設。
    """
    template, dest = Path(template), Path(dest)
    if not template.exists():
        raise FileNotFoundError(f"找不到範本 {template}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(template, dest)
    return openpyxl.load_workbook(dest)


def visible_sheets(wb: openpyxl.Workbook) -> list[Worksheet]:
    """可見的工作表。

    官方三份範本各自是同一本 24 張表的工作簿，只有一張可見（對應檔名那張），
    其餘 23 張是隱藏的舊範本樣例，內容是 ○○鄉／甲一／乙二 這類佔位資料。
    那些不是本案資料，也不要動它們。
    """
    return [ws for ws in wb.worksheets if ws.sheet_state != "hidden"]


def the_visible_sheet(wb: openpyxl.Workbook, *, expect_title: str | None = None) -> Worksheet:
    """取唯一的可見工作表，順便確認範本沒被換過。"""
    vis = visible_sheets(wb)
    if len(vis) != 1:
        raise ValueError(
            f"預期只有一張可見工作表，實得 {len(vis)} 張：{[w.title for w in vis]}。"
            f"範本可能被改過，請重新量測格位。"
        )
    ws = vis[0]
    if expect_title is not None and ws.title != expect_title:
        raise ValueError(
            f"可見工作表名稱是 {ws.title!r}，預期 {expect_title!r}。"
            f"範本可能被換過，請確認 layout.py 的座標仍然適用。"
        )
    return ws


def merge_anchor(ws: Worksheet, coord: str) -> str:
    """若 coord 落在合併範圍內，回傳該範圍的主格座標，否則原樣回傳。"""
    cell = ws[coord]
    row, col = cell.row, cell.column
    for rng in ws.merged_cells.ranges:
        min_col, min_row, max_col, max_row = range_boundaries(str(rng))
        if min_row <= row <= max_row and min_col <= col <= max_col:
            return f"{get_column_letter(min_col)}{min_row}"
    return coord


def cell(ws: Worksheet, coord: str) -> Cell:
    """取可寫的格子。落在合併範圍內時自動導向主格。"""
    return ws[merge_anchor(ws, coord)]


def put(
    ws: Worksheet,
    coord: str,
    value: Any,
    *,
    number_format: str | None = None,
    keep_existing: bool = False,
) -> str:
    """寫一格。回傳實際寫入的座標（可能因合併而不同於 coord）。

    `keep_existing=True` 時，格子原本有值就不覆寫。用於範本已經印好內容
    （例如表3 的土地改良勾選文字）而只想在空格填值的情況。
    `value` 為 None 一律跳過，避免把範本原有內容清成空白。
    """
    target = merge_anchor(ws, coord)
    c = ws[target]
    if value is None:
        return target
    if keep_existing and c.value not in (None, ""):
        return target
    c.value = _coerce(value)
    if number_format:
        c.number_format = number_format
    return target


def put_percent(ws: Worksheet, coord: str, pct: Decimal | float | None) -> str:
    """寫百分比。傳進來的是百分點數（23.5 代表 23.5%），存進去的是 0.235。

    Excel 的百分比格式就是這樣運作的。存成字串會讓公式算不動。
    """
    if pct is None:
        return merge_anchor(ws, coord)
    value = Decimal(str(pct)) / Decimal(100)
    return put(ws, coord, value, number_format=PERCENT_FORMAT)


def put_money(ws: Worksheet, coord: str, amount: int | Decimal | None) -> str:
    return put(ws, coord, amount, number_format=MONEY_FORMAT)


def put_formula(ws: Worksheet, coord: str, formula: str, *, number_format: str | None = None) -> str:
    """寫 Excel 公式。

    ⚠️ openpyxl 寫入公式後檔案裡不會有 cached value。用 openpyxl 讀回來會拿到
    公式字串而不是數字，要在 Excel、Numbers 或 Google Sheets 開啟才會計算。
    這是活版與定版必須並存的原因。
    """
    if not formula.startswith("="):
        raise ValueError(f"公式必須以 = 開頭：{formula!r}")
    return put(ws, coord, formula, number_format=number_format)


def _coerce(value: Any) -> Any:
    """Decimal 轉成 float 才能被 Excel 當數字處理。

    只在寫入這一刻轉，計算全程仍然是 Decimal。字串與 int 原樣保留。
    """
    if isinstance(value, Decimal):
        return float(value)
    return value


def duplicate_sheet(wb: openpyxl.Workbook, ws: Worksheet, titles: Iterable[str]) -> list[Worksheet]:
    """把 ws 變成 titles 指定的那幾張表。

    第一個標題套用在 ws 自己（改名），其餘用 copy_worksheet() 複製。這樣不會
    留下一張沒填的空白表。複製必須在填入資料之前做，否則會複製到已填的內容。
    """
    titles = list(titles)
    if not titles:
        raise ValueError("至少要一個工作表名稱")
    out = [ws]
    for t in titles[1:]:
        out.append(wb.copy_worksheet(ws))
    for sheet, title in zip(out, titles):
        sheet.title = title
    return out


def save(wb: openpyxl.Workbook, dest: str | Path) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    wb.save(dest)
    return dest
