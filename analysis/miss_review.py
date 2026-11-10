"""外れた予想（約定したが的中しなかった予測）の検証メモ。

承認済み設計（2026-11-10）。数値は全て記録済みの値から計算する。断定表現は使わず「可能性」の範囲に留める。

計算:
    約定価格   = 買い min(指値, 寄り) / 売り max(指値, 寄り)（寄りがなければ指値）
    損益       = 買い (終値-約定)/約定 / 売り (約定-終値)/約定
    銘柄の動き r = 対象日終値 ÷ 予測日終値 - 1
    地合いの寄与率 = r と日経平均の前日比 m が同じ向きなら min(m ÷ r, 1)、逆向きなら 0（m がなければ判定しない）
    超過       = r - m（市場全体の動きを除いた、この銘柄だけの動き）
    ギャップ g = 寄り ÷ 予測日終値 - 1 / 寄り後の動き o = 終値 ÷ 寄り - 1
    順行幅・逆行幅 = 約定価格から見た、当日の高値・安値までの動き（買いは高値側が順行、売りは安値側が順行）
主因（上から順に、最初に当てはまったもの。他は副次要因）:
    1 地合い       : 寄与率 >= 0.5            （タグ名: 買い=地合い悪化 / 売り=地合い上昇）
    2 寄りのギャップ: g と o がともに不利な向きで |g| >= 0.5% かつ |g| >= |o|（買い=寄りで下落 / 売り=寄りで上昇）
    3 反動         : 予測日の騰落率が買い+3%以上・売り-3%以下、または出来高倍率 >= 3.0（買い=急騰後の反動 / 売り=急落後の反発）
    4 ファンダメンタル逆行: 予測時の材料で、不利な向きの数 > 有利な向きの数
    5 決算イベント : 予測時に決算まで2日以内
    6 個別要因     : 上のどれにも当てはまらない。判定に必要な値（寄り・日経平均）が欠けていれば「データ不足」
副次要因には、既存の原因タグの条件（日経平均 |m|>=1% が不利な向き、|g|>=0.5% が不利な向き）も含める。
"""

import json
from dataclasses import dataclass

from analysis.miss_analysis import GAP_MOVE, GAP_TAG, MARKET_MOVE, MARKET_TAG, SURGE_RETURN, SURGE_TAG, SURGE_VOLUME
from analysis.scoring import Side

SHARE_THRESHOLD = 0.5
EPS = 1e-9  # 境界ちょうどの値が、小数の誤差で外れないようにする


def _ge(a: float, b: float) -> bool:
    return a >= b - EPS
EARNINGS_DAYS = 2
FUNDAMENTAL_TAG = "ファンダメンタル逆行"
EARNINGS_TAG = "決算イベント"
INDIVIDUAL_TAG = "個別要因"
NO_DATA_TAG = "データ不足"

NEXT_STEP = {
    "地合い悪化": "地合い（日経平均の向き）が大きく悪い日は、買い候補を控えるかどうかの検証が検討候補です。",
    "地合い上昇": "地合い（日経平均の向き）が大きく強い日は、売り候補を控えるかどうかの検証が検討候補です。",
    "寄りで下落": "寄り付きの不利なギャップに備え、指値の位置を見直す検証が検討候補です。",
    "寄りで上昇": "寄り付きの不利なギャップに備え、指値の位置を見直す検証が検討候補です。",
    "急騰後の反動": "勢いの強い銘柄ほど翌日に逆行している可能性があり、逆張りの検証が検討候補です。",
    "急落後の反発": "勢いの強い銘柄ほど翌日に逆行している可能性があり、逆張りの検証が検討候補です。",
    FUNDAMENTAL_TAG: "予測時のファンダメンタル（業績・割安度）が逆行する銘柄の扱いを見直す検証が検討候補です。",
    EARNINGS_TAG: "決算発表が近い銘柄の扱い（候補から外す・指値を離す）の検証が検討候補です。",
    INDIVIDUAL_TAG: "個別の要因が中心の可能性があります。根拠の追加が検討候補です。",
    NO_DATA_TAG: "判定に必要な値が欠けていました。データの取得状況の確認が必要です。",
}


@dataclass(frozen=True)
class MissMetrics:
    fill_price: float
    trade_return: float
    stock_move: float | None  # r
    market_move: float | None  # m
    market_share: float | None
    excess: float | None
    gap: float | None
    open_to_close: float | None
    favorable: float  # 順行幅（0以上）
    adverse: float  # 逆行幅（0以上）


@dataclass(frozen=True)
class MissReview:
    primary: str
    secondary: list[str]
    metrics: MissMetrics
    text: str


def _fundamental_counts(snapshot: list[dict] | None, side: Side) -> tuple[int, int]:
    """予測時の材料の（有利な数, 不利な数）。買いは強気が有利、売りは弱気が有利。"""
    if not snapshot:
        return 0, 0
    bull = sum(1 for i in snapshot if i.get("stance") == "bull")
    bear = sum(1 for i in snapshot if i.get("stance") == "bear")
    return (bull, bear) if side == "buy" else (bear, bull)


def compute_metrics(
    side: Side,
    entry_price: float,
    pred_close: float,
    target_open: float | None,
    target_high: float,
    target_low: float,
    target_close: float,
    market_return: float | None,
) -> MissMetrics:
    if side == "buy":
        fill = min(entry_price, target_open) if target_open else entry_price
        trade = (target_close - fill) / fill
        favorable, adverse = (target_high - fill) / fill, (fill - target_low) / fill
    else:
        fill = max(entry_price, target_open) if target_open else entry_price
        trade = (fill - target_close) / fill
        favorable, adverse = (fill - target_low) / fill, (target_high - fill) / fill
    r = target_close / pred_close - 1
    m = market_return
    share = excess = None
    if m is not None:
        share = 0.0 if r == 0 or (r > 0) != (m > 0) or m == 0 else min(m / r, 1.0)
        excess = r - m
    gap = o = None
    if target_open:
        gap = target_open / pred_close - 1
        o = target_close / target_open - 1
    return MissMetrics(fill, trade, r, m, share, excess, gap, o, max(favorable, 0.0), max(adverse, 0.0))


def _adverse_dir(side: Side, v: float) -> bool:
    return v < 0 if side == "buy" else v > 0


def review_miss(
    side: Side,
    entry_price: float,
    pred_close: float,
    pred_daily_return: float,
    pred_volume_ratio: float,
    target_open: float | None,
    target_high: float,
    target_low: float,
    target_close: float,
    market_return: float | None,
    fundamental_snapshot: list[dict] | None = None,
    earnings_days: int | None = None,
) -> MissReview:
    mt = compute_metrics(side, entry_price, pred_close, target_open, target_high, target_low, target_close, market_return)

    causes: list[str] = []  # 優先順
    if mt.market_share is not None and _ge(mt.market_share, SHARE_THRESHOLD):
        causes.append(MARKET_TAG[side])
    if mt.gap is not None and mt.open_to_close is not None:
        if (
            _adverse_dir(side, mt.gap)
            and _adverse_dir(side, mt.open_to_close)
            and _ge(abs(mt.gap), GAP_MOVE)
            and _ge(abs(mt.gap), abs(mt.open_to_close))
        ):
            causes.append(GAP_TAG[side])
    surge = _ge(pred_daily_return, SURGE_RETURN) if side == "buy" else _ge(-pred_daily_return, SURGE_RETURN)
    if surge or _ge(pred_volume_ratio, SURGE_VOLUME):
        causes.append(SURGE_TAG[side])
    aligned, contrary = _fundamental_counts(fundamental_snapshot, side)
    if contrary > aligned:
        causes.append(FUNDAMENTAL_TAG)
    if earnings_days is not None and 0 <= earnings_days <= EARNINGS_DAYS:
        causes.append(EARNINGS_TAG)

    # 副次要因: 主因の条件を満たさなくても、既存の原因タグの条件に当てはまるもの
    extras = []
    if mt.market_move is not None and (
        _ge(-mt.market_move, MARKET_MOVE) if side == "buy" else _ge(mt.market_move, MARKET_MOVE)
    ):
        extras.append(MARKET_TAG[side])
    if mt.gap is not None and _ge(abs(mt.gap), GAP_MOVE) and _adverse_dir(side, mt.gap):
        extras.append(GAP_TAG[side])

    if causes:
        primary = causes[0]
    else:
        primary = INDIVIDUAL_TAG if (target_open and market_return is not None) else NO_DATA_TAG
    secondary = [c for c in dict.fromkeys(causes[1:] + extras) if c != primary]

    return MissReview(primary, secondary, mt, _compose_text(side, primary, secondary, mt, pred_daily_return,
                                                             pred_volume_ratio, fundamental_snapshot, earnings_days))


def _pct(v: float, signed: bool = True) -> str:
    return f"{v * 100:+.2f}%" if signed else f"{v * 100:.2f}%"


def _compose_text(side, primary, secondary, mt, pred_dr, pred_vr, snapshot, earnings_days) -> str:
    parts = []
    if primary in (MARKET_TAG[side],):
        parts.append(
            f"主因: {primary}。日経平均が{_pct(mt.market_move)}動き、この銘柄の動き（予測日の終値比{_pct(mt.stock_move)}）の"
            f"約{mt.market_share * 100:.0f}%を市場全体の動きで説明できます。市場全体を除いた動き（超過）は{_pct(mt.excess)}です。"
        )
    elif primary == GAP_TAG[side]:
        parts.append(
            f"主因: {primary}。寄り付きで予測日の終値比{_pct(mt.gap)}と不利な方向にずれ（ギャップ）、"
            f"その後も寄り付き比{_pct(mt.open_to_close)}動きました。"
        )
    elif primary == SURGE_TAG[side]:
        word = "上昇" if side == "buy" else "下落"
        parts.append(
            f"主因: {primary}。予測日に{word}が大きく（{_pct(pred_dr)}・出来高は20日平均の{pred_vr:.1f}倍）、"
            f"翌日に反対方向の動き（反動）が出た可能性があります。"
        )
    elif primary == FUNDAMENTAL_TAG:
        direction = "買い" if side == "buy" else "売り"
        reasons = "・".join(i["reason"] for i in (snapshot or []) if i.get("reason") and i.get("stance"))
        parts.append(f"主因: {primary}。予測時のファンダメンタル（業績・割安度）は{direction}方向と逆行する材料が多い状況でした（{reasons}）。")
    elif primary == EARNINGS_TAG:
        parts.append(f"主因: {primary}。決算発表が{earnings_days}日後に迫っており、値動きが大きくなった可能性があります。")
    elif primary == INDIVIDUAL_TAG:
        parts.append(f"主因: {primary}。市場全体や寄り付きの動きでは説明しにくく、この銘柄固有の売買の動きが中心だった可能性があります。")
    else:
        parts.append(f"主因: {primary}。判定に必要な値（寄り付き・日経平均）が欠けています。")

    parts.append(
        f"約定価格{mt.fill_price:,.1f}円。約定後は最大で{_pct(mt.favorable, False)}有利な方向、"
        f"{_pct(mt.adverse, False)}不利な方向に動き、終値で{_pct(mt.trade_return)}になりました。"
    )
    if mt.market_move is None:
        parts.append("日経平均のデータが欠けているため、地合いの影響は判定できません。")
    if secondary:
        parts.append("副次要因: " + "・".join(secondary) + "。")
    parts.append("次回への検討: " + NEXT_STEP[primary])
    return " ".join(parts)


def snapshot_to_json(items: list) -> str:
    return json.dumps([{"text": i.text, "stance": i.stance, "reason": i.reason} for i in items], ensure_ascii=False)
