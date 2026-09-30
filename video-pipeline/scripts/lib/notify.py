"""macOS notification + optional Telegram ping."""
from __future__ import annotations

import os
import subprocess

import httpx


def notify(title: str, message: str) -> None:
    safe = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{safe(message)}" with title "{safe(title)}"'],
            check=False, capture_output=True, timeout=10,
        )
    except Exception:
        pass
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if token and chat:
        try:
            httpx.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": f"{title}: {message}"}, timeout=10,
            )
        except Exception:
            pass
