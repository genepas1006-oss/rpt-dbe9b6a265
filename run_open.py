"""寄り枠（寄り付きのギャップの逆張り・試験運用）を作成する。平日9:25ごろに実行する。"""

import sys

from intraday_runner import main

if __name__ == "__main__":
    sys.exit(main("open"))
