"""約定方法（指値・成行・持ち越し・利確/損切り）を変えたときの成績を比較するバックテスト。

承認済み設計（2026-11-09、成行検証のご依頼）:
    bars = [翌営業日の足, その翌営業日以降の足...]（bars[0] が翌営業日）
    - 指値(d)       : 指値 = round(予測日終値 × (1 ∓ d), 1)。買いは安値<=指値、売りは高値>=指値で約定し、
                      翌営業日の終値で決済（本番と同じ。d=0.005 が現行）。
    - 寄成→引成     : 翌営業日の始値で成行、同日の終値で決済（必ず約定）。
    - 寄成→N日後引け: 翌営業日の始値で成行、N営業日目の終値で決済（N=2,3）。足が足りなければ取引なし。
    - 寄成+利確/損切: 始値で成行。買いは 始値×(1+利確) 以上の高値で利確、始値×(1-損切) 以下の安値で損切り。
                      同じ日に両方に届いた場合は、日中の順序が分からないため損切りを先に付けた扱い（保守的）。
                      どちらにも届かなければ同日の終値で決済。売りは向きを反転。
    - 引け→引け(参考): 予測日終値で入り、翌営業日の終値で決済（約定条件なし。実行はできない理論値）。
    リターン: 買い=(決済-入口)/入口、売り=(入口-決済)/入口。的中 = リターン > 0。

    選び方(select): "top"=現行のスコア上位N件 / "all"=フィルターを通った全候補（スコア不問。比較用の基準）
"""

from dataclasses import dataclass
from typing import Callable

from analysis.scoring import Side, rank_candidates
from backtest.engine import Trade, TradingDay, Variant
from config import TOP_N
from data_sources.base import DailyBar
from tracking.trade_eval import TradeResult, evaluate_trade

# 戻り値 None は「この足の本数では取引が成立しない（取引として数えない）」
Evaluator = Callable[[Side, float, list[DailyBar]], tuple[float, TradeResult] | None]


@dataclass(frozen=True)
class ExecRule:
    name: str
    evaluate: Evaluator  # (side, 予測日終値, bars) -> (入口価格, 結果)


def _result(side: Side, entry: float, exit_price: float) -> TradeResult:
    ret = (entry - exit_price) / entry if side == "sell" else (exit_price - entry) / entry
    return TradeResult(filled=True, result_return=ret, is_win=ret > 0)


def limit_rule(discount: float) -> ExecRule:
    def evaluate(side: Side, close: float, bars: list[DailyBar]):
        entry = round(close * ((1 - discount) if side == "buy" else (1 + discount)), 1)
        b = bars[0]
        return entry, evaluate_trade(side, entry, b.low, b.high, b.close, b.open)

    return ExecRule(f"limit{discount * 100:g}%", evaluate)


def open_close_rule() -> ExecRule:
    def evaluate(side: Side, close: float, bars: list[DailyBar]):
        entry = bars[0].open
        if entry <= 0:
            return None
        return entry, _result(side, entry, bars[0].close)

    return ExecRule("open→close", evaluate)


def open_hold_rule(days: int) -> ExecRule:
    def evaluate(side: Side, close: float, bars: list[DailyBar]):
        entry = bars[0].open
        if entry <= 0 or len(bars) < days:
            return None
        return entry, _result(side, entry, bars[days - 1].close)

    return ExecRule(f"open→{days}日後close", evaluate)


def open_tp_sl_rule(take_profit: float, stop_loss: float) -> ExecRule:
    def evaluate(side: Side, close: float, bars: list[DailyBar]):
        b = bars[0]
        entry = b.open
        if entry <= 0:
            return None
        if side == "buy":
            tp_price, sl_price = entry * (1 + take_profit), entry * (1 - stop_loss)
            hit_tp, hit_sl = b.high >= tp_price, b.low <= sl_price
        else:
            tp_price, sl_price = entry * (1 - take_profit), entry * (1 + stop_loss)
            hit_tp, hit_sl = b.low <= tp_price, b.high >= sl_price
        if hit_sl:  # 両方に届いた場合も損切りを先に付ける（保守的）
            return entry, _result(side, entry, sl_price)
        if hit_tp:
            return entry, _result(side, entry, tp_price)
        return entry, _result(side, entry, b.close)

    return ExecRule(f"open+TP{take_profit * 100:g}%/SL{stop_loss * 100:g}%", evaluate)


def close_to_close_rule() -> ExecRule:
    def evaluate(side: Side, close: float, bars: list[DailyBar]):
        if close <= 0:
            return None
        return close, _result(side, close, bars[0].close)

    return ExecRule("close→close(参考)", evaluate)


def apply_rule(
    days: list[TradingDay],
    variant: Variant,
    rule: ExecRule,
    select: str = "top",
    top_n: int = TOP_N,
    cost: float = 0.0,
) -> list[Trade]:
    """variantで候補を絞り、selectで選び、ruleで答え合わせした取引一覧を返す。

    cost: 約定した取引ごとに差し引く往復の費用（取引額に対する割合）。的中は費用後のリターン>0。
    不成立の取引には費用をかけない。
    """
    if select not in ("top", "all"):
        raise ValueError(f"select must be 'top' or 'all': {select}")
    trades: list[Trade] = []
    for d in days:
        by_code = {c.code: c for c in d.candidates}
        for side in ("buy", "sell"):
            use_buy_score = (side == "buy") != variant.reverse
            pool = [
                (c.buy if use_buy_score else c.sell)
                for c in d.candidates
                if variant.allow(side, c.features)
            ]
            if select == "top":
                chosen = [r.code for r in rank_candidates(pool, top_n=top_n, side=side)]
            else:
                chosen = [c.code for c in pool]
            for code in chosen:
                cand = by_code[code]
                bars = [cand.next_bar, *cand.future_bars]
                evaluated = rule.evaluate(side, (cand.buy if use_buy_score else cand.sell).close, bars)
                if evaluated is None:
                    continue
                entry, result = evaluated
                if cost and result.filled and result.result_return is not None:
                    net = result.result_return - cost
                    result = TradeResult(filled=True, result_return=net, is_win=net > 0)
                trades.append(
                    Trade(
                        day=d.day,
                        next_day=d.next_day,
                        side=side,
                        code=code,
                        entry_price=entry,
                        filled=result.filled,
                        result_return=result.result_return,
                        is_win=result.is_win,
                    )
                )
    return trades


def default_rules() -> list[ExecRule]:
    return [
        *[limit_rule(d) for d in (0.0, 0.0025, 0.005, 0.01)],
        open_close_rule(),
        open_hold_rule(2),
        open_hold_rule(3),
        *[open_tp_sl_rule(tp, sl) for tp, sl in ((0.01, 0.01), (0.02, 0.01), (0.015, 0.015), (0.02, 0.02))],
        close_to_close_rule(),
    ]
