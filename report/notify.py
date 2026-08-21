"""Windowsデスクトップ通知（バルーン通知）。

タスクスケジューラでの自動実行完了をユーザーに知らせるためのもの。
Claude Codeセッションの起動状態には依存せず、PCが起動していれば表示される。
"""

import subprocess

_SCRIPT_TEMPLATE = """
Add-Type -AssemblyName System.Windows.Forms
$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = [System.Drawing.SystemIcons]::Information
$notify.Visible = $true
$notify.BalloonTipTitle = '{title}'
$notify.BalloonTipText = '{message}'
$notify.ShowBalloonTip(10000)
Start-Sleep -Seconds 5
$notify.Dispose()
"""


def _escape(text: str) -> str:
    return text.replace("'", "''")


def notify_windows(title: str, message: str) -> None:
    """Windowsのデスクトップ通知を表示する。

    通知に失敗しても例外を送出しない（通知の失敗でレポート生成本体を止めないため）。
    """
    script = _SCRIPT_TEMPLATE.format(title=_escape(title), message=_escape(message))
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            capture_output=True,
            timeout=30,
        )
    except Exception:
        pass
