"""Markdownレポート生成。

断定的な勝率保証表現は使わず、スコア・根拠・デモ検証の実績値を提示するのみとする
（CLAUDE.md記載の方針）。
"""

from datetime import date

from analysis.scoring import RankedCandidate
from tracking.predictions_db import WinRateStats


def generate_report(
    prediction_date: date,
    target_date: date,
    candidates: list[RankedCandidate],
    stats: WinRateStats,
) -> str:
    lines = [
        f"# 日本株デイクローズ・リサーチレポート {prediction_date.isoformat()}",
        "",
        "**注意: 本レポートは根拠付きスコアリングによる分析結果であり、"
        "翌日の値動きや勝率を保証するものではありません。実発注は行っていません"
        "（デモ検証フェーズ）。**",
        "",
        "## デモ検証成績（現時点までの累計）",
        f"- 答え合わせ済み予測数: {stats.total_predictions}件",
        f"- 指値約定数: {stats.filled_count}件"
        f"（不成立: {stats.total_predictions - stats.filled_count}件）",
    ]

    if stats.win_rate is None:
        lines.append("- 的中率（約定分のみ）: データなし")
    else:
        lines.append(f"- 的中率（約定分のみ）: {stats.win_rate * 100:.1f}%")

    lines += [
        "",
        f"## 本日のTOP候補（{target_date.isoformat()}向け・参考指値）",
        "",
    ]

    if not candidates:
        lines.append("本日は基準（スコア>0）を満たす候補がありませんでした。")
    else:
        for rank, c in enumerate(candidates, start=1):
            lines.append(f"### {rank}位 {c.name}（{c.code}） - スコア{c.total_score}点")
            lines.append(
                f"- 内訳: 値動き・出来高{c.technical_score}点 / 決算パターン{c.earnings_score}点"
            )
            lines.append(f"- 参考指値: {c.entry_price:,.1f}円")
            if c.reasons:
                lines.append(f"- 根拠: {' / '.join(c.reasons)}")
            lines.append("")

    return "\n".join(lines)
