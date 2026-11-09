"""環境認識（米国→想定ギャップ）: 市場ギャップ系列・計算・JSON・サイト表示のテスト。"""

import json
from datetime import date, timedelta

import pytest

from analysis.macro_gap import returns_from_bars
from analysis.market_gaps import load_market_gaps, market_overnight_gaps, save_market_gaps
from data_sources.base import DailyBar
from report.build_site import build_index
from report.premarket import Premarket, compute_premarket, load_premarket, save_premarket


def _days(n, start=date(2026, 1, 5)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _bar(d, o, c):
    return DailyBar(d, o, max(o, c), min(o, c), c, 1)


# ---------------- 日本株全体の夜間ギャップ ----------------
def test_market_overnight_gap_hand_calc():
    d1, d2 = date(2026, 11, 5), date(2026, 11, 6)
    bars = {
        "A": [_bar(d1, 100, 100), _bar(d2, 101, 101)],   # (101-100)/100 = +1%
        "B": [_bar(d1, 100, 100), _bar(d2, 97, 97)],     # -3%
        "C": [_bar(d1, 100, 100), _bar(d2, 105, 105)],   # +5%
    }
    assert market_overnight_gaps(bars, min_stocks=3)[d2] == pytest.approx(0.01)  # (1-3+5)/3 = +1%
    assert d1 not in market_overnight_gaps(bars, min_stocks=3)  # 初日は前日がない


def test_market_overnight_gap_min_stocks_and_bad_prices():
    d1, d2 = date(2026, 11, 5), date(2026, 11, 6)
    bars = {"A": [_bar(d1, 100, 100), _bar(d2, 101, 101)], "B": [_bar(d1, 0, 0), _bar(d2, 97, 97)]}
    assert market_overnight_gaps(bars, min_stocks=2) == {}                      # 前日終値0の銘柄は除外 → 1銘柄だけで足りない
    assert market_overnight_gaps(bars, min_stocks=1)[d2] == pytest.approx(0.01)


def test_market_gaps_json_roundtrip_and_tolerance(tmp_path):
    gaps = {date(2026, 11, 5): 0.002, date(2026, 11, 6): -0.0105}
    p = tmp_path / "g.json"
    save_market_gaps(p, gaps)
    assert load_market_gaps(p) == gaps
    assert load_market_gaps(tmp_path / "none.json") == {}
    p.write_text("{broken", encoding="utf-8")
    assert load_market_gaps(p) == {}


def test_returns_from_bars():
    ds = [date(2026, 11, 4), date(2026, 11, 5), date(2026, 11, 6)]
    bars = [_bar(ds[0], 100, 100), _bar(ds[1], 100, 101), _bar(ds[2], 101, 99)]
    r = returns_from_bars(bars)
    assert ds[0] not in r and r[ds[1]] == pytest.approx(0.01) and r[ds[2]] == pytest.approx(-2 / 101)
    assert returns_from_bars([_bar(ds[0], 0, 0), _bar(ds[1], 1, 1)]) == {}  # 前日終値0は除外


# ---------------- compute_premarket（手計算） ----------------
def _data(n_days=90, slope=0.5):
    """日本の営業日 ds[i] のギャップ = slope × その前の平日の米国前日比。米国は平日ごとに存在。"""
    ds = _days(n_days + 2)
    xs = [((i * 7) % 11 - 5) / 500 for i in range(len(ds))]  # -1.0% 〜 +1.0% の決まった動き
    us_bars, close = [], 100.0
    for d, x in zip(ds, xs):
        prev = close
        close = prev * (1 + x)
        us_bars.append(DailyBar(d, prev, max(prev, close), min(prev, close), close, 1))
    us_ret = returns_from_bars(us_bars)
    gaps = {}
    for i in range(2, len(ds) - 1):
        gaps[ds[i]] = slope * us_ret[ds[i - 1]]
    return ds, us_bars, us_ret, gaps


def test_compute_premarket_hand_calc_exact_linear():
    ds, us_bars, us_ret, gaps = _data()
    for_date = ds[-1]
    gaps = {d: g for d, g in gaps.items() if d < for_date}
    pm, reason = compute_premarket(gaps, us_bars, for_date, "2026-11-10 08:30", window=250, min_n=60)
    assert reason is None
    assert pm.us_date == ds[-2] and pm.us_return == pytest.approx(us_ret[ds[-2]])
    assert pm.slope == pytest.approx(0.5)                                  # 完全に線形 → 傾き0.5
    assert pm.expected_gap == pytest.approx(0.5 * us_ret[ds[-2]])          # 傾き×米国前日比
    assert pm.corr == pytest.approx(1.0) and pm.mae == pytest.approx(0.0, abs=1e-12)
    assert pm.direction_acc == 1.0 and pm.mae < pm.mae_zero
    assert pm.n_fit == len(gaps) - 1 or pm.n_fit <= 250


def test_compute_premarket_window_limits_fit_count():
    ds, us_bars, _, gaps = _data(n_days=120)
    gaps = {d: g for d, g in gaps.items() if d < ds[-1]}
    pm, _ = compute_premarket(gaps, us_bars, ds[-1], "t", window=40, min_n=20)
    assert pm.n_fit == 40


def test_compute_premarket_us_bar_on_the_day_is_not_used():
    ds, us_bars, us_ret, gaps = _data()
    for_date = ds[-1]
    gaps = {d: g for d, g in gaps.items() if d < for_date}
    pm, _ = compute_premarket(gaps, us_bars, for_date, "t")
    assert pm.us_date != for_date and pm.us_date < for_date   # 当日の米国バーは使わない


def test_compute_premarket_unavailable_reasons():
    ds, us_bars, _, gaps = _data()
    for_date = ds[-1]
    gaps = {d: g for d, g in gaps.items() if d < for_date}
    # 米国市場が未更新（基準日の前の平日のバーがない）
    stale = [b for b in us_bars if b.trade_date != ds[-2]]
    pm, reason = compute_premarket(gaps, stale, for_date, "t")
    assert pm is None and "米国市場の基準日" in reason and ds[-2].isoformat() in reason
    # 学習データ不足
    pm2, reason2 = compute_premarket({d: g for d, g in list(gaps.items())[:30]}, us_bars, for_date, "t", min_n=60)
    assert pm2 is None and "データが足りません" in reason2
    # 米国データなし
    pm3, reason3 = compute_premarket(gaps, [], for_date, "t")
    assert pm3 is None and "米国市場の基準日" in reason3


def test_compute_premarket_monday_uses_friday():
    ds = _days(100)
    monday = next(d for d in ds[70:] if d.weekday() == 0)
    friday = monday - timedelta(days=3)
    _, us_bars, _, gaps = _data(n_days=98)
    us_bars = [b for b in us_bars if b.trade_date < monday]
    gaps = {d: g for d, g in gaps.items() if d < monday}
    pm, reason = compute_premarket(gaps, us_bars, monday, "t", min_n=30)
    assert reason is None and pm.us_date == friday


# ---------------- JSON ----------------
def _pm(for_date=date(2026, 11, 10), **kw):
    base = dict(for_date=for_date, us_date=date(2026, 11, 9), us_return=0.012, slope=0.5, expected_gap=0.006,
                n_fit=250, eval_n=540, eval_start=date(2024, 8, 20), eval_end=date(2026, 11, 9), corr=0.65,
                mae=0.0056, mae_zero=0.0068, direction_acc=0.69, generated_at="2026-11-10 08:30")
    base.update(kw)
    return Premarket(**base)


def test_premarket_json_roundtrip_and_tolerance(tmp_path):
    p = tmp_path / "premarket.json"
    save_premarket(p, _pm())
    assert load_premarket(p) == _pm()
    save_premarket(p, _pm(corr=None, mae=None, eval_start=None, eval_end=None))
    assert load_premarket(p).corr is None and load_premarket(p).eval_start is None
    assert load_premarket(tmp_path / "none.json") is None
    p.write_text("{broken", encoding="utf-8")
    assert load_premarket(p) is None
    p.write_text(json.dumps({"for_date": "2026-11-10"}), encoding="utf-8")  # 必須項目が足りない
    assert load_premarket(p) is None


# ---------------- サイト表示 ----------------
def _page(tmp_path, pm=None, report_day="2026-11-09"):
    reports = tmp_path / "reports"
    reports.mkdir(exist_ok=True)
    (reports / f"{report_day}.md").write_text("# 日本株デイクローズ・リサーチレポート\n", encoding="utf-8")
    if pm is not None:
        save_premarket(reports / "premarket.json", pm)
    return build_index(reports, tmp_path / "docs", "t").read_text(encoding="utf-8")


def test_site_shows_environment_with_tags_sources_and_accuracy(tmp_path):
    page = _page(tmp_path, _pm(for_date=date(2026, 11, 10)), report_day="2026-11-09")
    assert '<span class="env-title">環境認識（目安）</span><span class="env-sub">2026-11-10 寄り付き前 ／ 売買の助言ではありません</span>' in page
    assert '<div class="env-k">米国（S&amp;P500）前日比</div><div class="env-v"><span style="color:var(--up)">+1.20%</span></div><span class="tag fact">事実</span>' in page
    assert "Yahoo Finance ^GSPC・2026-11-09 終値" in page
    assert '約<span style="color:var(--up)">+0.6%</span></div><span class="tag guess">推測</span>' in page
    assert "傾き0.50×米国前日比・直近250営業日の回帰" in page
    assert "方向一致 69%・相関 0.65・平均誤差 0.56%（常に0と予測した場合 0.68%）" in page
    assert "2024-08-20〜2026-11-09（540日、各日をその日より前のデータだけで予測）" in page
    assert '<span class="tag fact">事実（過去の検証）</span>' in page
    assert '<span class="tag unknown">不明</span><div class="env-src">無料データでは取得できないため</div>' in page


def test_site_negative_gap_uses_down_color(tmp_path):
    page = _page(tmp_path, _pm(us_return=-0.013, expected_gap=-0.007))
    assert '<span style="color:var(--down)">-1.30%</span>' in page
    assert '約<span style="color:var(--down)">-0.7%</span>' in page


def test_site_without_premarket_shows_unknown_with_reason(tmp_path):
    page = _page(tmp_path, None)
    assert '<span class="env-sub">売買の助言ではありません</span>' in page
    assert "翌営業日向けの米国市場の結果は、朝の更新（米国市場の確定後）で反映されます" in page
    assert "米国（S&amp;P500）前日比" not in page and '<span class="tag fact">事実</span>' not in page
    assert '<span class="tag unknown">不明</span>' in page


def test_site_keeps_past_target_day_values_with_reference_label_and_next_day_unknown(tmp_path):
    # 最新レポートの予測日(11/9) 以前が対象日の値は、隠さず「対象日は過ぎています・参考」と明記して残す
    page = _page(tmp_path, _pm(for_date=date(2026, 11, 9)), report_day="2026-11-09")
    assert "2026-11-09 寄り付き前の値（対象日は過ぎています・参考） ／ 売買の助言ではありません" in page
    assert '<span style="color:var(--up)">+1.20%</span>' in page and '<span class="tag guess">推測</span>' in page
    # 翌営業日向けの欄は「不明（理由）」として別に出す
    assert '<div class="env-k">翌営業日向けの想定ギャップ</div><div class="env-v">不明</div>' in page
    assert "翌営業日向けの米国市場の結果は、朝の更新（米国市場の確定後）で反映されます" in page


def test_site_current_premarket_has_no_next_day_unknown_row(tmp_path):
    page = _page(tmp_path, _pm(for_date=date(2026, 11, 10)), report_day="2026-11-09")
    assert "寄り付き前の値（対象日は過ぎています" not in page
    assert "翌営業日向けの想定ギャップ" not in page
    assert "2026-11-10 寄り付き前 ／ 売買の助言ではありません" in page


def test_site_older_premarket_is_also_kept_and_labeled(tmp_path):
    page = _page(tmp_path, _pm(for_date=date(2026, 11, 6)), report_day="2026-11-10")
    assert "2026-11-06 寄り付き前の値（対象日は過ぎています・参考）" in page
    assert "翌営業日向けの想定ギャップ" in page


def test_site_accuracy_unknown_when_not_available(tmp_path):
    page = _page(tmp_path, _pm(corr=None, mae=None, mae_zero=None, direction_acc=None, eval_start=None, eval_end=None, eval_n=0))
    assert "検証に必要なデータが足りません" in page and "方向一致" not in page


def test_site_wording_has_no_assertions(tmp_path):
    page = _page(tmp_path, _pm())
    env = page.split('<section class="env">')[1].split("</section>")[0]
    assert not any(w in env for w in ("必ず", "確実", "上がる", "下がる"))
    assert "保証するものではありません" in env and env.count("保証") == 1


# ---------------- 追加の境界・先読み ----------------
def test_direction_zero_prediction_is_not_a_match():
    from analysis.macro_gap import evaluate_forecasts

    d = date(2026, 1, 5)
    assert evaluate_forecasts([(d, 0.0, -0.2), (d, 0.1, 0.2)]).direction_acc == 0.5  # 予測0は一致とみなさない


def test_market_gap_skips_zero_open():
    d1, d2 = date(2026, 11, 5), date(2026, 11, 6)
    bars = {"A": [_bar(d1, 100, 100), _bar(d2, 101, 101)], "B": [_bar(d1, 100, 100), DailyBar(d2, 0, 0, 0, 0, 1)]}
    assert market_overnight_gaps(bars, min_stocks=2) == {}  # 始値0の銘柄は除外 → 1銘柄だけで足りない
    assert market_overnight_gaps(bars, min_stocks=1)[d2] == pytest.approx(0.01)


def _two_regime_data():
    """前半は傾き0.2、直近40日は傾き0.8。直近の窓だけを使えば傾きは0.8になる。"""
    ds = _days(130)
    xs = [((i * 7) % 11 - 5) / 500 for i in range(len(ds))]
    us_bars, close = [], 100.0
    for d, x in zip(ds, xs):
        prev, close = close, close * (1 + x)
        us_bars.append(DailyBar(d, prev, max(prev, close), min(prev, close), close, 1))
    us_ret = returns_from_bars(us_bars)
    gaps = {}
    for i in range(2, len(ds) - 1):
        gaps[ds[i]] = (0.2 if i < len(ds) - 41 else 0.8) * us_ret[ds[i - 1]]
    return ds, us_bars, gaps


def test_window_uses_the_most_recent_pairs():
    ds, us_bars, gaps = _two_regime_data()
    gaps = {d: g for d, g in gaps.items() if d < ds[-1]}
    pm, _ = compute_premarket(gaps, us_bars, ds[-1], "t", window=40, min_n=20)
    assert pm.slope == pytest.approx(0.8)  # 古い期間（0.2）ではなく、直近の窓


def test_min_n_boundary_is_inclusive():
    ds, us_bars, _, gaps = _data(n_days=90)
    gaps = {d: g for d, g in gaps.items() if d < ds[-1]}
    pairs_available = len([d for d in gaps if any(b.trade_date < d for b in us_bars)])
    ok, _ = compute_premarket(gaps, us_bars, ds[-1], "t", window=250, min_n=pairs_available)
    ng, reason = compute_premarket(gaps, us_bars, ds[-1], "t", window=250, min_n=pairs_available + 1)
    assert ok is not None and ng is None and "データが足りません" in reason


def test_gaps_on_or_after_the_target_day_are_ignored():
    ds, us_bars, _, gaps = _data()
    for_date = ds[-1]
    past = {d: g for d, g in gaps.items() if d < for_date}
    base, _ = compute_premarket(past, us_bars, for_date, "t")
    leaked = dict(past)
    leaked[for_date] = 99.0                      # 対象日（予測したい日）の実際の値が混ざっても
    leaked[for_date + timedelta(days=1)] = -99.0  # それ以降があっても
    out, _ = compute_premarket(leaked, us_bars, for_date, "t")
    assert out == base
