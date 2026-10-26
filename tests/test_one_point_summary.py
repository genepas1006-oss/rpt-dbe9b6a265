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
