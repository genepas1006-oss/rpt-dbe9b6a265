"""report.parse_report のテスト。"""

from datetime import date

from analysis.scoring import RankedCandidate
from report.generate_report import generate_report
from report.parse_report import parse_report
from tracking.predictions_db import WinRateStats

STATS = WinRateStats(total_predictions=10, filled_count=8, win_count=4, win_rate=0.5)


def test_parses_new_format_buy_and_sell_sections():
    buy = RankedCandidate(
        code="6954",
        name="ファナック",
        total_score=3,
        technical_score=2,
        earnings_score=1,
        volume_ratio=2.45,
        entry_price=5608.8,
        reasons=["出来高が20日平均の2.45倍", "当日+3.89%"],
        side="buy",
        day_open=5400.0,
        day_high=5650.0,
        day_low=5380.0,
        day_close=5610.0,
        day_volume=12_000_000,
    )
    sell = RankedCandidate(
        code="1234",
        name="テスト株",
        total_score=5,
        technical_score=5,
        earnings_score=0,
        volume_ratio=2.5,
        entry_price=974.9,
        reasons=["当日-3.00%"],
        side="sell",
    )
    text = generate_report(date(2026, 10, 26), date(2026, 10, 27), [buy], [sell], STATS, STATS)

    parsed = parse_report(text)

    assert parsed.has_sell_section
    assert len(parsed.buy_candidates) == 1
    assert len(parsed.sell_candidates) == 1
    assert parsed.buy_candidates[0].name == "ファナック"
    assert parsed.buy_candidates[0].code == "6954"
    assert parsed.buy_candidates[0].score == 3
    assert parsed.buy_candidates[0].entry_price == "5,608.8円"
    assert parsed.buy_candidates[0].reasons == ["出来高が20日平均の2.45倍", "当日+3.89%"]
    assert parsed.sell_candidates[0].name == "テスト株"
    assert len(parsed.buy_stats_lines) == 3
    assert len(parsed.sell_stats_lines) == 3
    assert "寄り付きから上昇して" in parsed.buy_candidates[0].one_point
    assert "高値5,650.0円" in parsed.buy_candidates[0].day_summary


def test_parses_legacy_format_as_buy_only():
    legacy_text = """# 日本株デイクローズ・リサーチレポート 2026-09-01

**注意: 本レポートは...**

## デモ検証成績（現時点までの累計）
- 答え合わせ済み予測数: 10件
- 指値約定数: 8件（不成立: 2件）
- 的中率（約定分のみ）: 50.0%

## 本日のTOP候補（2026-09-02向け・参考指値）

### 1位 旧銘柄（9999） - スコア4点
- 内訳: 値動き・出来高3点 / 決算パターン1点
- 参考指値: 1,000.0円
- 根拠: 当日+2.00%
"""

    parsed = parse_report(legacy_text)

    assert not parsed.has_sell_section
    assert len(parsed.buy_candidates) == 1
    assert parsed.buy_candidates[0].name == "旧銘柄"
    assert len(parsed.buy_stats_lines) == 3


def test_empty_candidate_sections_parse_to_empty_lists():
    text = generate_report(date(2026, 10, 26), date(2026, 10, 27), [], [], STATS, STATS)

    parsed = parse_report(text)

    assert parsed.buy_candidates == []
    assert parsed.sell_candidates == []
