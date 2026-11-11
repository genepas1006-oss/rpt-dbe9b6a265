"""候補カードの説明（スコア内訳・気をつける点）を、その銘柄の数字から組み立てる。

承認済み（2026-11-11）。新しい判定は追加せず、既存のスコア基準（analysis.technical）を表示用に分解する。
断定表現は使わない。キリのいい価格の効果は未検証のため、事実の表示にとどめる。

    スコア内訳: 出来高 / 当日騰落率 / 引け位置 / 決算パターンの4項目（値動き・出来高5点＋決算2点＝7点満点）。
    日経平均との比較: 差が±0.5ポイント以内は「ほぼ同じ動き」、それ以外は強い・弱い。
    キリのいい価格: 1,000円未満は100円刻み / 1,000〜4,999円は500円刻み / 5,000円以上は1,000円刻み。
        3,000円・5,000円・10,000円は「大きな節目」と添える（呼値の境目とは断定しない）。
"""

import math
from dataclasses import dataclass

from analysis.scoring import Side
from analysis.technical import (
    _close_position_points,
    _return_points,
    _short_close_position_points,
    _short_return_points,
    _volume_points,
)

MAX_SCORE = 7
SAME_MOVE_POINTS = 0.5  # 日経平均との差がこの範囲（ポイント）以内ならほぼ同じ動き
BIG_LEVELS = (3000, 5000, 10000)


@dataclass(frozen=True)
class ScoreRow:
    label: str
    actual: str
    rule: str
    points: int

    def to_md(self) -> str:
        return f"{self.label} | {self.actual} | {self.rule} | +{self.points}点"


def close_position(high: float, low: float, close: float) -> float:
    """引け位置=(終値-安値)/(高値-安値)。高値=安値の日は0.5。"""
    return 0.5 if high == low else (close - low) / (high - low)


def score_rows(
    side: Side, volume_ratio: float, daily_return: float, close_pos: float, earnings_points: int
) -> list[ScoreRow]:
    sell = side == "sell"
    if sell:
        ret_rule = "-1%以下で+1点・-3%以下で+2点"
        ret_pts = _short_return_points(daily_return)
        pos_rule = "0.2以下（安値圏）で+1点"
        pos_pts = _short_close_position_points(close_pos)
        pos_zone = "（安値圏）" if pos_pts else ""
    else:
        ret_rule = "+1%以上で+1点・+3%以上で+2点"
        ret_pts = _return_points(daily_return)
        pos_rule = "0.8以上（高値圏）で+1点"
        pos_pts = _close_position_points(close_pos)
        pos_zone = "（高値圏）" if pos_pts else ""
    return [
        ScoreRow("出来高", f"平均の{volume_ratio:.2f}倍", "1.5倍以上で+1点・2倍以上で+2点", _volume_points(volume_ratio)),
        ScoreRow("当日の騰落率", f"前日比{daily_return * 100:+.1f}%", ret_rule, ret_pts),
        ScoreRow("引け位置", f"{close_pos:.2f}{pos_zone}", pos_rule, pos_pts),
        ScoreRow(
            "決算パターン",
            "該当あり" if earnings_points else "該当なし",
            "決算前後の過去の値動きが条件に合えば加点（最大2点）",
            earnings_points,
        ),
    ]


def reason_sentence(side: Side, rows: list[ScoreRow]) -> str:
    total = sum(r.points for r in rows)
    hit = [f"{r.label} {r.actual}" for r in rows if r.points > 0]
    if not hit:
        return ""
    label = "売り" if side == "sell" else "買い"
    return (
        f"{label}の条件のうち、{'・'.join(hit)}が当てはまり、{total}点（{MAX_SCORE}点満点）です。"
        "点数は条件に当てはまった数で、上がる（下がる）保証ではありません。"
    )


def relative_strength_text(stock_return: float, index_return: float | None) -> str:
    """銘柄の前日比と日経平均の前日比の差（ポイント）から、地合いとの関係を一言で表す。"""
    if index_return is None:
        return ""
    diff = (stock_return - index_return) * 100
    idx = f"日経平均{index_return * 100:+.1f}%"
    if abs(diff) <= SAME_MOVE_POINTS + 1e-9:
        return f"{idx}とほぼ同じ動き（地合いの影響が大きい）"
    if diff > 0:
        return f"{idx}より{diff:.1f}ポイント強い動き（銘柄固有の動きが大きい）"
    return f"{idx}より{-diff:.1f}ポイント弱い動き（銘柄固有の動きが大きい）"


def _step(price: float) -> int:
    if price < 1000:
        return 100
    if price < 5000:
        return 500
    return 1000


def _level_label(level: int) -> str:
    return f"{level:,}円（大きな節目）" if level in BIG_LEVELS else f"{level:,}円"


def round_level_text(close: float) -> str:
    """終値の上下にあるキリのいい価格までの距離。"""
    if close <= 0:
        return ""
    step = _step(close)
    lower = math.floor(close / step + 1e-9) * step
    if abs(close - lower) < 1e-9:
        return f"終値はちょうど{_level_label(lower)}の節目"
    upper = lower + step
    up_pct = (upper - close) / close * 100
    parts = [f"上の節目{_level_label(upper)}まであと{up_pct:.1f}%"]
    if lower > 0:
        parts.append(f"下の節目{_level_label(lower)}から{(close - lower) / lower * 100:.1f}%上")
    return "、".join(parts)
