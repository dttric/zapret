# zapret2_launcher/strategy_runner.py
"""
Strategy runner for Zapret 2 (winws2.exe) with hot-reload support.

This version:
- Supports hot-reload via ConfigFileWatcher
- Monitors preset-zapret2.txt for changes
- Automatically restarts process when config changes
- Uses winws2.exe executable
"""

import os
import re
import subprocess
import time
import threading
from typing import Optional, List, Callable
from datetime import datetime

from log import log
from launcher_common.runner_base import StrategyRunnerBase, log_full_command
from launcher_common.args_filters import apply_all_filters
from utils.circular_strategy_numbering import (
    renumber_circular_strategies,
    strip_strategy_tags,
)
from launcher_common.constants import SW_HIDE, CREATE_NO_WINDOW, STARTF_USESHOWWINDOW
from dpi.process_health_check import (
    check_process_health,
    get_last_crash_info,
    check_common_crash_causes,
    check_conflicting_processes,
    get_conflicting_processes_report,
    diagnose_startup_error
)


_WINDOWS_ABS_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


def _is_windows_abs(path: str) -> bool:
    try:
        return bool(_WINDOWS_ABS_RE.match(str(path or "")))
    except Exception:
        return False


def _strip_outer_quotes(value: str) -> str:
    v = str(value or "").strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        v = v[1:-1]
    return v.strip()


class ConfigFileWatcher:
    """
    Monitors preset file changes for hot-reload.

    Watches a config file and calls callback when modification time changes.
    Runs in a background thread with configurable polling interval.
    """

    def __init__(self, file_path: str, callback: Callable[[], None], interval: float = 1.0):
        """
        Initialize config file watcher.

        Args:
            file_path: Path to file to monitor
            callback: Function to call when file changes
            interval: Polling interval in seconds (default 1.0)
        """
        self._file_path = file_path
        self._callback = callback
        self._interval = interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_mtime: Optional[float] = None

        # Get initial modification time
        if os.path.exists(self._file_path):
            self._last_mtime = os.path.getmtime(self._file_path)

    def start(self):
        """Start watching the file in background thread"""
        if self._running:
            log("ConfigFileWatcher already running", "DEBUG")
            return

        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True, name="ConfigFileWatcher")
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
                log("ConfigFileWatcher.stop called from watcher thread; skip self-join", "DEBUG")
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

                        # Call callback in try-except to prevent thread crash
                        try:
                            self._callback()
                        except Exception as e:
                            log(f"Error in config change callback: {e}", "ERROR")

                    self._last_mtime = current_mtime

            except Exception as e:
                log(f"Error checking file modification: {e}", "DEBUG")

            # Sleep in small intervals to allow quick stop
            sleep_remaining = self._interval
            while sleep_remaining > 0 and self._running:
                time.sleep(min(0.1, sleep_remaining))
                sleep_remaining -= 0.1


class StrategyRunnerV2(StrategyRunnerBase):
    """
    Runner for Zapret 2 (winws2.exe) with hot-reload support.

    Features:
    - Hot-reload: automatically restarts when preset-zapret2.txt changes
    - Full Lua support
    - Uses winws2.exe executable
    """

    def __init__(self, winws_exe_path: str):
        """
        Initialize V2 strategy runner.

        Args:
            winws_exe_path: Path to winws2.exe
        """
        super().__init__(winws_exe_path)
        self._config_watcher: Optional[ConfigFileWatcher] = None
        self._preset_file_path: Optional[str] = None
        self._runtime_preset_file_path: Optional[str] = None
        # Human-readable last start error (for UI/status).
        self.last_error: Optional[str] = None

        log(f"StrategyRunnerV2 initialized with hot-reload support", "INFO")

    def get_preset_filename(self) -> str:
        """Returns preset filename for Zapret 2 based on current launch method"""
        try:
            from strategy_menu import get_strategy_launch_method
            method = get_strategy_launch_method()
            if method == "direct_zapret2_orchestra":
                return "preset-zapret2-orchestra.txt"
        except Exception:
            pass
        return "preset-zapret2.txt"

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

    def validate_preset_file(self, preset_path: str) -> tuple[bool, str]:
        """Validates that preset references point to existing files.

        Returns:
            (ok, message)
              - ok=True if everything looks good
              - message contains a human-readable report on failure
        """
        p = str(preset_path or "").strip()
        if not p:
            return False, "Не указан путь к preset файлу"
        if not os.path.exists(p):
            return False, f"Preset файл не найден: {p}"

        missing = self._collect_missing_preset_references(p)
        if not missing:
            return True, ""

        max_show = 15
        shown = missing[:max_show]
        hidden = len(missing) - len(shown)

        example = shown[0][0] if shown else ""
        if example:
            header = f"Preset содержит ссылки на отсутствующие файлы ({len(missing)}), например: {example}"
        else:
            header = f"Preset содержит ссылки на отсутствующие файлы ({len(missing)}):"

        lines: list[str] = [header]
        for ref, expected in shown:
            if expected:
                lines.append(f"- {ref}  (ожидается: {expected})")
            else:
                lines.append(f"- {ref}")
        if hidden > 0:
            lines.append(f"... и еще {hidden} файл(ов)")

        return False, "\n".join(lines)

    def _collect_missing_preset_references(self, preset_path: str) -> list[tuple[str, str]]:
        """Returns list of (ref, expected_abs_path) for missing referenced files."""

        def _norm_slashes(s: str) -> str:
            return str(s or "").replace("\\", "/")

        def _resolve_candidates(raw_value: str, default_dir: Optional[str] = None) -> list[str]:
            v = str(raw_value or "").strip()
            if not v:
                return []

            # Some options allow @file values.
            if v.startswith("@"):
                v = v[1:].strip()

            v = _strip_outer_quotes(v)
            if not v:
                return []

            # Windows absolute should be detected even in non-Windows dev.
            if os.path.isabs(v) or _is_windows_abs(v):
                return [os.path.normpath(v)]

            # Relative with folders.
            if "/" in v or "\\" in v:
                return [os.path.normpath(os.path.join(self.work_dir, v))]

            # Bare filename: try default_dir first (lists/bin/lua), then work_dir.
            out: list[str] = []
            if default_dir:
                out.append(os.path.normpath(os.path.join(default_dir, v)))
            out.append(os.path.normpath(os.path.join(self.work_dir, v)))
            return out

        def _exists_any(paths: list[str]) -> bool:
            for p in paths:
                try:
                    if p and os.path.exists(p):
                        return True
                except Exception:
                    continue
            return False

        missing: list[tuple[str, str]] = []
        seen: set[str] = set()

        lists_dir = self.lists_dir
        bin_dir = self.bin_dir
        lua_dir = os.path.join(self.work_dir, "lua")
        filter_dir = os.path.join(self.work_dir, "windivert.filter")

        try:
            with open(preset_path, "r", encoding="utf-8", errors="ignore") as f:
                iterator = f
                for raw in iterator:
                    line = (raw or "").strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue

                    key, _sep, value = line.partition("=")
                    key_l = key.strip().lower()
                    value_s = value.strip()

                    # lists/*.txt
                    if key_l in ("--hostlist", "--ipset", "--hostlist-exclude", "--ipset-exclude"):
                        candidates = _resolve_candidates(value_s, default_dir=lists_dir)
                        if candidates and (not _exists_any(candidates)):
                            ref = f"{key.strip()}={_norm_slashes(_strip_outer_quotes(value_s).lstrip('@'))}"
                            expected = candidates[0] if candidates else ""
                            k = ref.lower()
                            if k not in seen:
                                seen.add(k)
                                missing.append((ref, expected))
                        continue

                    # lua/*.lua
                    if key_l == "--lua-init":
                        candidates = _resolve_candidates(value_s, default_dir=lua_dir)
                        if candidates and (not _exists_any(candidates)):
                            ref = f"{key.strip()}={_norm_slashes(_strip_outer_quotes(value_s).lstrip('@'))}"
                            expected = candidates[0] if candidates else ""
                            k = ref.lower()
                            if k not in seen:
                                seen.add(k)
                                missing.append((ref, expected))
                        continue

                    # windivert.filter/*
                    if key_l == "--wf-raw-part":
                        candidates = _resolve_candidates(value_s, default_dir=filter_dir)
                        if candidates and (not _exists_any(candidates)):
                            ref = f"{key.strip()}={_norm_slashes(_strip_outer_quotes(value_s).lstrip('@'))}"
                            expected = candidates[0] if candidates else ""
                            k = ref.lower()
                            if k not in seen:
                                seen.add(k)
                                missing.append((ref, expected))
                        continue

                    # Various bin-backed fake payload args (winws/winws2).
                    if key_l in (
                        "--dpi-desync-fake-syndata",
                        "--dpi-desync-fake-tls",
                        "--dpi-desync-fake-quic",
                        "--dpi-desync-fake-unknown-udp",
                        "--dpi-desync-split-seqovl-pattern",
                        "--dpi-desync-fake-http",
                        "--dpi-desync-fake-unknown",
                        "--dpi-desync-fakedsplit-pattern",
                        "--dpi-desync-fake-discord",
                        "--dpi-desync-fake-stun",
                        "--dpi-desync-fake-dht",
                        "--dpi-desync-fake-wireguard",
                    ):
                        special = _strip_outer_quotes(value_s.strip())
                        if special.startswith("@"):
                            special = special[1:].strip()
                        special = special.lower()
                        if special.startswith("0x") or special.startswith("!") or special.startswith("^"):
                            continue

                        # Only *.bin values are treated as file references here.
                        if not special.endswith(".bin"):
                            continue

                        candidates = _resolve_candidates(value_s, default_dir=bin_dir)
                        if candidates and (not _exists_any(candidates)):
                            ref = f"{key.strip()}={_norm_slashes(_strip_outer_quotes(value_s).lstrip('@'))}"
                            expected = candidates[0] if candidates else ""
                            k = ref.lower()
                            if k not in seen:
                                seen.add(k)
                                missing.append((ref, expected))
                        continue

                    # --blob=name:@path or --blob=name:+offset@path
                    if key_l == "--blob":
                        blob_value = _strip_outer_quotes(value_s)
                        if not blob_value or ":" not in blob_value:
                            continue

                        _name, _colon, tail = blob_value.partition(":")
                        tail = tail.strip()
                        if not tail:
                            continue

                        # Hex blobs / inline values.
                        if tail.lower().startswith("0x"):
                            continue

                        file_part = ""
                        if tail.startswith("@"):
                            file_part = tail[1:].strip()
                        elif tail.startswith("+"):
                            at_idx = tail.find("@")
                            if at_idx > 0 and at_idx < len(tail) - 1:
                                file_part = tail[at_idx + 1 :].strip()

                        if not file_part:
                            continue

                        candidates = _resolve_candidates(file_part, default_dir=bin_dir)
                        if candidates and (not _exists_any(candidates)):
                            ref = f"{key.strip()}={_norm_slashes(blob_value)}"
                            expected = candidates[0] if candidates else ""
                            k = ref.lower()
                            if k not in seen:
                                seen.add(k)
                                missing.append((ref, expected))
                        continue

        except Exception:
            return []

        return missing

    @staticmethod
    def _runtime_preset_path(source_preset_path: str) -> str:
        base, ext = os.path.splitext(source_preset_path)
        return f"{base}.runtime{ext or '.txt'}"

    @staticmethod
    def _write_text_file(path: str, content: str) -> None:
        data = (content or "").replace("\r\n", "\n").replace("\r", "\n")
        if data and not data.endswith("\n"):
            data += "\n"
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(data)

    def _prepare_launch_preset_file(self, source_preset_path: str) -> str:
        """Builds runtime preset with circular :strategy=N tags when needed.

        Source preset stays human-editable without explicit strategy tags.
        """
        self._runtime_preset_file_path = None

        try:
            with open(source_preset_path, "r", encoding="utf-8", errors="replace") as f:
                source_content = f.read()
        except Exception:
            return source_preset_path

        cleaned_source = strip_strategy_tags(source_content)
        if cleaned_source != source_content:
            try:
                self._write_text_file(source_preset_path, cleaned_source)
                log(f"Removed legacy :strategy=N tags from {source_preset_path}", "DEBUG")
            except Exception as e:
                log(f"Failed to clean preset file {source_preset_path}: {e}", "DEBUG")

        runtime_content = renumber_circular_strategies(cleaned_source)
        if runtime_content == cleaned_source:
            return source_preset_path

        runtime_path = self._runtime_preset_path(source_preset_path)
        try:
            self._write_text_file(runtime_path, runtime_content)
            self._runtime_preset_file_path = runtime_path
            return runtime_path
        except Exception as e:
            log(f"Failed to prepare runtime preset {runtime_path}: {e}", "WARNING")
            self._runtime_preset_file_path = None
            return source_preset_path

    def _on_config_changed(self):
        """
        Called when config file changes.
        Restarts process with new config.
        """
        log("Hot-reload triggered: config file changed", "INFO")

        if not self._preset_file_path or not os.path.exists(self._preset_file_path):
            log("Preset file not found, cannot hot-reload", "WARNING")
            return

        # Stop process only (keep watcher running)
        self._stop_process_only()

        # Small delay to ensure clean stop
        time.sleep(0.3)

        # Restart from preset file
        self._start_from_preset()

    def _stop_process_only(self):
        """
        Stops the process without stopping the config watcher.
        Used for hot-reload to keep monitoring the config file.
        """
        try:
            if self.running_process and self.is_running():
                pid = self.running_process.pid
                strategy_name = self.current_strategy_name or "unknown"

                log(f"Hot-reload: stopping process '{strategy_name}' (PID: {pid})", "INFO")

                # Soft stop
                self.running_process.terminate()

                try:
                    self.running_process.wait(timeout=3)
                    log(f"Process stopped for hot-reload (PID: {pid})", "SUCCESS")
                except subprocess.TimeoutExpired:
                    log("Soft stop timeout, force killing for hot-reload", "WARNING")
                    self.running_process.kill()
                    self.running_process.wait()

                self.running_process = None

            # Quick cleanup without full service removal
            self._kill_all_winws_processes()

        except Exception as e:
            log(f"Error stopping process for hot-reload: {e}", "ERROR")

    def _start_from_preset(self):
        """
        Starts process from existing preset file.
        Used for hot-reload after config change.
        """
        if not self._preset_file_path or not os.path.exists(self._preset_file_path):
            log("Cannot start from preset: file not found", "ERROR")
            self._runtime_preset_file_path = None
            return False

        try:
            launch_preset_path = self._prepare_launch_preset_file(self._preset_file_path)

            # Build command with @file
            cmd = [self.winws_exe, f"@{launch_preset_path}"]

            log(f"Hot-reload: starting from preset {self._preset_file_path}", "INFO")
            if launch_preset_path != self._preset_file_path:
                log(f"Hot-reload runtime preset: {launch_preset_path}", "DEBUG")

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

            # Quick startup check
            time.sleep(0.2)

            if self.running_process.poll() is None:
                log(f"Hot-reload successful (PID: {self.running_process.pid})", "SUCCESS")
                self.current_strategy_args = [f"@{launch_preset_path}"]
                return True
            else:
                exit_code = self.running_process.returncode
                log(f"Hot-reload failed: process exited (code: {exit_code})", "ERROR")

                try:
                    stderr_output = self.running_process.stderr.read().decode('utf-8', errors='ignore')
                    if stderr_output:
                        log(f"Error: {stderr_output[:500]}", "ERROR")
                except:
                    pass

                self.running_process = None
                self.current_strategy_args = None
                self._runtime_preset_file_path = None
                return False

        except Exception as e:
            log(f"Error starting from preset: {e}", "ERROR")
            self.running_process = None
            self.current_strategy_args = None
            self._runtime_preset_file_path = None
            return False

    def start_from_preset_file(
        self,
        preset_path: str,
        strategy_name: str = "Preset",
        _force_cleanup: bool = False,
        _retry_count: int = 0,
    ) -> bool:
        """
        Starts strategy directly from existing preset file.

        This is the new primary method for launching DPI - it uses an already
        prepared preset file instead of generating args from registry.

        Features:
        - Hot-reload support (monitors preset file for changes)
        - No registry access needed
        - Preset file already contains all arguments

        Args:
            preset_path: Path to preset file (e.g., preset-zapret2.txt)
            strategy_name: Strategy name for logs

        Returns:
            True if strategy started successfully
        """
        from utils.process_killer import kill_winws_force, get_process_pids

        if not os.path.exists(preset_path):
            log(f"Preset file not found: {preset_path}", "ERROR")
            self._set_last_error(f"Preset файл не найден: {preset_path}")
            return False

        try:
            self._set_last_error(None)
            launch_preset_path = self._prepare_launch_preset_file(preset_path)

            # If the exact preset is already running, do NOT restart it.
            # Just attach watcher + update runner state.
            pid = self.find_running_preset_pid(launch_preset_path)
            if pid:
                self._preset_file_path = preset_path
                self._runtime_preset_file_path = (
                    launch_preset_path if launch_preset_path != preset_path else None
                )
                self.current_strategy_name = strategy_name
                self.current_strategy_args = [f"@{launch_preset_path}"]
                log(f"Preset already running (PID: {pid}), attaching without restart", "INFO")
                self._start_config_watcher()
                return True

            # Preflight: validate referenced files before stopping/killing anything.
            ok, report = self.validate_preset_file(preset_path)
            if not ok:
                for line in (report or "").splitlines():
                    if line.strip():
                        log(line, "ERROR")
                try:
                    self._set_last_error((report or "").splitlines()[0].strip())
                except Exception:
                    self._set_last_error("Preset содержит ссылки на отсутствующие файлы")
                return False

            # Stop previous process and watcher
            cleanup_required = bool(_force_cleanup)

            if self.running_process and self.is_running():
                log("Stopping previous process before starting new one", "INFO")
                self.stop()
                cleanup_required = True

            # Не тратим время на полную очистку, если нет активных winws процессов.
            try:
                active_winws_pids = get_process_pids("winws.exe") + get_process_pids("winws2.exe")
            except Exception:
                active_winws_pids = []

            if active_winws_pids:
                cleanup_required = True

            # Cleanup (ускоренный путь: только когда реально нужно)
            if cleanup_required:
                log("Cleaning up previous winws processes...", "DEBUG")
                kill_winws_force()
                self._fast_cleanup_services()

                # Unload WinDivert drivers for complete cleanup
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
            else:
                log("Fast start: cleanup skipped (no active winws processes)", "DEBUG")

            # Store preset file path for hot-reload
            self._preset_file_path = preset_path
            self._runtime_preset_file_path = (
                launch_preset_path if launch_preset_path != preset_path else None
            )

            # Build command with @file
            cmd = [self.winws_exe, f"@{launch_preset_path}"]

            log(f"Starting from preset file: {preset_path}", "INFO")
            if launch_preset_path != preset_path:
                log(f"Using runtime preset file: {launch_preset_path}", "DEBUG")
            log(f"Strategy: {strategy_name}", "INFO")

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
            self.current_strategy_args = [f"@{launch_preset_path}"]

            # Quick startup check
            time.sleep(0.2)

            if self.running_process.poll() is None:
                log(f"Strategy '{strategy_name}' started from preset (PID: {self.running_process.pid})", "SUCCESS")

                # Start hot-reload watcher after successful start
                self._start_config_watcher()

                return True
            else:
                exit_code = self.running_process.returncode
                log(f"Strategy '{strategy_name}' exited immediately (code: {exit_code})", "ERROR")

                stderr_output = ""
                try:
                    stderr_output = self.running_process.stderr.read().decode('utf-8', errors='ignore')
                    if stderr_output:
                        log(f"Error: {stderr_output[:500]}", "ERROR")
                except:
                    pass

                # Diagnose the exit code + stderr for a human-readable error
                from dpi.process_health_check import diagnose_winws_exit
                diag = diagnose_winws_exit(exit_code, stderr_output)
                if diag:
                    prefix = f"[AUTOFIX:{diag.auto_fix}]" if diag.auto_fix else ""
                    self._set_last_error(f"{prefix}{diag.cause}. {diag.solution}")
                    log(f"Diagnosis: {diag.cause} | Fix: {diag.solution} | auto_fix={diag.auto_fix}", "INFO")
                else:
                    first_line = ""
                    try:
                        first_line = (stderr_output or "").strip().splitlines()[0].strip()
                    except Exception:
                        first_line = ""
                    if first_line:
                        self._set_last_error(f"winws2 завершился сразу (код {exit_code}): {first_line[:200]}")
                    else:
                        self._set_last_error(f"winws2 завершился сразу (код {exit_code})")

                self.running_process = None
                self.current_strategy_name = None
                self.current_strategy_args = None
                self._preset_file_path = None
                self._runtime_preset_file_path = None

                # System-level WinDivert errors (Secure Boot, service disabled, etc.)
                # are not fixable by cleanup/retry — skip retry.
                if self._is_windivert_system_error(stderr_output, exit_code):
                    log("WinDivert system error detected — retry will not help", "WARNING")
                    return False

                # Retryable WinDivert conflict (GUID collision, stale state)
                if (
                    (not cleanup_required)
                    and _retry_count == 0
                    and self._is_windivert_conflict_error(stderr_output, exit_code)
                ):
                    log("WinDivert conflict detected, retrying with full cleanup", "WARNING")
                    return self.start_from_preset_file(
                        preset_path,
                        strategy_name,
                        _force_cleanup=True,
                        _retry_count=1,
                    )

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
            self._preset_file_path = None
            self._runtime_preset_file_path = None
            return False

    def find_running_preset_pid(self, preset_path: str) -> Optional[int]:
        """Returns PID of winws2.exe running with @preset_path, if any."""
        try:
            import psutil

            target_exe = os.path.basename(self.winws_exe).lower()
            target_preset = os.path.normcase(os.path.normpath(os.path.abspath(preset_path)))

            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    name = (proc.info.get("name") or "").lower()
                    if name != target_exe:
                        continue

                    cmdline = proc.info.get("cmdline") or []
                    if not isinstance(cmdline, list):
                        continue

                    for arg in cmdline:
                        if not isinstance(arg, str):
                            continue
                        if not arg.startswith("@"):
                            continue

                        raw = arg[1:].strip().strip('"').strip()
                        if not raw:
                            continue

                        candidate = raw
                        if not os.path.isabs(candidate):
                            candidate = os.path.join(self.work_dir, candidate)

                        candidate_norm = os.path.normcase(os.path.normpath(os.path.abspath(candidate)))
                        if candidate_norm == target_preset:
                            return int(proc.info.get("pid"))
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
                except Exception:
                    continue

            return None
        except Exception:
            return None

    def _start_config_watcher(self):
        """Start watching the preset file for changes"""
        if self._config_watcher:
            self._stop_config_watcher()

        if self._preset_file_path and os.path.exists(self._preset_file_path):
            self._config_watcher = ConfigFileWatcher(
                self._preset_file_path,
                self._on_config_changed,
                interval=1.0
            )
            self._config_watcher.start()
            log(f"Config watcher started for: {self._preset_file_path}", "DEBUG")

    def _stop_config_watcher(self):
        """Stop watching the preset file"""
        if self._config_watcher:
            self._config_watcher.stop()
            self._config_watcher = None
            log("Config watcher stopped", "DEBUG")

    def start_strategy_custom(self, custom_args: List[str], strategy_name: str = "Custom Strategy", _retry_count: int = 0) -> bool:
        """
        Starts strategy with arbitrary arguments.

        V2 features:
        - Hot-reload support
        - Lua functionality supported
        - Writes to preset-zapret2.txt

        Args:
            custom_args: List of command line arguments
            strategy_name: Strategy name for logs
            _retry_count: Internal retry counter (don't pass externally)

        Returns:
            True if strategy started successfully
        """
        MAX_RETRIES = 2

        conflicting = check_conflicting_processes()
        if conflicting:
            warning_report = get_conflicting_processes_report()
            log(warning_report, "WARNING")

        try:
            # Stop previous process and watcher
            if self.running_process and self.is_running():
                log("Stopping previous process before starting new one", "INFO")
                self.stop()

            from utils.process_killer import kill_winws_force

            if _retry_count > 0:
                # Aggressive cleanup only on retry
                self._aggressive_windivert_cleanup()
            else:
                log("Cleaning up previous winws processes...", "DEBUG")
                kill_winws_force()

                self._fast_cleanup_services()

                # Unload WinDivert drivers for complete cleanup
                try:
                    from utils.service_manager import unload_driver
                    for driver in ["WinDivert", "WinDivert14", "WinDivert64", "Monkey"]:
                        try:
                            unload_driver(driver)
                        except:
                            pass
                except:
                    pass

                time.sleep(0.3)

            if not custom_args:
                log("No arguments for startup", "ERROR")
                return False

            # Resolve paths
            resolved_args = self._resolve_file_paths(custom_args)

            # Apply ALL filters in correct order
            resolved_args = apply_all_filters(resolved_args, self.lists_dir)

            # Write config to file
            preset_file = self._write_preset_file(resolved_args, strategy_name)

            # Store preset file path for hot-reload
            self._preset_file_path = preset_file

            # Build command with @file
            cmd = [self.winws_exe, f"@{preset_file}"]

            log(f"Starting strategy '{strategy_name}'" + (f" (attempt {_retry_count + 1})" if _retry_count > 0 else ""), "INFO")
            log(f"Config written to: {preset_file}", "DEBUG")
            log(f"Arguments count: {len(resolved_args)}", "DEBUG")

            # Save full command line for debugging
            log_full_command([self.winws_exe] + resolved_args, strategy_name)

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
            self.current_strategy_args = resolved_args.copy()

            # Quick startup check
            time.sleep(0.2)

            if self.running_process.poll() is None:
                log(f"Strategy '{strategy_name}' started (PID: {self.running_process.pid})", "SUCCESS")

                # Start hot-reload watcher after successful start
                self._start_config_watcher()

                return True
            else:
                exit_code = self.running_process.returncode
                log(f"Strategy '{strategy_name}' exited immediately (code: {exit_code})", "ERROR")

                stderr_output = ""
                try:
                    stderr_output = self.running_process.stderr.read().decode('utf-8', errors='ignore')
                    if stderr_output:
                        log(f"Error: {stderr_output[:500]}", "ERROR")
                except:
                    pass

                # Diagnose the exit code + stderr
                from dpi.process_health_check import diagnose_winws_exit
                diag = diagnose_winws_exit(exit_code, stderr_output)
                if diag:
                    prefix = f"[AUTOFIX:{diag.auto_fix}]" if diag.auto_fix else ""
                    self._set_last_error(f"{prefix}{diag.cause}. {diag.solution}")
                    log(f"Diagnosis: {diag.cause} | Fix: {diag.solution} | auto_fix={diag.auto_fix}", "INFO")

                self.running_process = None
                self.current_strategy_name = None
                self.current_strategy_args = None
                self._preset_file_path = None

                # System-level errors — don't retry
                if self._is_windivert_system_error(stderr_output, exit_code):
                    log("WinDivert system error — retry will not help", "WARNING")
                    return False

                # Retryable conflict — auto retry
                if self._is_windivert_conflict_error(stderr_output, exit_code) and _retry_count < MAX_RETRIES:
                    log(f"Detected WinDivert conflict, automatic retry ({_retry_count + 1}/{MAX_RETRIES})...", "INFO")
                    return self.start_strategy_custom(custom_args, strategy_name, _retry_count + 1)

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

            import traceback
            log(traceback.format_exc(), "DEBUG")
            self.running_process = None
            self.current_strategy_name = None
            self.current_strategy_args = None
            self._preset_file_path = None
            return False

    def stop(self) -> bool:
        """
        Stops running process and config watcher.

        Overrides base class to also stop the hot-reload watcher.
        """
        # Stop config watcher first
        self._stop_config_watcher()

        # Clear preset file path
        self._preset_file_path = None
        self._runtime_preset_file_path = None

        # Call base class stop
        return super().stop()


# Global instance
_strategy_runner_v2_instance: Optional[StrategyRunnerV2] = None


def get_strategy_runner_v2(winws_exe_path: str) -> StrategyRunnerV2:
    """
    Gets or creates global StrategyRunnerV2 instance.

    IMPORTANT: Recreates runner if different exe requested (mode switch).

    Args:
        winws_exe_path: Path to winws2.exe

    Returns:
        StrategyRunnerV2 instance
    """
    global _strategy_runner_v2_instance

    # Recreate runner if exe changed (mode switch)
    if _strategy_runner_v2_instance is not None:
        if _strategy_runner_v2_instance.winws_exe != winws_exe_path:
            log(f"Exe change: {_strategy_runner_v2_instance.winws_exe} -> {winws_exe_path}", "INFO")
            _strategy_runner_v2_instance = None

    if _strategy_runner_v2_instance is None:
        _strategy_runner_v2_instance = StrategyRunnerV2(winws_exe_path)
    return _strategy_runner_v2_instance


def reset_strategy_runner_v2():
    """Resets global instance (synchronously stops process and watcher)"""
    global _strategy_runner_v2_instance
    if _strategy_runner_v2_instance:
        _strategy_runner_v2_instance.stop()
    _strategy_runner_v2_instance = None


def invalidate_strategy_runner_v2():
    """
    Marks runner for recreation without synchronous stop.
    Used when switching launch method - UI updates instantly,
    old process will be stopped on next DPI start.
    """
    global _strategy_runner_v2_instance
    _strategy_runner_v2_instance = None


def get_current_runner_v2() -> Optional[StrategyRunnerV2]:
    """Returns current runner instance without creating new one"""
    return _strategy_runner_v2_instance
