"""不的中（約定したが的中しなかった予測）の原因タグ付けと、次回への示唆の組み立て。

承認済み設計（2026-11-09）:
    買いの不的中に付けるタグ（売りは向きを反転、タグ名は下の表）:
        地合い悪化   : 翌営業日の日経平均の前日比 <= -1%
        寄りで下落   : 翌営業日の始値が予測日終値より 0.5% 以上低い（(始値-終値)/終値 <= -0.5%）
        急騰後の反動 : 予測日の騰落率 >= +3% または 出来高倍率 >= 3.0
        その他       : 上のどれにも当てはまらない（判定に必要な値が揃っている場合）
        データ不足   : どれにも当てはまらず、始値または日経平均の値が欠けている場合
    売り: 地合い上昇（日経平均 >= +1%）/ 寄りで上昇（+0.5%以上）/
          急落後の反発（予測日の騰落率 <= -3% または 出来高倍率 >= 3.0）
    複数のタグが同時に付くことがある。
    次回への示唆は、タグ件数に基づく定型文（断定しない・スコアは自動変更しない）。
"""

from collections import Counter

from analysis.scoring import Side

MARKET_MOVE = 0.01
GAP_MOVE = 0.005
SURGE_RETURN = 0.03
SURGE_VOLUME = 3.0

MARKET_TAG = {"buy": "地合い悪化", "sell": "地合い上昇"}
GAP_TAG = {"buy": "寄りで下落", "sell": "寄りで上昇"}
SURGE_TAG = {"buy": "急騰後の反動", "sell": "急落後の反発"}
OTHER_TAG = "その他"
NO_DATA_TAG = "データ不足"

# 件数が少ないときは参考程度であることを添える
SMALL_SAMPLE = 10

SUGGESTIONS = {
    "地合い悪化": "市場全体の下落に左右されている可能性があります。地合い（日経平均の向き）の確認が検討候補です。",
    "地合い上昇": "市場全体の上昇に左右されている可能性があります。地合い（日経平均の向き）の確認が検討候補です。",
    "寄りで下落": "翌営業日の寄り付きで不利なギャップが出ている可能性があります。指値の位置の見直しが検討候補です。",
    "寄りで上昇": "翌営業日の寄り付きで不利なギャップが出ている可能性があります。指値の位置の見直しが検討候補です。",
    "急騰後の反動": "勢いの強い銘柄ほど翌日に逆行している可能性があります。逆張りの検証（バックテスト）が検討候補です。",
    "急落後の反発": "勢いの強い銘柄ほど翌日に逆行している可能性があります。逆張りの検証（バックテスト）が検討候補です。",
    OTHER_TAG: "個別要因が中心の可能性があります。根拠の追加が検討候補です。",
    NO_DATA_TAG: "判定に必要な値が欠けていました。データの取得状況の確認が必要です。",
}


def classify_miss(
    side: Side,
    pred_close: float,
    pred_daily_return: float,
    pred_volume_ratio: float,
    target_open: float | None,
    market_return: float | None,
) -> list[str]:
    """不的中の予測に原因タグを付ける（的中・不成立には使わない）。"""
    tags: list[str] = []

    if market_return is not None:
        if side == "buy" and market_return <= -MARKET_MOVE:
            tags.append(MARKET_TAG["buy"])
        elif side == "sell" and market_return >= MARKET_MOVE:
            tags.append(MARKET_TAG["sell"])

    if target_open is not None and pred_close > 0:
        gap = (target_open - pred_close) / pred_close
        if side == "buy" and gap <= -GAP_MOVE:
            tags.append(GAP_TAG["buy"])
        elif side == "sell" and gap >= GAP_MOVE:
            tags.append(GAP_TAG["sell"])

    if side == "buy":
        surge = pred_daily_return >= SURGE_RETURN or pred_volume_ratio >= SURGE_VOLUME
    else:
        surge = pred_daily_return <= -SURGE_RETURN or pred_volume_ratio >= SURGE_VOLUME
    if surge:
        tags.append(SURGE_TAG[side])

    if not tags:
        complete = target_open is not None and market_return is not None
        tags.append(OTHER_TAG if complete else NO_DATA_TAG)
    return tags


def count_causes(tag_lists: list[list[str]]) -> list[tuple[str, int]]:
    """タグ別の件数を、多い順（同数はタグ名順）で返す。"""
    counts = Counter(tag for tags in tag_lists for tag in tags)
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def build_suggestion(tag_lists: list[list[str]]) -> str:
    """不的中の件数から、次回への示唆の定型文を組み立てる。"""
    total = len(tag_lists)
    if total == 0:
        return ""
    top_tag, top_count = count_causes(tag_lists)[0]
    text = (
        f"不的中{total}件のうち、「{top_tag}」が最多（{top_count}件・{top_count / total * 100:.0f}%）です。"
        f"{SUGGESTIONS[top_tag]}"
    )
    if total < SMALL_SAMPLE:
        text += "（件数が少ないため参考程度です。）"
    return text
