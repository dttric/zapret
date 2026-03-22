# tg_log_delta.py

"""
Telegram log helpers.
Отправка логов ТОЛЬКО вручную по кнопке пользователя в UI.
Автоматическая отправка отключена — никакие данные не отправляются без явного действия пользователя.
"""

from __future__ import annotations
import os, sys, uuid, platform, pathlib, winreg
from typing import Optional
from config import APP_VERSION, CHANNEL

# ───────────── определяем, test это или нет ─────────────
IS_DEV_BUILD = True if CHANNEL == "test" else False

# ───────────── токены (из _build_secrets при сборке, иначе пусто) ───────────
try:
    from config._build_secrets import TG_LOG_BOT_TOKEN_PROD, TG_LOG_BOT_TOKEN_DEV, TG_LOG_CHAT_ID
except ImportError:
    TG_LOG_BOT_TOKEN_PROD = ""
    TG_LOG_BOT_TOKEN_DEV = ""
    TG_LOG_CHAT_ID = 0

CHAT_ID = TG_LOG_CHAT_ID

# Топик зависит от канала: test → 10854, stable → 1
TOPIC_ID = 10854 if IS_DEV_BUILD else 1

# Топик для ошибок (error/warning) - общий для всех версий
ERROR_TOPIC_ID = 12681

#  выбираем токен
TOKEN = TG_LOG_BOT_TOKEN_DEV if IS_DEV_BUILD else TG_LOG_BOT_TOKEN_PROD

MAX_CHUNK = 3500

# ---------- Client-ID ------------------------------------------------
def _reg_get() -> Optional[str]:
    from config import REGISTRY_PATH
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_PATH)
        cid, _ = winreg.QueryValueEx(k, "ClientID")
        return cid
    except Exception:
        return None

def _reg_set(cid: str):
    from config import REGISTRY_PATH
    k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGISTRY_PATH)
    winreg.SetValueEx(k, "ClientID", 0, winreg.REG_SZ, cid)

def get_client_id() -> str:
    if sys.platform.startswith("win"):
        cid = _reg_get()
        if cid:
            return cid
        cid = str(uuid.uuid4())
        _reg_set(cid)
        return cid
    path = pathlib.Path.home() / ".zapret_client_id"
    if path.exists():
        return path.read_text().strip()
    cid = str(uuid.uuid4())
    path.write_text(cid)
    return cid

CID  = get_client_id()
HOST = platform.node() or "unknown-pc"

# ---------- Telegram API (только для ручной отправки) -----------------
API = f"https://api.telegram.org/bot{TOKEN}"

from pathlib import Path
import requests

def _tg_api(method: str, files=None, data=None):
    url = f"{API}/{method}"
    r   = requests.post(url, files=files, data=data, timeout=30)
    r.raise_for_status()
    return r.json()

def send_log_to_tg(log_path: str | Path, caption: str = "") -> None:
    """Ручная отправка текста лога в Telegram (вызывается пользователем из UI)."""
    path = Path(log_path)
    text = path.read_text(encoding="utf-8-sig", errors="replace")[-4000:]
    data = {
        "chat_id": CHAT_ID,
        "message_thread_id": TOPIC_ID,
        "text": (caption + "\n\n" if caption else "") + text,
        "parse_mode": "HTML"
    }
    _tg_api("sendMessage", data=data)

def send_file_to_tg(file_path: str | Path, caption: str = "") -> None:
    """Ручная отправка файла лога в Telegram (вызывается пользователем из UI)."""
    path = Path(file_path)
    with path.open("rb") as fh:
        files = {"document": fh}
        data = {
            "chat_id": CHAT_ID,
            "message_thread_id": TOPIC_ID,
            "caption": caption or path.name
        }
        _tg_api("sendDocument", files=files, data=data)
