"""5分足の毎日保存（2026-11-11承認）。

yfinance の5分足は直近約60日分しか取れないため、後から「最大含み益・最大含み損が何時に起きたか」
「利確と損切りのどちらが先だったか」を調べられるよう、毎日の大引け後に全銘柄の5分足を保存しておく。
保存先は data/bars_5m/YYYY-MM-DD.json.gz（data/ は .gitignore 対象）。画面・成績には使わない（データを溜めるだけ）。
1銘柄の取得失敗で全体を止めない。保存の失敗も、レポート作成を止めない。
"""

import gzip
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from data_sources.base import DataSource

DEFAULT_DIR = Path("data/bars_5m")


def save_5m_bars(
    source: DataSource,
    codes: list[str],
    day: date,
    out_dir: Path = DEFAULT_DIR,
    workers: int = 6,
) -> tuple[Path | None, int]:
    """全銘柄の当日の5分足を保存し、(保存先, 保存できた銘柄数) を返す。1銘柄も取れなければ保存しない。"""

    def job(code: str):
        try:
            bars = source.get_intraday_bars(code, day)
        except Exception:  # noqa: BLE001
            return code, []
        return code, [[b.start.strftime("%H:%M"), b.open, b.high, b.low, b.close, b.volume] for b in bars]

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(job, codes))
    data = {code: rows for code, rows in results if rows}
    if not data:
        return None, 0
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day.isoformat()}.json.gz"
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    tmp.replace(path)
    return path, len(data)
