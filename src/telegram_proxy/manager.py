# telegram_proxy/manager.py
"""QThread-based lifecycle manager for Telegram WSS proxy.

Integrates with PyQt6 event system — emits signals on status changes
so the UI page can update without polling.
"""

from PyQt6.QtCore import QThread, pyqtSignal, QTimer
from typing import Optional, Callable

from telegram_proxy import ProxyController
from telegram_proxy.wss_proxy import ProxyStats
from telegram_proxy.proxy_logger import get_proxy_logger


class TelegramProxyManager(QThread):
    """Manages proxy lifecycle from GUI thread.

    Signals:
        status_changed(bool)   — emitted when proxy starts/stops
        log_message(str)       — emitted on proxy log events
        stats_updated(object)  — emitted periodically with ProxyStats
    """

    status_changed = pyqtSignal(bool)
    log_message = pyqtSignal(str)
    stats_updated = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._controller: Optional[ProxyController] = None
        self._stats_timer: Optional[QTimer] = None
        self._proxy_logger = get_proxy_logger()

    @property
    def is_running(self) -> bool:
        return self._controller is not None and self._controller.is_running

    @property
    def stats(self) -> Optional[ProxyStats]:
        return self._controller.stats if self._controller else None

    @property
    def port(self) -> int:
        return self._controller.port if self._controller else 1353

    @property
    def mode(self) -> str:
        return self._controller.mode if self._controller else "socks5"

    @property
    def host(self) -> str:
        return self._controller.host if self._controller else "127.0.0.1"

    @property
    def proxy_logger(self):
        return self._proxy_logger

    def start_proxy(self, port: int = 1353, mode: str = "socks5", host: str = "127.0.0.1") -> bool:
        """Start the proxy. Thread-safe, non-blocking."""
        if self.is_running:
            return False

        self._controller = ProxyController(
            port=port,
            mode=mode,
            on_log=self._on_log,
            host=host,
        )
        ok = self._controller.start()
        if ok:
            self.status_changed.emit(True)
            self._start_stats_polling()
        else:
            self._on_log("Failed to start proxy")
        return ok

    def stop_proxy(self) -> None:
        """Stop the proxy. Thread-safe."""
        if not self._controller:
            return

        self._stop_stats_polling()
        self._controller.stop()
        self._controller = None
        self.status_changed.emit(False)

    def restart_proxy(self, port: int = 1353, mode: str = "socks5", host: str = "127.0.0.1") -> bool:
        """Restart with new config."""
        self.stop_proxy()
        return self.start_proxy(port, mode, host)

    def cleanup(self) -> None:
        """Called on app exit."""
        try:
            self._stop_stats_polling()
        except Exception:
            pass
        try:
            if self._controller:
                self._controller.stop()
        except Exception:
            pass
            self._controller = None

    def _on_log(self, msg: str) -> None:
        # Write to file logger + ring buffer (thread-safe)
        self._proxy_logger.log(msg)
        # Emit signal for backward compat (UI now uses drain() instead)
        self.log_message.emit(msg)

    def _start_stats_polling(self) -> None:
        if self._stats_timer is None:
            self._stats_timer = QTimer()
            self._stats_timer.timeout.connect(self._emit_stats)
        self._stats_timer.start(2000)  # Every 2 seconds

    def _stop_stats_polling(self) -> None:
        if self._stats_timer:
            self._stats_timer.stop()

    def _emit_stats(self) -> None:
        if self._controller and self._controller.is_running:
            self.stats_updated.emit(self._controller.stats)
