"""予想セット（1回分の予想のまとまり）。作成時刻・データ基準・対象時間帯・有効期間を持つ。

承認済み設計（2026-11-11）: 「前日夜の予想を後場に使ってしまう」誤りを、画面と内部の両方で防ぐ。
    夜の予想（大引け後に作る翌営業日向け）: 有効期間は翌営業日の 9:00 以上〜11:30 未満（前場のみ）。後場は昼の予想（第2段階）を使う前提。
    有効期間は、開始時刻を含み、終了時刻は含まない。時刻は全て日本時間。
    状態: 開始前=待機 / 有効期間内=有効 / 終了後=期限切れ。
    バナーに出すセット: 有効なもののうち作成時刻が最も新しいもの。なければ、待機中で開始が最も早いもの。なければ表示なし。
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

JST = timezone(timedelta(hours=9))
AM_OPEN, AM_CLOSE = time(9, 0), time(11, 30)
PM_OPEN, PM_CLOSE = time(12, 30), time(15, 30)

SESSION_LABEL = {"am": "前場", "pm": "後場"}
SLOT_LABEL = {"evening": "夜の予想", "open": "寄り枠", "lunch": "昼の予想"}

ACTIVE, WAITING, EXPIRED = "active", "waiting", "expired"


@dataclass(frozen=True)
class ForecastSet:
    slot: str  # evening / open / lunch
    created_at: datetime | None  # 不明（古いレポートからの復元）ならNone
    data_as_of: datetime
    data_note: str  # 例: 大引け / 前場終了（約15分遅れのデータ）
    target_date: date
    session: str  # am / pm
    valid_from: datetime
    valid_until: datetime
    note: str

    @property
    def label(self) -> str:
        return f"{SLOT_LABEL[self.slot]}（{self.target_date.month}/{self.target_date.day} {SESSION_LABEL[self.session]}向け）"


def _at(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=JST)


def evening_set(prediction_date: date, target_date: date, created_at: datetime | None) -> ForecastSet:
    return ForecastSet(
        slot="evening",
        created_at=created_at,
        data_as_of=_at(prediction_date, PM_CLOSE),
        data_note="大引け",
        target_date=target_date,
        session="am",
        valid_from=_at(target_date, AM_OPEN),
        valid_until=_at(target_date, AM_CLOSE),
        note="前場（9:00〜11:30）向けの予想です。後場の売買には使えません。",
    )


def state_at(fs: ForecastSet, now: datetime) -> tuple[str, timedelta | None]:
    """（状態, 残り or 開始までの時間）。期限切れはNone。"""
    if now < fs.valid_from:
        return WAITING, fs.valid_from - now
    if now < fs.valid_until:
        return ACTIVE, fs.valid_until - now
    return EXPIRED, None


def pick_banner_set(sets: list[ForecastSet], now: datetime) -> ForecastSet | None:
    active = [s for s in sets if state_at(s, now)[0] == ACTIVE]
    if active:
        return max(active, key=lambda s: s.created_at or s.valid_from)
    waiting = [s for s in sets if state_at(s, now)[0] == WAITING]
    return min(waiting, key=lambda s: s.valid_from) if waiting else None


# ---- レポート（Markdown）への書き出し・読み込み ----
_FMT = "%Y-%m-%d %H:%M"


def fmt_md_hm(dt: datetime) -> str:
    return f"{dt.month}/{dt.day} {dt:%H:%M}"


def to_md_lines(fs: ForecastSet) -> list[str]:
    return [
        "## 予想セット",
        "",
        f"- 種別: {SLOT_LABEL[fs.slot]}（{fs.slot}）",
        f"- 作成: {fs.created_at.astimezone(JST).strftime(_FMT) if fs.created_at else '不明'}",
        f"- データ基準: {fs.data_as_of.astimezone(JST).strftime(_FMT)}（{fs.data_note}）",
        f"- 対象: {fs.target_date.isoformat()} {SESSION_LABEL[fs.session]}（{fs.session}）",
        f"- 有効: {fs.valid_from.isoformat()} 〜 {fs.valid_until.isoformat()}",
        f"- 注意: {fs.note}",
        "",
    ]


def from_md_body(body: str) -> ForecastSet | None:
    kv: dict[str, str] = {}
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("- ") and ": " in line:
            k, v = line.removeprefix("- ").split(": ", 1)
            kv[k.strip()] = v.strip()
    try:
        slot = kv["種別"].split("（")[1].rstrip("）")
        created = None if kv["作成"] == "不明" else datetime.strptime(kv["作成"], _FMT).replace(tzinfo=JST)
        as_of_text, _, note_part = kv["データ基準"].partition("（")
        target_text, _, sess_part = kv["対象"].partition(" ")
        valid_from, valid_until = (datetime.fromisoformat(x.strip()) for x in kv["有効"].split("〜"))
        return ForecastSet(
            slot=slot,
            created_at=created,
            data_as_of=datetime.strptime(as_of_text.strip(), _FMT).replace(tzinfo=JST),
            data_note=note_part.rstrip("）"),
            target_date=date.fromisoformat(target_text),
            session=sess_part.split("（")[1].rstrip("）"),
            valid_from=valid_from,
            valid_until=valid_until,
            note=kv.get("注意", ""),
        )
    except (KeyError, ValueError, IndexError):
        return None


def to_json_dict(fs: ForecastSet, set_id: str) -> dict:
    return {
        "id": set_id,
        "label": fs.label,
        "slot": fs.slot,
        "created_at": fs.created_at.astimezone(JST).isoformat() if fs.created_at else None,
        "valid_from": fs.valid_from.isoformat(),
        "valid_until": fs.valid_until.isoformat(),
        "target_date": fs.target_date.isoformat(),
        "note": fs.note,
    }
