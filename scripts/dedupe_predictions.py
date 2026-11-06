"""予測DBに溜まった重複（同じ日の複数回実行）を掃除する。

予測日・side（買い/売り）ごとに、一番新しい登録分（created_at が最大の組）だけを残す。
既定は確認のみ（削除しない）。実際に削除するときは --apply を付ける。

使い方:
    python scripts/dedupe_predictions.py            # 消す件数を表示するだけ
    python scripts/dedupe_predictions.py --apply    # 実際に削除
"""

import argparse
import sqlite3
import sys

DB_PATH = "data/predictions.db"


def find_duplicate_ids(conn: sqlite3.Connection) -> list[tuple[str, str, list[int]]]:
    """(予測日, side, 削除対象id一覧) を返す。削除対象のある組だけ。"""
    result = []
    groups = conn.execute(
        "SELECT prediction_date, side, MAX(created_at) FROM predictions "
        "GROUP BY prediction_date, side"
    ).fetchall()
    for prediction_date, side, latest in groups:
        ids = [
            r[0]
            for r in conn.execute(
                "SELECT id FROM predictions WHERE prediction_date = ? AND side = ? "
                "AND created_at < ?",
                (prediction_date, side, latest),
            )
        ]
        if ids:
            result.append((prediction_date, side, ids))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="実際に削除する")
    parser.add_argument("--db", default=DB_PATH)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        dups = find_duplicate_ids(conn)
        if not dups:
            print("重複はありません。")
            return 0
        total = 0
        for prediction_date, side, ids in dups:
            print(f"{prediction_date} {side}: 古い登録分 {len(ids)}件")
            total += len(ids)
        if not args.apply:
            print(f"合計 {total}件が削除対象です（--apply で削除）。")
            return 0
        for _, _, ids in dups:
            conn.executemany("DELETE FROM predictions WHERE id = ?", [(i,) for i in ids])
        conn.commit()
        print(f"{total}件を削除しました。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
