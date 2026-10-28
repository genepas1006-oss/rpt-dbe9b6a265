from report.one_point_summary import build_one_point_summary


def test_up_day_with_volume_surge_closing_high():
    text = build_one_point_summary(day_open=995, day_high=1005, day_low=965, day_close=970 + 35, volume_ratio=2.5)
    # close=1005(=high) -> close_position=1.0
    assert text == "寄り付きから上昇して、出来高が急増し、高値圏で引けた。"


def test_down_day_closing_low():
    text = build_one_point_summary(day_open=1000, day_high=1010, day_low=965, day_close=970, volume_ratio=1.0)
    # close_position = (970-965)/(1010-965) = 0.111
    assert text == "寄り付きから下落して、安値圏で引けた。"


def test_flat_day_mid_range_no_volume_mention():
    text = build_one_point_summary(day_open=1000, day_high=1010, day_low=990, day_close=1000, volume_ratio=1.0)
    assert text == "寄り付き水準からほぼ横ばいで、中間圏で引けた。"


def test_no_range_day_uses_neutral_close_position():
    text = build_one_point_summary(day_open=1000, day_high=1000, day_low=1000, day_close=1000, volume_ratio=1.0)
    assert text == "寄り付き水準からほぼ横ばいで、中間圏で引けた。"


from report.one_point_summary import build_outlook

BUY_UP_VOL = "買いの勢いが翌日に持ち越され、続伸する可能性がある。ただし利益確定売りで寄り付き後に押す場面にも注意。"
FLAT = "方向感は定まっておらず、寄り付きの強弱を見極めたい。"


def test_outlook_buy_high_close_with_volume():
    assert build_outlook("buy", 1005, 965, 1005, 2.5) == BUY_UP_VOL  # pos=1.0


def test_outlook_buy_high_close_normal_volume():
    # pos=18/20=0.9
    assert build_outlook("buy", 1010, 990, 1008, 1.0) == "出来高を伴わない上昇のため、続伸には出来高の増加が条件。"


def test_outlook_buy_mid_close():
    assert build_outlook("buy", 1010, 990, 1000, 1.0) == FLAT  # pos=0.5


def test_outlook_buy_low_close():
    # pos=5/45=0.11
    assert build_outlook("buy", 1010, 965, 970, 1.0) == "売りに押された形で、翌日は戻りが鈍い可能性がある。"


def test_outlook_sell_low_close_with_volume():
    assert "続落する可能性" in build_outlook("sell", 1010, 965, 970, 2.0)


def test_outlook_sell_high_close():
    assert "逆行" in build_outlook("sell", 1010, 990, 1008, 1.0)


def test_outlook_no_range_is_neutral():
    assert build_outlook("buy", 1000, 1000, 1000, 1.0) == FLAT


def test_outlook_has_no_assertive_wording():
    for side in ("buy", "sell"):
        for close in (965, 1000, 1010):
            for vol in (1.0, 2.5):
                text = build_outlook(side, 1010, 965, close, vol)
                assert not any(w in text for w in ("必ず", "保証", "確実"))
