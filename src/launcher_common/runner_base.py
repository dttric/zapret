# launcher_common/runner_base.py
"""Base class for strategy runners with shared functionality"""

import os
import subprocess
import time
from abc import ABC, abstractmethod
from typing import Optional, List, Dict
from datetime import datetime

from log import log
from config import LOGS_FOLDER
from .args_filters import apply_all_filters
from .constants import SW_HIDE, CREATE_NO_WINDOW, STARTF_USESHOWWINDOW
from dpi.process_health_check import (
    check_process_health, get_last_crash_info, check_common_crash_causes,
    check_conflicting_processes, get_conflicting_processes_report, diagnose_startup_error
)
from utils.args_resolver import resolve_args_paths
from utils.service_manager import (
    cleanup_windivert_services, stop_and_delete_service, unload_driver, service_exists
)
from utils.process_killer import kill_process_by_name, kill_winws_force


def log_full_command(cmd_list: List[str], strategy_name: str):
    """
    Writes full command line to a separate file for debugging.

    Args:
        cmd_list: List of command arguments
        strategy_name: Strategy name
    """
    try:
        os.makedirs(LOGS_FOLDER, exist_ok=True)

        cmd_log_file = os.path.join(LOGS_FOLDER, "commands_full.log")

        full_cmd_parts = []
        for i, arg in enumerate(cmd_list):
            if i == 0:
                full_cmd_parts.append(arg)
            else:
                if arg.startswith('"') and arg.endswith('"'):
                    full_cmd_parts.append(arg)
                elif ' ' in arg or '\t' in arg:
                    full_cmd_parts.append(f'"{arg}"')
                else:
                    full_cmd_parts.append(arg)

        full_cmd = ' '.join(full_cmd_parts)

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        separator = "=" * 80

        with open(cmd_log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{separator}\n")
            f.write(f"Timestamp: {timestamp}\n")
            f.write(f"Strategy: {strategy_name}\n")
            f.write(f"Command length: {len(full_cmd)} characters\n")
            f.write(f"Arguments count: {len(cmd_list) - 1}\n")
            f.write(f"{separator}\n")
            f.write(f"FULL COMMAND:\n")
            f.write(f"{full_cmd}\n")
            f.write(f"{separator}\n")

            f.write(f"ARGUMENTS LIST:\n")
            for i, arg in enumerate(cmd_list):
                f.write(f"[{i:3}]: {arg}\n")
            f.write(f"{separator}\n\n")

        last_cmd_file = os.path.join(LOGS_FOLDER, "last_command.txt")
        with open(last_cmd_file, 'w', encoding='utf-8') as f:
            f.write(f"# Last command executed at {timestamp}\n")
            f.write(f"# Strategy: {strategy_name}\n\n")
            f.write(full_cmd)

        log(f"Command saved to logs/commands_full.log", "DEBUG")

    except Exception as e:
        log(f"Error writing command to log: {e}", "DEBUG")


class StrategyRunnerBase(ABC):
    """Abstract base class for strategy runners"""

    def __init__(self, winws_exe_path: str):
        """
        Initialize base strategy runner.

        Args:
            winws_exe_path: Path to winws.exe or winws2.exe
        """
        self.winws_exe = os.path.abspath(winws_exe_path)
        self.running_process: Optional[subprocess.Popen] = None
        self.current_strategy_name: Optional[str] = None
        self.current_strategy_args: Optional[List[str]] = None

        # Verify exe exists
        if not os.path.exists(self.winws_exe):
            raise FileNotFoundError(f"Executable not found: {self.winws_exe}")

        # Determine working directories
        exe_dir = os.path.dirname(self.winws_exe)
        self.work_dir = os.path.dirname(exe_dir)
        self.bin_dir = os.path.join(self.work_dir, "bin")
        self.lists_dir = os.path.join(self.work_dir, "lists")

        log(f"{self.__class__.__name__} initialized. exe: {self.winws_exe}", "INFO")
        log(f"Working directory: {self.work_dir}", "DEBUG")
        log(f"Lists folder: {self.lists_dir}", "DEBUG")
        log(f"Bin folder: {self.bin_dir}", "DEBUG")

    @abstractmethod
    def start_strategy_custom(self, custom_args: List[str], strategy_name: str = "custom", _retry_count: int = 0) -> bool:
        """
        Start strategy with custom arguments.
        Must be implemented by subclasses.

        Args:
            custom_args: List of command line arguments
            strategy_name: Strategy name for logs
            _retry_count: Internal retry counter (don't pass externally)

        Returns:
            True if strategy started successfully
        """
        pass

    @abstractmethod
    def get_preset_filename(self) -> str:
        """Returns the preset filename for this runner type (e.g., preset-zapret1.txt)"""
        pass

    def start_from_preset_file(self, preset_path: str, strategy_name: str = "Preset") -> bool:
        """
        Starts strategy directly from existing preset file.

        This is the preferred method for launching DPI in the new architecture
        where preset files are managed by PresetManager instead of registry.

        Default implementation reads the file and calls start_strategy_custom.
        Subclasses (like StrategyRunnerV2) may override for more efficient handling.

        Args:
            preset_path: Path to preset file (e.g., preset-zapret2.txt)
            strategy_name: Strategy name for logs

        Returns:
            True if strategy started successfully
        """
        if not os.path.exists(preset_path):
            log(f"Preset file not found: {preset_path}", "ERROR")
            return False

        try:
            # Read preset file and parse arguments
            with open(preset_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            args = []
            for line in lines:
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue
                args.append(line)

            if not args:
                log(f"Preset file is empty or has no valid arguments: {preset_path}", "ERROR")
                return False

            log(f"Starting from preset file: {preset_path} ({len(args)} args)", "INFO")
            return self.start_strategy_custom(args, strategy_name)

        except Exception as e:
            log(f"Error reading preset file: {e}", "ERROR")
            return False

    def _write_preset_file(self, args: List[str], strategy_name: str) -> str:
        """
        Writes arguments to preset file for loading via @file.

        Args:
            args: List of command line arguments
            strategy_name: Strategy name for comment

        Returns:
            Path to created file
        """
        preset_filename = self.get_preset_filename()
        preset_path = os.path.join(self.work_dir, preset_filename)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Convert paths to relative for readability
        relative_args = self._make_paths_relative(args)

        with open(preset_path, 'w', encoding='utf-8') as f:
            f.write(f"# Strategy: {strategy_name}\n")
            f.write(f"# Generated: {timestamp}\n")

            first_filter_found = False

            for arg in relative_args:
                if not first_filter_found and (arg.startswith('--filter-tcp') or arg.startswith('--filter-udp')):
                    f.write("\n")
                    first_filter_found = True

                f.write(f"{arg}\n")

                if arg == '--new':
                    f.write("\n")

        return preset_path

    # Prefixes whose paths are relative to lists_dir (not work_dir)
    _LISTS_PREFIXES = frozenset([
        "--hostlist", "--hostlist-exclude", "--hostlist-domains",
        "--ipset", "--ipset-exclude",
    ])
    # Prefixes that always point to files under lists/
    _LISTS_FILE_PREFIXES = frozenset([
        "--hostlist", "--hostlist-exclude",
        "--ipset", "--ipset-exclude",
    ])
    # Prefixes whose paths are relative to bin_dir
    _BIN_PREFIXES = frozenset([
        "--dpi-desync-fake-tls", "--dpi-desync-fake-syndata",
        "--dpi-desync-fake-quic", "--dpi-desync-fake-unknown-udp",
        "--dpi-desync-fake-unknown", "--dpi-desync-fake-http",
        "--dpi-desync-split-seqovl-pattern", "--dpi-desync-fakedsplit-pattern",
        "--dpi-desync-fake-discord", "--dpi-desync-fake-stun",
        "--dpi-desync-fake-dht", "--dpi-desync-fake-wireguard",
        "--dpi-desync-fake-tls-mod",
    ])

    def _make_paths_relative(self, args: List[str]) -> List[str]:
        """
        Converts absolute paths to relative for config readability.

        IMPORTANT: paths are made relative to their *source* directory
        (lists_dir for hostlist/ipset, bin_dir for fake-* files).

        For list-file options we keep explicit "lists/..." in preset values,
        because winws/winws2 resolves @preset lines relative to work_dir.
        """
        result = []
        lists_dir_normalized = os.path.normpath(self.lists_dir).lower()
        bin_dir_normalized = os.path.normpath(self.bin_dir).lower()
        work_dir_normalized = os.path.normpath(self.work_dir).lower()

        for arg in args:
            if '=' not in arg:
                result.append(arg)
                continue

            prefix, value = arg.split('=', 1)

            value_clean = value.strip('"').strip("'")

            # Check special format --blob=name:@path or --blob=name:+offset@path
            if ':' in value_clean and prefix == '--blob':
                colon_idx = value_clean.index(':')
                blob_name = value_clean[:colon_idx]
                blob_value = value_clean[colon_idx + 1:]

                offset_prefix = ""
                if blob_value.startswith('+'):
                    at_idx = blob_value.find('@')
                    if at_idx > 0:
                        offset_prefix = blob_value[:at_idx]
                        blob_value = blob_value[at_idx:]

                if blob_value.startswith('@'):
                    path = blob_value[1:]
                    path_normalized = os.path.normpath(path).lower()
                    if path_normalized.startswith(work_dir_normalized):
                        rel_path = os.path.relpath(path, self.work_dir).replace('\\', '/')
                        result.append(f'{prefix}={blob_name}:{offset_prefix}@{rel_path}')
                    else:
                        result.append(arg)
                else:
                    result.append(arg)
                continue

            has_at_prefix = value_clean.startswith('@')
            path_value = value_clean[1:] if has_at_prefix else value_clean

            path_normalized = os.path.normpath(path_value).lower()

            # Pick the right base directory for relpath
            if prefix in self._LISTS_PREFIXES and path_normalized.startswith(lists_dir_normalized):
                base_dir = self.lists_dir
            elif prefix in self._BIN_PREFIXES and path_normalized.startswith(bin_dir_normalized):
                base_dir = self.bin_dir
            elif path_normalized.startswith(work_dir_normalized):
                base_dir = self.work_dir
            else:
                result.append(arg)
                continue

            rel_path = os.path.relpath(path_value, base_dir).replace('\\', '/')

            # Keep list paths explicit for @preset launches from work_dir:
            # --hostlist=lists/file.txt (not bare --hostlist=file.txt).
            if prefix in self._LISTS_FILE_PREFIXES and rel_path:
                if not rel_path.lower().startswith("lists/"):
                    rel_path = f"lists/{rel_path.lstrip('/')}"

            if has_at_prefix:
                result.append(f'{prefix}=@{rel_path}')
            else:
                result.append(f'{prefix}={rel_path}')

        return result

    def _create_startup_info(self):
        """Creates STARTUPINFO for hidden process launch"""
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags = STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = SW_HIDE
        return startupinfo

    def _resolve_file_paths(self, args: List[str]) -> List[str]:
        """Resolves relative file paths"""
        from config import WINDIVERT_FILTER
        return resolve_args_paths(args, self.lists_dir, self.bin_dir, WINDIVERT_FILTER)

    def _fast_cleanup_services(self):
        """Fast service cleanup via Win API (for normal startup)"""
        try:
            cleanup_windivert_services()
        except Exception as e:
            log(f"Fast cleanup error: {e}", "DEBUG")

    def _force_cleanup_multiple_services(self, service_names: List[str], retry_count: int = 3):
        """Force cleanup multiple services"""
        for service_name in service_names:
            try:
                stop_and_delete_service(service_name, retry_count=retry_count)
            except Exception as e:
                log(f"Error cleaning up service {service_name}: {e}", "DEBUG")

    def _is_windivert_conflict_error(self, stderr: str, exit_code: int) -> bool:
        """Checks if error is a retryable WinDivert conflict (GUID/LUID collision).

        This does NOT include system-level errors like service disabled (1058),
        driver blocked (1275), or Secure Boot (577) — those are not fixable
        by cleanup/retry.
        """
        # Exit code 9 = ERROR_INVALID_BLOCK — stale WinDivert state
        if exit_code == 9:
            return True

        stderr_lower = (stderr or "").lower()
        conflict_signatures = [
            "guid or luid already exists",
            "object with that guid",
        ]
        return any(sig in stderr_lower for sig in conflict_signatures)

    def _is_windivert_system_error(self, stderr: str, exit_code: int) -> bool:
        """Checks if error is a non-retryable WinDivert system error.

        These errors require user action (Secure Boot, AV, adapter, etc.)
        and should NOT be retried.
        """
        non_retryable_codes = {577, 1058, 1060, 1068, 1275, 654}
        if exit_code in non_retryable_codes:
            return True

        stderr_lower = (stderr or "").lower()
        system_signatures = [
            "the service cannot be started",
            "service is disabled",
            "invalid image hash",
            "driver blocked",
            "disable secure boot",
            "driver failed prior unload",
        ]
        return any(sig in stderr_lower for sig in system_signatures)

    def _aggressive_windivert_cleanup(self):
        """Aggressive WinDivert cleanup via Win API - for cases when normal cleanup doesn't help"""
        log("Performing aggressive WinDivert cleanup via Win API...", "INFO")

        # 1. Kill ALL processes that may hold handles
        self._kill_all_winws_processes()
        time.sleep(0.3)

        # 2. Unload drivers via fltmc (before deleting services!)
        drivers = ["WinDivert", "WinDivert14", "WinDivert64", "Monkey"]
        for driver in drivers:
            try:
                unload_driver(driver)
            except:
                pass

        time.sleep(0.2)

        # 3. Stop and delete services via Win API
        services = ["WinDivert", "WinDivert14", "WinDivert64", "windivert", "Monkey"]
        for service in services:
            try:
                stop_and_delete_service(service, retry_count=3)
            except:
                pass

        time.sleep(0.3)

        # 4. Final process cleanup
        self._kill_all_winws_processes()

        log("Aggressive cleanup completed", "INFO")

    def stop(self) -> bool:
        """Stops running process"""
        try:
            success = True

            if self.running_process and self.is_running():
                pid = self.running_process.pid
                strategy_name = self.current_strategy_name or "unknown"

                log(f"Stopping strategy '{strategy_name}' (PID: {pid})", "INFO")

                # Soft stop
                self.running_process.terminate()

                try:
                    self.running_process.wait(timeout=5)
                    log(f"Process stopped (PID: {pid})", "SUCCESS")
                except subprocess.TimeoutExpired:
                    log("Soft stop failed, using force kill", "WARNING")
                    self.running_process.kill()
                    self.running_process.wait()
                    log(f"Process forcefully terminated (PID: {pid})", "SUCCESS")
            else:
                log("No running process to stop", "INFO")

            # Additional cleanup
            self._stop_windivert_service()
            self._stop_monkey_service()
            self._kill_all_winws_processes()

            # Clear state
            self.running_process = None
            self.current_strategy_name = None
            self.current_strategy_args = None

            return success

        except Exception as e:
            log(f"Error stopping process: {e}", "ERROR")
            return False

    def _stop_windivert_service(self):
        """Stops and deletes WinDivert service via Win API"""
        for service_name in ["WinDivert", "windivert", "WinDivert14", "WinDivert64"]:
            stop_and_delete_service(service_name, retry_count=3)

    def _stop_monkey_service(self):
        """Stops and deletes Monkey service via Win API"""
        stop_and_delete_service("Monkey", retry_count=3)

    def _force_delete_service(self, service_name: str):
        """Force delete a service"""
        try:
            stop_and_delete_service(service_name, retry_count=5)
        except Exception as e:
            log(f"Force delete service {service_name} error: {e}", "DEBUG")

    def _kill_all_winws_processes(self):
        """Forcefully terminates all winws.exe and winws2.exe processes via Win API"""
        try:
            kill_winws_force()
        except Exception as e:
            log(f"Error killing winws processes: {e}", "DEBUG")

    def is_running(self) -> bool:
        """Checks if process is running"""
        if not self.running_process:
            return False

        poll_result = self.running_process.poll()
        is_running = poll_result is None

        if not is_running and self.current_strategy_name:
            log(f"Strategy process exited (code: {poll_result})", "WARNING")

        return is_running

    def get_current_strategy_info(self) -> Dict:
        """Returns information about current running strategy"""
        if not self.is_running():
            return {}

        return {
            'name': self.current_strategy_name,
            'pid': self.running_process.pid if self.running_process else None,
            'args_count': len(self.current_strategy_args) if self.current_strategy_args else 0
        }

    def get_process(self) -> Optional[subprocess.Popen]:
        """Returns current running process for output reading"""
        if self.is_running():
            return self.running_process
        return None
