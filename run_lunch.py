"""昼の予想（前場の動きの逆張り・試験運用）を作成する。平日11:50ごろ（昼休み）に実行する。"""

import sys

from intraday_runner import main

if __name__ == "__main__":
    sys.exit(main("lunch"))
