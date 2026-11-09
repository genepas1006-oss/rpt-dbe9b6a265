"""ファンダメンタル指標に基づくワンポイント・明日の見通しのコメント組み立て。

承認済み設計（2026-11-10）。スコア（候補の選び方）には使わない参考情報で、断定表現は使わない。
取得できた項目だけで文を作り、全て取れない場合は呼び出し側が従来の文に戻す。

判定ルール:
    PER  : <10倍 割安水準 / 10以上20未満 市場平均並み / 20以上30以下 やや割高 / 30倍超 割高水準
           （赤字などでPERがなければ判定しない）。PBRは1倍未満なら「（1倍割れ）」と明記。
    成長率: +100%超は「前年比2倍超（前年が低水準の影響の可能性）」/ +10%以上 増益(増収)基調 / -10%以下 減益(減収)基調。
    ROE  : 10%以上 良好 / 5%未満 低め（その間は載せない）。
    配当利回り: 3%以上のみ「高配当」として載せる。
    目標株価: アナリスト5名以上のとき、乖離率=(目標-現値)/現値。+15%以上 上回る / -5%以下 下回る。
    52週レンジ位置=(現値-安値)/(高値-安値): 0.9以上 高値圏 / 0.1以下 安値圏。現値が範囲外（基準違い）なら使わない。
    決算: 次回発表まで14日以内なら日数を記載。
    表示項目: 優先順（バリュエーション→成長→目標株価→ROE→高配当→52週）に最大3項目。
    整合/逆行: 強気材料=割安・増益基調・目標株価が上回る・52週安値圏、弱気材料=割高・減益基調・目標株価が下回る・52週高値圏。
              買いは強気が整合、売りは弱気が整合。件数の多い方を述べ、同数は「混在」。
"""

from dataclasses import dataclass

from data_sources.base import Fundamentals

MAX_ITEMS = 3
EARNINGS_NOTICE_DAYS = 14


@dataclass(frozen=True)
class Item:
    text: str
    stance: str | None  # "bull" / "bear" / None
    reason: str | None  # 見通し文に使う短い理由


def _growth_text(label: str, g: float, up: str, down: str) -> tuple[str, str | None]:
    if g > 1.0:
        return f"{label}は前年比2倍超（前年が低水準の影響の可能性）", "bull"
    if g >= 0.10:
        return f"{label}成長{g * 100:+.1f}%（{up}）", "bull"
    if g <= -0.10:
        return f"{label}成長{g * 100:+.1f}%（{down}）", "bear"
    return f"{label}成長{g * 100:+.1f}%", None


def build_items(f: Fundamentals, close: float) -> list[Item]:
    items: list[Item] = []

    # バリュエーション
    parts = []
    stance = reason = None
    label = ""
    if f.per is not None and f.per > 0:
        parts.append(f"PER {f.per:.1f}倍")
        if f.per < 10:
            label, stance, reason = "と割安水準", "bull", "割安"
        elif f.per < 20:
            label = "と市場平均並み"
        elif f.per <= 30:
            label = "とやや割高"
        else:
            label, stance, reason = "と割高水準", "bear", "割高"
    if f.pbr is not None and f.pbr > 0:
        parts.append(f"PBR {f.pbr:.2f}倍" + ("（1倍割れ）" if f.pbr < 1 else ""))
        if stance is None and f.per is None and f.pbr < 1:
            stance, reason = "bull", "割安"
    if parts:
        items.append(Item("・".join(parts) + label, stance, reason))

    # 成長（利益を優先して判定。売上は併記）
    growth_parts = []
    gstance = greason = None
    if f.revenue_growth is not None:
        t, gstance = _growth_text("売上高", f.revenue_growth, "増収基調", "減収基調")
        growth_parts.append(t)
        greason = {"bull": "増収基調", "bear": "減収基調"}.get(gstance)
    if f.earnings_growth is not None:  # 利益があれば、利益の判定を優先する
        t, gstance = _growth_text("利益", f.earnings_growth, "増益基調", "減益基調")
        growth_parts.append(t)
        greason = {"bull": "増益基調", "bear": "減益基調"}.get(gstance)
    if growth_parts:
        items.append(Item("・".join(growth_parts), gstance, greason))

    # アナリスト目標株価
    if f.target_price and f.analyst_count and f.analyst_count >= 5 and close > 0:
        dev = (f.target_price - close) / close
        stance = reason = None
        if dev >= 0.15:
            stance, reason = "bull", "目標株価が現値を上回る"
        elif dev <= -0.05:
            stance, reason = "bear", "目標株価が現値を下回る"
        items.append(Item(f"アナリスト目標株価{f.target_price:,.0f}円（{f.analyst_count}名）は現値比{dev * 100:+.1f}%", stance, reason))

    # ROE
    if f.roe is not None:
        if f.roe >= 0.10:
            items.append(Item(f"ROE {f.roe * 100:.1f}%（資本効率は良好）", None, None))
        elif f.roe < 0.05:
            items.append(Item(f"ROE {f.roe * 100:.1f}%（低め）", None, None))

    # 高配当
    if f.dividend_yield is not None and f.dividend_yield >= 0.03:
        items.append(Item(f"配当利回り{f.dividend_yield * 100:.2f}%（高配当）", None, None))

    # 52週レンジ位置
    if f.week52_high and f.week52_low and f.week52_high > f.week52_low and close > 0:
        if f.week52_low * 0.99 <= close <= f.week52_high * 1.01:
            pos = (close - f.week52_low) / (f.week52_high - f.week52_low)
            if pos >= 0.9:
                items.append(Item("52週レンジの高値圏", "bear", "52週高値圏"))
            elif pos <= 0.1:
                items.append(Item("52週レンジの安値圏", "bull", "52週安値圏"))
    return items


def build_fundamental_sentence(f: Fundamentals, close: float) -> str | None:
    """ワンポイント用。表示する項目が1つもなければNone。"""
    items = build_items(f, close)[:MAX_ITEMS]
    return ("、".join(i.text for i in items) + "。") if items else None


def build_fundamental_outlook(f: Fundamentals, close: float, side: str) -> str | None:
    """明日の見通し用（ファンダメンタル部分）。強気・弱気の材料が1つもなければNone。"""
    items = [i for i in build_items(f, close) if i.stance]
    if not items:
        return None
    bull = [i for i in items if i.stance == "bull"]
    bear = [i for i in items if i.stance == "bear"]
    aligned, contrary = (bull, bear) if side == "buy" else (bear, bull)
    direction = "買い" if side == "buy" else "売り"
    if len(aligned) > len(contrary):
        names = "・".join(i.reason for i in aligned)
        many = "が多く" if len(aligned) >= 2 else "があり"
        return f"ファンダメンタル面は{direction}方向と整合する材料{many}（{names}）、"
    if len(contrary) > len(aligned):
        names = "・".join(i.reason for i in contrary)
        caution = "急反発に注意。" if side == "sell" else "戻り売りに押される可能性に注意。"
        many = "が多く" if len(contrary) >= 2 else "があり"
        return f"ファンダメンタル面は{direction}方向と逆行する材料{many}（{names}）、{caution}"
    names = "・".join(i.reason for i in items)
    return f"ファンダメンタル面は材料が混在しており（{names}）、"


def earnings_notice(days: int | None) -> str:
    if days is None or days < 0 or days > EARNINGS_NOTICE_DAYS:
        return ""
    when = "本日" if days == 0 else f"{days}日後"
    return f"決算発表が{when}に予定されており、発表前後の値動きの拡大にも注意。"
