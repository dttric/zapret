# zapret1_launcher/strategy_runner.py
"""
Strategy runner for Zapret 1 (winws.exe).

Supports hot-reload via ConfigFileWatcher when the launch preset file changes.
Does NOT support Lua functionality.
Writes args to a launch preset file and launches winws.exe via @file syntax.
"""

import os
import subprocess
import threading
import time
from typing import Optional, List, Callable
from log import log

from launcher_common.constants import CREATE_NO_WINDOW
from launcher_common.runner_base import StrategyRunnerBase
from dpi.process_health_check import (
    check_common_crash_causes,
    diagnose_startup_error
)


def _launch_args_from_preset_text(content: str) -> list[str]:
    """Build argv directly from a source preset file.

    The source preset may contain UI metadata lines like `# Preset: ...`.
    Keep the source file human-readable, but strip metadata comments before
    launching winws.exe.
    """
    args: list[str] = []
    for raw in str(content or "").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        args.append(stripped)
    return args


class ConfigFileWatcher:
    """
    Monitors preset file changes for hot-reload.

    Watches a config file and calls callback when modification time changes.
    Runs in a background thread with configurable polling interval.
    """

    def __init__(self, file_path: str, callback: Callable[[], None], interval: float = 1.0):
        self._file_path = file_path
        self._callback = callback
        self._interval = interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_mtime: Optional[float] = None

        if os.path.exists(self._file_path):
            self._last_mtime = os.path.getmtime(self._file_path)

    def start(self):
        """Start watching the file in background thread"""
        if self._running:
            log("ConfigFileWatcher already running", "DEBUG")
            return
        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True, name="ConfigFileWatcherV1")
        self._thread.start()
        log(f"ConfigFileWatcher started for: {self._file_path}", "DEBUG")

    def stop(self):
        """Stop watching the file"""
        if not self._running:
            return
        self._running = False
        watcher_thread = self._thread
        if watcher_thread and watcher_thread.is_alive():
            if watcher_thread is threading.current_thread():
                log("ConfigFileWatcherV1.stop called from watcher thread; skip self-join", "DEBUG")
            else:
                watcher_thread.join(timeout=2.0)
        self._thread = None
        log("ConfigFileWatcher stopped", "DEBUG")

    def _watch_loop(self):
        """Main watch loop - polls file for changes"""
        while self._running:
            try:
                if os.path.exists(self._file_path):
                    current_mtime = os.path.getmtime(self._file_path)
                    if self._last_mtime is not None and current_mtime != self._last_mtime:
                        log(f"Config file changed: {self._file_path}", "INFO")
                        self._last_mtime = current_mtime
                        try:
                            self._callback()
                        except Exception as e:
                            log(f"Error in config change callback: {e}", "ERROR")
                    self._last_mtime = current_mtime
            except Exception as e:
                log(f"Error checking file modification: {e}", "DEBUG")

            sleep_remaining = self._interval
            while sleep_remaining > 0 and self._running:
                time.sleep(min(0.1, sleep_remaining))
                sleep_remaining -= 0.1


class StrategyRunnerV1(StrategyRunnerBase):
    """
    Runner for Zapret 1 (winws.exe).
    Simple version without hot-reload and Lua functionality.
    """

    def __init__(self, winws_exe_path: str):
        """
        Args:
            winws_exe_path: Path to winws.exe
        """
        super().__init__(winws_exe_path)
        # Human-readable last start error (for UI/status).
        self.last_error: Optional[str] = None

        # Config file watcher for hot-reload on preset change
        self._config_watcher: Optional[ConfigFileWatcher] = None
        self._preset_file_path: Optional[str] = None

    def _set_last_error(self, message: Optional[str]) -> None:
        try:
            text = str(message or "").strip()
        except Exception:
            text = ""
        self.last_error = text or None
        if text:
            self._notify_ui_launch_error(text)

    @staticmethod
    def _notify_ui_launch_error(message: str) -> None:
        """Best-effort UI notification from any thread (queued to main Qt thread)."""
        text = str(message or "").strip()
        if not text:
            return
        try:
            from PyQt6.QtCore import QMetaObject, Qt, Q_ARG
            from PyQt6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is None:
                return

            target = app.activeWindow()
            if target is None or not hasattr(target, "show_dpi_launch_error"):
                for widget in app.topLevelWidgets():
                    if hasattr(widget, "show_dpi_launch_error"):
                        target = widget
                        break

            if target is not None and hasattr(target, "show_dpi_launch_error"):
                QMetaObject.invokeMethod(
                    target,
                    "show_dpi_launch_error",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, text),
                )
        except Exception:
            pass

    def _on_config_changed(self) -> None:
        """Called when the launch preset file changes. Performs full restart."""
        log("Launch preset file changed, restarting winws.exe...", "INFO")
        try:
            if self._preset_file_path and os.path.exists(self._preset_file_path):
                self.start_from_preset_file(
                    self._preset_file_path,
                    strategy_name=self.current_strategy_name or "Preset",
                )
        except Exception as e:
            log(f"Error restarting after config change: {e}", "ERROR")

    def _start_config_watcher(self, preset_file: str) -> None:
        """Starts config file watcher for hot-reload."""
        # Stop existing watcher
        if self._config_watcher:
            self._config_watcher.stop()
            self._config_watcher = None

        self._config_watcher = ConfigFileWatcher(
            file_path=preset_file,
            callback=self._on_config_changed,
            interval=1.0,
        )
        self._config_watcher.start()

    def start_from_preset_file(self, preset_path: str, strategy_name: str = "Preset", _retry_count: int = 0) -> bool:
        """
        Starts strategy directly from an existing preset file via @file syntax.

        This is the primary path for ordinary direct_zapret1 launch.
        Unlike the old approach, does NOT re-parse/rewrite the file.
        Preset file must already contain resolved paths (lists/X, bin/X).
        """
        MAX_RETRIES = 2

        if not os.path.exists(preset_path):
            log(f"Preset file not found: {preset_path}, attempting selected-source refresh...", "WARNING")
            try:
                from core.services import get_direct_flow_coordinator

                get_direct_flow_coordinator().ensure_selected_source_path("direct_zapret1")
                if os.path.exists(preset_path):
                    log(f"Preset file became available after refresh: {preset_path}", "INFO")
            except Exception as e:
                log(f"Selected-source refresh failed: {e}", "WARNING")

        if not os.path.exists(preset_path):
            log(f"Preset file not found: {preset_path}", "ERROR")
            self._set_last_error(f"Preset файл не найден: {preset_path}")
            return False

        self._set_last_error(None)

        try:
            with open(preset_path, "r", encoding="utf-8", errors="replace") as f:
                launch_args = _launch_args_from_preset_text(f.read())
        except Exception as e:
            log(f"Failed to read preset file '{preset_path}': {e}", "ERROR")
            self._set_last_error(f"Не удалось прочитать preset файл: {e}")
            return False

        if not launch_args:
            self._set_last_error("Не удалось подготовить аргументы запуска из preset файла")
            return False

        try:
            # Stop previous process
            if self.running_process and self.is_running():
                log("Stopping previous process before starting new one", "INFO")
                self.stop()

            from utils.process_killer import kill_winws_force

            if _retry_count > 0:
                self._aggressive_windivert_cleanup()
            else:
                log("Cleaning up previous winws processes...", "DEBUG")
                kill_winws_force()
                self._fast_cleanup_services()

                try:
                    from utils.service_manager import unload_driver
                    for driver in ["WinDivert", "WinDivert14", "WinDivert64", "Monkey"]:
                        try:
                            unload_driver(driver)
                        except Exception:
                            pass
                except Exception:
                    pass

                time.sleep(0.3)

            # Self-healing: verify winws.exe still exists
            if not os.path.exists(self.winws_exe):
                log(f"winws.exe disappeared: {self.winws_exe}", "ERROR")
                self._set_last_error(f"winws.exe не найден: {self.winws_exe}")
                return False

            # Store preset file path for hot-reload
            self._preset_file_path = preset_path

            cmd = [self.winws_exe, *launch_args]

            log(f"Starting from preset file: {preset_path}", "INFO")
            log(f"Strategy: {strategy_name}" + (f" (attempt {_retry_count + 1})" if _retry_count > 0 else ""), "INFO")

            # Start process
            self.running_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                startupinfo=self._create_startup_info(),
                creationflags=CREATE_NO_WINDOW,
                cwd=self.work_dir
            )

            # Save info
            self.current_strategy_name = strategy_name
            self.current_strategy_args = list(launch_args)

            # Quick startup check
            time.sleep(0.2)

            if self.running_process.poll() is None:
                log(f"Strategy '{strategy_name}' started from preset (PID: {self.running_process.pid})", "SUCCESS")
                self._start_config_watcher(preset_path)
                self._set_last_error(None)
                return True
            else:
                exit_code = self.running_process.returncode
                log(f"Strategy '{strategy_name}' exited immediately (code: {exit_code})", "ERROR")

                stderr_output = ""
                try:
                    stderr_output = self.running_process.stderr.read().decode('utf-8', errors='ignore')
                    if stderr_output:
                        log(f"Error: {stderr_output[:500]}", "ERROR")
                except Exception:
                    pass

                from dpi.process_health_check import diagnose_winws_exit
                diag = diagnose_winws_exit(exit_code, stderr_output)
                if diag:
                    prefix = f"[AUTOFIX:{diag.auto_fix}]" if diag.auto_fix else ""
                    self._set_last_error(f"{prefix}{diag.cause}. {diag.solution}")
                    log(f"Diagnosis: {diag.cause} | Fix: {diag.solution} | auto_fix={diag.auto_fix}", "INFO")
                else:
                    first_line = ""
                    try:
                        first_line = next((ln.strip() for ln in (stderr_output or "").splitlines() if ln.strip()), "")
                    except Exception:
                        first_line = ""
                    if first_line:
                        self._set_last_error(f"winws завершился сразу (код {exit_code}): {first_line[:200]}")
                    else:
                        self._set_last_error(f"winws завершился сразу (код {exit_code})")

                self.running_process = None
                self.current_strategy_name = None
                self.current_strategy_args = None

                # System-level errors — don't retry
                if self._is_windivert_system_error(stderr_output, exit_code):
                    log("WinDivert system error — retry will not help", "WARNING")
                    return False

                # Retryable conflict
                if self._is_windivert_conflict_error(stderr_output, exit_code) and _retry_count < MAX_RETRIES:
                    log(f"Detected WinDivert conflict, automatic retry ({_retry_count + 1}/{MAX_RETRIES})...", "INFO")
                    return self.start_from_preset_file(preset_path, strategy_name, _retry_count + 1)

                if not diag:
                    causes = check_common_crash_causes()
                    if causes:
                        log("Possible causes:", "INFO")
                        for line in causes.split('\n')[:5]:
                            log(f"  {line}", "INFO")

                return False

        except Exception as e:
            diagnosis = diagnose_startup_error(e, self.winws_exe)
            for line in diagnosis.split('\n'):
                log(line, "ERROR")

            try:
                self._set_last_error(diagnosis.split("\n")[0].strip())
            except Exception:
                self._set_last_error(None)

            import traceback
            log(traceback.format_exc(), "DEBUG")
            self.running_process = None
            self.current_strategy_name = None
            self.current_strategy_args = None
            return False

    def stop(self) -> bool:
        """Stops running process and hot-reload watcher."""
        if self._config_watcher:
            self._config_watcher.stop()
            self._config_watcher = None

        self._preset_file_path = None
        return super().stop()
