from backtest.engine import Metrics
from backtest.report import build_markdown, improved


def _m(avg_return, count=10, win_rate=0.5):
    return Metrics(count, count, 1.0, 5, win_rate, avg_return, 0.01, -0.01, 1.0)


def _results(base_train, base_valid, var_train, var_valid):
    def entry(train, valid):
        return {"train": {"buy": _m(train), "sell": _m(train)}, "valid": {"buy": _m(valid), "sell": _m(valid)}}

    return {"baseline": entry(base_train, base_valid), "v": entry(var_train, var_valid)}


def test_improved_requires_both_periods():
    assert improved(_results(-0.01, -0.02, 0.00, -0.01), "v", "buy") is True
    assert improved(_results(-0.01, -0.02, 0.00, -0.03), "v", "buy") is False  # 後半が悪化
    assert improved(_results(-0.01, -0.02, -0.02, -0.01), "v", "buy") is False  # 前半が悪化


def test_improved_equal_is_not_improved():
    assert improved(_results(-0.01, -0.01, -0.01, 0.0), "v", "buy") is False


def test_improved_none_is_not_improved():
    res = _results(-0.01, -0.01, 0.0, 0.0)
    res["v"]["valid"]["buy"] = _m(None)
    assert improved(res, "v", "buy") is False


def test_markdown_contains_marks_and_no_assertive_wording():
    md = build_markdown(
        _results(-0.01, -0.02, 0.00, -0.01), {"train": "前半", "valid": "後半"}
    )
    assert "| v | 10 | 100.0% | 50.0% | 0.00% |" in md
    rows = [l for l in md.splitlines() if l.startswith("| v |")]
    assert len(rows) == 4 and all(l.rstrip().endswith("✓ |") for l in rows)  # 買い・売り × 前半・後半
    assert "baseline" in md
    assert not any(w in md for w in ("必ず", "確実"))
    assert "保証するものではありません" in md


def test_positive_both_requires_positive_in_both_periods():
    from backtest.report import positive_both

    assert positive_both(_results(-0.01, -0.01, 0.002, 0.001), "v", "buy") is True
    assert positive_both(_results(-0.01, -0.01, 0.002, -0.001), "v", "buy") is False
    assert positive_both(_results(-0.01, -0.01, 0.0, 0.001), "v", "buy") is False  # 0はプラスではない
    res = _results(-0.01, -0.01, 0.002, 0.001)
    res["v"]["train"]["buy"] = _m(None)
    assert positive_both(res, "v", "buy") is False


def test_markdown_marks_double_circle_only_when_positive_in_both():
    md = build_markdown(_results(-0.01, -0.01, 0.002, 0.001), {"train": "前半", "valid": "後半"})
    rows = [l for l in md.splitlines() if l.startswith("| v |")]
    assert rows and all(l.rstrip().endswith("✓◎ |") for l in rows)
    md2 = build_markdown(_results(-0.01, -0.01, -0.002, -0.001), {"train": "前半", "valid": "後半"})
    assert "◎ |" not in "\n".join(l for l in md2.splitlines() if l.startswith("| v |"))
