"""5分足の毎日保存のテスト（2026-11-11承認）。"""

import gzip
import json
from datetime import date, datetime, timedelta, timezone

from data_sources.base import IntradayBar
from tracking.bars_5m import save_5m_bars

JST = timezone(timedelta(hours=9))
DAY = date(2026, 11, 11)


class FakeSource:
    def get_intraday_bars(self, code, day):
        if code == "BAD":
            raise RuntimeError("取得失敗")
        if code == "EMPTY":
            return []
        return [
            IntradayBar(datetime(2026, 11, 11, 9, 0, tzinfo=JST), 100.0, 101.0, 99.5, 100.5, 1000),
            IntradayBar(datetime(2026, 11, 11, 9, 5, tzinfo=JST), 100.5, 102.0, 100.0, 101.5, 800),
        ]


def test_saves_only_codes_with_bars_and_survives_failures(tmp_path):
    path, n = save_5m_bars(FakeSource(), ["1111", "BAD", "EMPTY", "2222"], DAY, tmp_path)
    assert n == 2 and path == tmp_path / "2026-11-11.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as f:
        data = json.load(f)
    assert set(data) == {"1111", "2222"}
    assert data["1111"][0] == ["09:00", 100.0, 101.0, 99.5, 100.5, 1000]
    assert len(data["1111"]) == 2


def test_nothing_saved_when_no_data(tmp_path):
    path, n = save_5m_bars(FakeSource(), ["BAD", "EMPTY"], DAY, tmp_path)
    assert path is None and n == 0
    assert not list(tmp_path.iterdir())


def test_rerun_overwrites_same_day_file(tmp_path):
    save_5m_bars(FakeSource(), ["1111"], DAY, tmp_path)
    path, n = save_5m_bars(FakeSource(), ["1111", "2222"], DAY, tmp_path)
    assert n == 2 and len(list(tmp_path.iterdir())) == 1
