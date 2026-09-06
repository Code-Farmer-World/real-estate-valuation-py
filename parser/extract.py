"""PDF 文字層抽取層。

**只靠座標定位，不靠文字順序。** 官方書表的文字層順序是不可信的：
範本表4 的「9深度(M)」標籤 y=149.1，但它那一列的值（23 / 16 / 1.00%）在 y=145.8，
差 3.3pt；`pdftotext -layout` 會把這種偏移印成串行（113.21 / 7 / 16 / 方形 交錯）。
所以本層只提供「x 區間 + y 容差」的查詢原語，上層 parser 一律用欄位座標取值。

同理，全域 y 分群也不可用：範本表4 的列距最小只有 3.3pt（標籤與值之間），
與相鄰列的間距（6.6pt）差距太小，任何單一容差都會同時切錯或併錯。
正確做法是先用標籤定位出該列的 y，再往各欄取值。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import pdfplumber


@dataclass(frozen=True)
class Word:
    """一個文字片段及其在頁面上的位置（單位為 pt，原點在左上）。"""

    text: str
    x0: float
    x1: float
    top: float
    bottom: float

    @property
    def y_center(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.x0, self.top, self.x1, self.bottom)


Grid = tuple[tuple[str | None, ...], ...]


@dataclass(frozen=True)
class Page:
    """一頁的文字、框線與 cell 網格。

    `lines` 與 `rects` 都保留，因為兩者不能互相取代：範本表1／表4 的框線是
    line 物件（96 / 164 條），表5-2 卻一條 line 都沒有、140 個 rect——
    同一份 PDF 裡兩種畫法並存，只認 lines 會在表5-2 上完全失效。

    座標與網格兩種取值方式並存是刻意的，各表自己選：
    表4 的欄內還有子分隔線、且摘要列（合計／試算價格）與資料列排版不同，
    用座標準；表5-2 的細項名會折成 2–3 行、值落在中間那一行，用網格準。
    """

    number: int
    width: float
    height: float
    words: tuple[Word, ...]
    lines: tuple[dict, ...]
    rects: tuple[dict, ...]
    grids: tuple[Grid, ...] = ()

    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    def main_grid(self) -> Grid:
        """列數最多的那個網格，即這頁的主表。"""
        if not self.grids:
            raise ValueError("p%d 沒有偵測到任何表格網格" % self.number)
        return max(self.grids, key=len)


def load_pages(pdf_path: str | Path) -> list[Page]:
    pages: list[Page] = []
    with pdfplumber.open(str(pdf_path)) as doc:
        for i, p in enumerate(doc.pages, start=1):
            words = tuple(
                Word(w["text"], w["x0"], w["x1"], w["top"], w["bottom"])
                for w in p.extract_words()
            )
            grids = tuple(
                tuple(tuple(row) for row in t.extract()) for t in p.find_tables()
            )
            pages.append(
                Page(
                    number=i,
                    width=p.width,
                    height=p.height,
                    words=words,
                    lines=tuple(p.lines),
                    rects=tuple(p.rects),
                    grids=grids,
                )
            )
    return pages


# ---------- 查詢原語 ----------


def find_word(words: Iterable[Word], text: str, x_range: tuple[float, float] | None = None) -> Word:
    """找出文字完全相符的唯一一個 word。

    刻意要求「唯一」：書表上同一個標籤字串出現兩次，代表版面認知有誤，
    這時猜哪一個都可能錯，寧可當場失敗。
    """
    hits = [w for w in words if w.text == text and _in_x(w, x_range)]
    if not hits:
        raise LookupError("找不到欄位標籤：%r（x 區間 %s）" % (text, x_range))
    if len(hits) > 1:
        raise LookupError(
            "欄位標籤 %r 出現 %d 次，版面判讀有歧義：%s"
            % (text, len(hits), [(round(w.x0), round(w.top)) for w in hits])
        )
    return hits[0]


def words_at(
    words: Iterable[Word],
    x_range: tuple[float, float],
    y_center: float,
    y_tol: float = 5.0,
) -> list[Word]:
    """取出落在指定欄位（x 區間）且與指定列（y 中心）對齊的所有 word，左到右排序。

    y_tol 預設 5.0：範本實測標籤與值最大偏移 3.3pt，相鄰列間距最小 6.6pt，
    5.0 落在兩者之間，是唯一能同時不切錯也不併錯的區間。
    """
    hits = [
        w
        for w in words
        if _in_x(w, x_range) and abs(w.y_center - y_center) <= y_tol
    ]
    return sorted(hits, key=lambda w: w.x0)


def text_at(
    words: Iterable[Word],
    x_range: tuple[float, float],
    y_center: float,
    y_tol: float = 5.0,
) -> str:
    """同 `words_at`，但回傳以空白接起來的文字。空欄回傳空字串。"""
    return " ".join(w.text for w in words_at(words, x_range, y_center, y_tol))


def _in_x(w: Word, x_range: tuple[float, float] | None) -> bool:
    if x_range is None:
        return True
    lo, hi = x_range
    return lo <= w.x0 < hi


# ---------- provenance ----------


def bbox_of(words: Sequence[Word]) -> tuple[float, float, float, float] | None:
    """一組 word 的外接框，用於 provenance 回指原始 PDF 位置。"""
    if not words:
        return None
    return (
        min(w.x0 for w in words),
        min(w.top for w in words),
        max(w.x1 for w in words),
        max(w.bottom for w in words),
    )
