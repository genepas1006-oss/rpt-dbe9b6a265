"""report.generate_report のテスト（買い・売り2セクション構成）。"""

from datetime import date

from analysis.scoring import RankedCandidate
from report.generate_report import generate_report
from tracking.predictions_db import WinRateStats

PREDICTION_DATE = date(2026, 10, 26)
TARGET_DATE = date(2026, 10, 27)

EMPTY_STATS = WinRateStats(total_predictions=0, filled_count=0, win_count=0, win_rate=None)


def _buy_candidate() -> RankedCandidate:
    return RankedCandidate(
        code="6954",
        name="ファナック",
        total_score=3,
        technical_score=2,
        earnings_score=1,
        volume_ratio=2.45,
        entry_price=5608.8,
        reasons=["出来高が20日平均の2.45倍"],
        side="buy",
    )


def _sell_candidate() -> RankedCandidate:
    return RankedCandidate(
        code="1234",
        name="テスト株",
        total_score=5,
        technical_score=5,
        earnings_score=0,
        volume_ratio=2.5,
        entry_price=974.9,
        reasons=["当日-3.00%", "安値圏(0.13)で引け"],
        side="sell",
    )


def test_report_contains_both_sections_with_candidates():
    text = generate_report(
        PREDICTION_DATE,
        TARGET_DATE,
        [_buy_candidate()],
        [_sell_candidate()],
        EMPTY_STATS,
        EMPTY_STATS,
    )

    assert "## 本日の買い候補（2026-10-27向け・参考指値）" in text
    assert "## 本日の売り候補（2026-10-27向け・参考指値）" in text
    assert "ファナック" in text
    assert "テスト株" in text
    assert "参考指値: 974.9円" in text


def test_report_shows_empty_message_when_no_candidates():
    text = generate_report(PREDICTION_DATE, TARGET_DATE, [], [], EMPTY_STATS, EMPTY_STATS)

    assert "本日は基準（スコア>0）を満たす買い候補がありませんでした。" in text
    assert "本日は基準（スコア>0）を満たす売り候補がありませんでした。" in text
