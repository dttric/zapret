"""
tgram/tg_log_full.py
────────────────────
TgSendWorker — фоновый воркер для РУЧНОЙ отправки лога в Telegram.
Запускается только по явному действию пользователя (кнопка в UI).
Автоматическая периодическая отправка отключена.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from .tg_log_bot import send_log_file as send_log_via_bot


class TgSendWorker(QObject):
    """Воркер для ручной отправки лога (запускается пользователем из UI)."""
    finished = pyqtSignal(bool, float, str)  # ok, extra_wait_seconds, error_msg

    def __init__(self, path: str, caption: str, use_log_bot: bool = False, topic_id: Optional[int] = None, auth_code: str | None = None):
        super().__init__()
        self._path = path
        self._cap = caption
        self._use_log_bot = use_log_bot
        self._topic_id = topic_id
        self._auth_code = auth_code

    def run(self):
        try:
            if self._use_log_bot:
                success, error_msg = send_log_via_bot(self._path, self._cap, topic_id=self._topic_id, auth_code=self._auth_code)
                if success:
                    self.finished.emit(True, 0.0, "")
                else:
                    is_flood = "wait" in (error_msg or "").lower() or "частые" in (error_msg or "").lower()
                    extra_wait = 60.0 if is_flood else 0.0
                    self.finished.emit(False, extra_wait, error_msg or "Неизвестная ошибка")
            else:
                from tgram import send_file_to_tg
                ok = send_file_to_tg(self._path, self._cap)
                self.finished.emit(ok, 0.0, "" if ok else "Не удалось отправить файл")

        except Exception as e:
            error_msg = str(e)
            is_flood_wait = "429" in error_msg or "Too Many Requests" in error_msg
            extra_wait = 60.0 if is_flood_wait else 0.0
            self.finished.emit(False, extra_wait, error_msg)
