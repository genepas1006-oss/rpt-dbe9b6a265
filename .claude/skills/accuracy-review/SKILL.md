---
name: accuracy-review
description: tracking/の予測記録と翌日実結果から、買い/売りそれぞれの的中傾向を振り返る手順。「的中率を見て」「検証フェーズの振り返り」と頼まれたときに使う。
---

# 的中傾向レビュー手順

1. `tracking/predictions_db.py` の `get_win_rate_stats` で買い・売りを別々に集計する。
2. 件数（サンプル数）を必ず併記する。件数が少ない間は「傾向を断定できない」と明記する。
3. 外れた事例を数件ピックアップし、スコア要素のどれが効いて/効かなかったかを考察する。
4. 改善案があれば提案する。ロジック変更は `new-scoring-logic` スキルの承認プロセスに乗せる。
5. 結果から「勝率保証」等の表現は使わない（rule: no-real-orders-no-guarantees）。
