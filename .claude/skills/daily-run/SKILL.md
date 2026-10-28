---
name: daily-run
description: 日次リサーチ（run_daily.py）を実行してレポートを確認する手順。「今日のレポートを作って」「過去日を再実行して」と頼まれたときに使う。
---

# 日次リサーチ実行手順

1. `pip install -r requirements.txt` が済んでいるか確認する。
2. `python run_daily.py`（過去日は `--date YYYY-MM-DD`）を実行する。
   - 実行すると答え合わせ → 買い/売りスコアリング → `reports/`生成 → `docs/`生成 → git pushまで進む。
   - pushを伴うため、オーナーの依頼がある場合だけ実行する（rule: safe-operations）。
3. `reports/<日付>.md` を開き、次を確認して報告する。
   - 買い/売りTOP5と、各スコアの根拠
   - 取得失敗でスキップされた銘柄の有無
   - 断定表現が混ざっていないか
4. 休場日は当日データがなく「候補なし」になる想定。エラーではない。
