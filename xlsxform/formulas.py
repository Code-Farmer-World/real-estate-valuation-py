"""活版的 Excel 公式。

分界線：需要查表判斷的（優劣等級、修正百分比）一律寫成規則引擎算好的數值，
純四則運算的（加總、乘法、加權平均）寫成公式。這樣局處把個別因素填進表4 之後，
下游的合計、絕對值加總、試算價格、比準地比較價格會自動更新。

權重刻意不寫成公式。它需要「絕對值加總由小到大排序後分級」的判斷，
而且作業手冊另註要配合蒐集資料可信度綜合決定，寫成公式會把這個判斷藏起來。

表4 的區域因素調整百分率也不寫成跨檔案參照。三份表是三個獨立檔案，
跨檔案公式要寫成 ='[檔名.xlsx]工作表'!G42，對檔名與路徑的依賴太脆弱，
而且那一格是我們算好的結果，沒有讓它跟著動的需求。
"""

from __future__ import annotations

from . import layout


def _rng(col: str, rows: tuple[int, ...]) -> str:
    """把列號轉成 Excel 參照。連續就用區間，不連續就逐格列舉。"""
    if len(rows) > 1 and list(rows) == list(range(rows[0], rows[-1] + 1)):
        return f"{col}{rows[0]}:{col}{rows[-1]}"
    return ",".join(f"{col}{r}" for r in rows)


def table5_1_subtotal(col: str, subtotal_row: int) -> str:
    """表5-1 某個群組的百分比小計。

    第 11 列（土地使用管制）不含第 6、7、8 列，因為表5-1 備註載明使用分區、
    建蔽率、容積率的修正併同於表4 宗地個別因素處理，所以公式會長成
    =SUM(G5,G9,G10) 而不是 =SUM(G5:G10)。這個缺口是刻意的。
    """
    rows = layout.TABLE5_1_SUBTOTAL_ROWS[subtotal_row]
    return f"=SUM({_rng(col, rows)})"


def table5_1_total(col: str) -> str:
    """表5-1 影響地價區域因素總修正數 = 八個群組小計相加。

    書表上 B42 印的 =(1)+(2)+(3)+(4)+(5)+(6)+(7)+(8) 就是在講這件事，
    但那是說明文字（(1) 不是合法的儲存格參照），真正的公式在各標的的欄位。
    """
    rows = layout.TABLE5_1_SUBTOTAL_ROW_ORDER
    return f"=SUM({_rng(col, rows)})"


def table4_individual_total(diff_col: str) -> str:
    """表4 個別因素合計 = 項目 7 到 25 的差異率相加。

    局處填入 J9:J28 之後這一格自動更新，下游的試算價格也跟著動。
    """
    rows = layout.TABLE4_INDIVIDUAL_ROWS
    return f"=SUM({diff_col}{rows[0]}:{diff_col}{rows[-1]})"


def table4_abs_sum(diff_col: str) -> str:
    """表4 調整百分率絕對值加總。

    定義是 |交易日期調整| ＋ |區域因素總修正數| ＋ Σ|個別因素各項|
    （作業手冊 p.53，金山 Golden Case 的 |2.00|＋|0.00|＋|1|＋|2|＋|5|＋|3|＋|2|
    ＝15.00 就是這個結構）。

    注意用的是區域因素的總修正數（單一數字），不是各細項的絕對值加總。
    這兩者不同，混用會導出不同的權重。
    """
    ind = layout.TABLE4_INDIVIDUAL_ROWS
    date_row = layout.TABLE4_ROW_TRANSACTION_DATE
    seg_row = layout.TABLE4_ROW_SEGMENT
    return (
        f"=ABS({diff_col}{date_row})+ABS({diff_col}{seg_row})"
        f"+SUMPRODUCT(ABS({diff_col}{ind[0]}:{diff_col}{ind[-1]}))"
    )


def table4_trial_price(cond_col: str, diff_col: str, total_col: str) -> str:
    """表4 試算價格 = 調整至估價基準日單價 × (1＋區域因素) × (1＋個別因素合計)。

    用範本上已有的「調整至估價基準日單價」當起點，而不是回頭乘正常單價與日期
    調整。那個值是題目給的，兩種算法等價（調整後單價就是正常單價乘日期調整），
    但用表上的值公式比較好讀，也與書表的閱讀順序一致。
    """
    price_row = layout.TABLE4_ROW_ADJUSTED_UNIT_PRICE
    seg_row = layout.TABLE4_ROW_SEGMENT
    total_row = layout.TABLE4_ROW_INDIVIDUAL_TOTAL
    return (
        f"=ROUND({cond_col}{price_row}*(1+{diff_col}{seg_row})"
        f"*(1+{total_col}{total_row}),0)"
    )


def table4_benchmark_comparison_price() -> str:
    """表4 比準地比較價格 = Σ(試算價格 × 權重)，四捨五入至個位（手冊 p.53）。"""
    trial = layout.TABLE4_ROW_TRIAL_PRICE
    parts = []
    for i in sorted(layout.TABLE4_DECISION_LEFT_COL):
        left = layout.TABLE4_DECISION_LEFT_COL[i]
        right = layout.TABLE4_DECISION_RIGHT_COL[i]
        parts.append(f"{left}{trial}*{right}{trial}")
    return f"=ROUND({'+'.join(parts)},0)"
