"""
updater/update.py
────────────────────────────────────────────────────────────────
ОПТИМИЗИРОВАННАЯ ВЕРСИЯ ДЛЯ БЫСТРОГО СКАЧИВАНИЯ
"""
from __future__ import annotations

import os, sys, tempfile, subprocess, shutil, time, requests
import threading
import ctypes
from typing import Callable, Optional
from time import sleep

from PyQt6.QtCore    import QObject, QThread, pyqtSignal, QTimer
from packaging import version
from utils import run_hidden, get_system_exe

from .release_manager import get_latest_release
from .github_release import normalize_version
from config import CHANNEL, APP_VERSION
from log import log
from .rate_limiter import UpdateRateLimiter
from .network_hints import maybe_log_disable_dpi_for_update


TIMEOUT = 15  # Увеличен с 10 до 15 сек для медленных соединений

# Автопереключение на другой источник, если текущий сервер слишком медленный.
# Порог достаточно консервативный, чтобы не ломать нормальные медленные сети,
# но уходить с явно «зажатых» зеркал.
SLOW_MIRROR_THRESHOLD_MBPS = 0.35
SLOW_MIRROR_GRACE_SECONDS = 15.0
SLOW_MIRROR_WINDOW_SECONDS = 4.0
SLOW_MIRROR_MAX_SECONDS = 18.0
SLOW_MIRROR_MIN_BYTES = 8 * 1024 * 1024

# ──────────────────────────── Запуск установщика с UAC ─────────────────────────
# ВАЖНО ДЛЯ БУДУЩИХ РАЗРАБОТЧИКОВ:
# НЕ ИСПОЛЬЗОВАТЬ ctypes.windll.shell32.ShellExecuteW с "runas"!
# Причина: ShellExecuteW асинхронный - возвращает успех (HINSTANCE>32) сразу,
# но установщик фактически не запускается (причина до конца не ясна,
# возможно связано с тем что приложение закрывается через os._exit()).
#
# РЕШЕНИЕ: PowerShell Start-Process -Verb RunAs
# Работает стабильно. Если приложение уже запущено с правами админа
# (а Zapret требует админ для WinDivert), UAC не появляется.
# Проверено 25.12.2025.


def launch_installer_winapi(exe_path: str, arguments: str, working_dir: str = None) -> bool:
    """
    Запускает установщик с правами администратора через PowerShell Start-Process.

    ВНИМАНИЕ: Не заменять на ShellExecuteW! См. комментарий выше.

    Args:
        exe_path: Путь к установщику (.exe)
        arguments: Аргументы командной строки (разделённые пробелами)
        working_dir: Рабочая директория (не используется, оставлен для совместимости)

    Returns:
        True если процесс успешно запущен
    """
    # Проверяем существование файла
    if not os.path.exists(exe_path):
        log(f"❌ Файл установщика не найден: {exe_path}", "🔁❌ ERROR")
        return False

    file_size = os.path.getsize(exe_path)
    log(f"📦 Размер установщика: {file_size / 1024 / 1024:.1f} MB", "🔁 UPDATE")

    log(f"🚀 Запуск через PowerShell (RunAs): {exe_path}", "🔁 UPDATE")
    log(f"   Параметры: {arguments}", "🔁 UPDATE")

    try:
        # Разбиваем аргументы на список для PowerShell
        args_list = arguments.split()
        # Формируем строку аргументов для PowerShell: '/arg1','/arg2',...
        ps_args = ",".join(f"'{arg}'" for arg in args_list)

        # PowerShell команда для запуска с правами админа
        ps_command = f"Start-Process -FilePath '{exe_path}' -ArgumentList {ps_args} -Verb RunAs"

        log(f"   PowerShell: {ps_command}", "🔁 UPDATE")

        # Запускаем PowerShell с командой
        process = subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", ps_command],
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # Даём время на появление UAC (не ждём завершения установщика!)
        time.sleep(0.5)

        # Проверяем, не завершился ли PowerShell с ошибкой
        retcode = process.poll()
        if retcode is not None and retcode != 0:
            stderr = process.stderr.read().decode('utf-8', errors='ignore')
            log(f"❌ PowerShell ошибка (код {retcode}): {stderr}", "🔁❌ ERROR")
            return False

        log(f"✅ Установщик запущен успешно", "🔁 UPDATE")
        return True

    except Exception as e:
        log(f"❌ Ошибка запуска: {e}", "🔁❌ ERROR")
        return False


# ──────────────────────────── вспомогательные утилиты ─────────────────────
def _safe_set_status(parent, msg: str):
    """Пишем в status-label, если она есть; иначе в консоль."""
    if parent and hasattr(parent, "set_status"):
        parent.set_status(msg)
    else:
        print(msg)

def _download_with_retry(url: str, dest: str, on_progress: Callable[[int, int], None] | None,
                         verify_ssl: bool = True, max_retries: int = 2,
                         enable_slow_mirror_switch: bool = True):
    """
    ОПТИМИЗИРОВАННОЕ скачивание с защитой от повторных загрузок
    """
    import requests
    from time import sleep, time
    import os
    
    # ═══════════════════════════════════════════════════════════
    # ✅ ЗАЩИТА ОТ ПОВТОРНОГО СКАЧИВАНИЯ (в течение 30 секунд)
    # ═══════════════════════════════════════════════════════════
    if os.path.exists(dest):
        file_age = time() - os.path.getmtime(dest)
        file_size = os.path.getsize(dest)
        
        # Если файл скачан недавно И имеет правильный размер (>60MB)
        if file_age < 30 and file_size > 60000000:
            log(
                f"⏭️ Файл уже скачан {int(file_age)}с назад "
                f"({file_size/1024/1024:.1f}MB), повторное скачивание пропущено",
                "🔄 DOWNLOAD"
            )
            return  # НЕ СКАЧИВАЕМ ПОВТОРНО!
    
    last_error = None
    effective_retries = max_retries
    attempt = 0
    
    while attempt < effective_retries:
        try:
            session = requests.Session()
            session.trust_env = False
            session.proxies = {"http": None, "https": None}
            
            session.headers.update({
                'User-Agent': 'Zapret-Updater/3.1',  # ✅ Обновлена версия
                'Accept': 'application/octet-stream',
                'Accept-Encoding': 'identity',
                'Connection': 'keep-alive'
            })
            
            # ✅ УМЕНЬШЕН пул соединений
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=2,
                pool_maxsize=2,
                max_retries=requests.adapters.Retry(
                    total=0,
                    backoff_factor=0,
                    status_forcelist=None
                )
            )
            session.mount('https://', adapter)
            session.mount('http://', adapter)
            
            if not verify_ssl:
                session.verify = False
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            log(f"Попытка {attempt + 1}/{max_retries} скачивания", "🔄 DOWNLOAD")
            
            chunk_size = 65536  # 64KB — при 15 КБ/с callback каждые ~4с, не 133с
            timeout = (10, 90)
            
            # ✅ Resume для любой попытки, если уже есть значимый partial-файл.
            # Это позволяет переключаться на более быстрые зеркала без потери прогресса.
            resume_from = 0
            if os.path.exists(dest):
                resume_from = os.path.getsize(dest)
                if resume_from > 1048576:  # > 1MB
                    log(f"📥 Возобновление с {resume_from/1024/1024:.1f} МБ", "🔄 DOWNLOAD")
                    session.headers['Range'] = f'bytes={resume_from}-'
                    # При resume уже скачано достаточно — снижаем порог slow mirror
                    # чтобы быстрее переключиться если и этот сервер медленный
                    if resume_from >= SLOW_MIRROR_MIN_BYTES:
                        log(f"⚡ Resume >= {SLOW_MIRROR_MIN_BYTES/1024/1024:.0f} МБ — порог slow mirror снижен до 1 МБ", "🔄 DOWNLOAD")
                else:
                    resume_from = 0
            
            with session.get(url, stream=True, timeout=timeout, verify=verify_ssl) as resp:
                resp.raise_for_status()
                
                if resp.status_code == 206:
                    content_range = resp.headers.get('Content-Range', '')
                    if content_range:
                        total = int(content_range.split('/')[-1])
                    else:
                        total = resume_from + int(resp.headers.get("content-length", 0))
                else:
                    total = int(resp.headers.get("content-length", 0))
                    resume_from = 0
                
                done = resume_from
                
                if total > 0:
                    log(f"📦 Размер: {total/(1024*1024):.1f} MB", "🔄 DOWNLOAD")
                
                last_update_time = 0
                update_interval = 2.0
                
                mode = "ab" if resume_from > 0 else "wb"
                
                with open(dest, mode, buffering=4194304) as fp:
                    start_time = time()
                    slow_window_started = start_time
                    slow_window_bytes = 0
                    slow_seconds_accum = 0.0
                    last_slow_log_time = 0.0
                    # При resume снижаем порог — уже достаточно данных для оценки
                    effective_min_bytes = (1 * 1024 * 1024) if (resume_from >= SLOW_MIRROR_MIN_BYTES) else SLOW_MIRROR_MIN_BYTES
                    
                    try:
                        for chunk in resp.iter_content(chunk_size=chunk_size):
                            if chunk:
                                fp.write(chunk)
                                done += len(chunk)
                                slow_window_bytes += len(chunk)
                                
                                current_time = time()
                                if on_progress and total:
                                    if (current_time - last_update_time) >= update_interval:
                                        on_progress(done, total)
                                        last_update_time = current_time

                                if enable_slow_mirror_switch:
                                    window_elapsed = current_time - slow_window_started
                                    if window_elapsed >= SLOW_MIRROR_WINDOW_SECONDS:
                                        window_speed_bps = slow_window_bytes / max(window_elapsed, 1e-6)
                                        downloaded_now = done - resume_from
                                        remaining = (total - done) if total > 0 else None
                                        too_slow = window_speed_bps < (SLOW_MIRROR_THRESHOLD_MBPS * 1024 * 1024)
                                        enough_data = downloaded_now >= effective_min_bytes
                                        after_grace = (current_time - start_time) >= SLOW_MIRROR_GRACE_SECONDS
                                        not_finishing = (remaining is None) or (remaining > (8 * 1024 * 1024))

                                        if too_slow and enough_data and after_grace and not_finishing:
                                            slow_seconds_accum += window_elapsed
                                            if (current_time - last_slow_log_time) >= 6.0:
                                                log(
                                                    f"🐢 Низкая скорость {window_speed_bps / 1024 / 1024:.2f} MB/s, "
                                                    f"возможен переход на другое зеркало",
                                                    "🔄 DOWNLOAD",
                                                )
                                                last_slow_log_time = current_time
                                        else:
                                            slow_seconds_accum = 0.0

                                        if slow_seconds_accum >= SLOW_MIRROR_MAX_SECONDS:
                                            raise requests.exceptions.ConnectionError(
                                                "Slow download: mirror is too slow, switching source"
                                            )

                                        slow_window_started = current_time
                                        slow_window_bytes = 0
                        
                        if on_progress and total:
                            on_progress(total, total)
                        
                        elapsed = time() - start_time
                        if elapsed > 0 and total > 0:
                            avg_speed = ((done - resume_from) / elapsed) / (1024 * 1024)
                            log(f"✅ Скачано {total/(1024*1024):.1f} MB за {elapsed:.1f}с ({avg_speed:.2f} MB/s)", "🔄 DOWNLOAD")
                        
                    except requests.exceptions.ChunkedEncodingError as e:
                        raise requests.exceptions.ConnectionError(f"Incomplete download: {e}")
            
            # ✅ Проверяем размер файла
            if os.path.exists(dest):
                actual_size = os.path.getsize(dest)
                if total > 0 and actual_size != total:
                    raise Exception(f"Размер не совпадает: {actual_size} != {total}")
                
                # ✅ Устанавливаем время модификации файла для защиты
                os.utime(dest, None)  # Обновляем mtime
            
            log(f"✅ Файл скачан с попытки {attempt + 1}", "🔄 DOWNLOAD")
            return
            
        except Exception as e:
            last_error = str(e)
            log(f"❌ Попытка {attempt + 1} не удалась: {last_error}", "🔄 DOWNLOAD")
            maybe_log_disable_dpi_for_update(e, scope="download", level="🔄 DOWNLOAD")
        
        # Удаляем файл если ошибка не resume-able.
        # Для медленного зеркала partial сохраняем, чтобы следующий источник
        # продолжил скачивание через Range.
        keep_partial = False
        try:
            err_text = str(last_error)
            keep_partial = ("Incomplete download" in err_text) or ("Slow download" in err_text)
        except Exception:
            keep_partial = False

        if os.path.exists(dest) and not keep_partial:
            try:
                os.remove(dest)
            except:
                pass
        
        attempt += 1
        
        if attempt < effective_retries:
            wait_time = min(2 ** attempt, 30)
            log(f"⏳ Ожидание {wait_time}с перед повтором...", "🔄 DOWNLOAD")
            sleep(wait_time)
    
    raise Exception(f"Не удалось скачать после {max_retries} попыток. Ошибка: {last_error}")

def compare_versions(v1: str, v2: str) -> int:
    """Сравнивает две версии"""
    from packaging import version
    
    try:
        v1_norm = normalize_version(v1)
        v2_norm = normalize_version(v2)
        
        ver1 = version.parse(v1_norm)
        ver2 = version.parse(v2_norm)
        
        if ver1 < ver2:
            return -1
        elif ver1 > ver2:
            return 1
        else:
            return 0
            
    except Exception as e:
        log(f"Error comparing versions '{v1}' and '{v2}': {e}", "🔁❌ ERROR")
        return -1 if v1 < v2 else (1 if v1 > v2 else 0)

# ──────────────────────────── фоновой воркер ──────────────────────────────
class UpdateWorker(QObject):
    progress = pyqtSignal(str)
    progress_value = pyqtSignal(int)
    progress_bytes = pyqtSignal(int, int, int)
    finished = pyqtSignal(bool)
    ask_user = pyqtSignal(str, str, bool)
    show_no_updates = pyqtSignal(str)
    download_complete = pyqtSignal()
    download_failed = pyqtSignal(str)

    def __init__(self, parent=None, silent: bool = False, skip_rate_limit: bool = False):
        super().__init__()
        self._parent = parent
        self._silent = silent
        self._skip_rate_limit = skip_rate_limit
        self._should_continue = True
        self._user_response = None
        self._response_event = threading.Event()

    def set_user_response(self, response: bool):
        log(f"UpdateWorker: получен ответ: {response}", "🔁 UPDATE")
        self._user_response = response
        self._response_event.set()

    def _emit(self, msg: str):
        self.progress.emit(msg)

    def _emit_progress(self, percent: int):
        self.progress_value.emit(percent)
    
    def _ask_user_dialog(self, new_ver: str, notes: str, is_pre: bool):
        if self._silent:
            log("UpdateWorker: тихий режим - автоустановка", "🔁 UPDATE")
            self._user_response = True
            return True
        
        self._user_response = None
        self._response_event.clear()
        
        log(f"UpdateWorker: запрос разрешения для v{new_ver}", "🔁 UPDATE")
        self.ask_user.emit(new_ver, notes, is_pre)
        
        if self._response_event.wait(timeout=60):
            log(f"UpdateWorker: ответ получен: {self._user_response}", "🔁 UPDATE")
            return self._user_response
        else:
            log("UpdateWorker: таймаут ожидания ответа", "🔁 UPDATE")
            return False
    
    def _get_download_urls(self, release_info: dict) -> list:
        """Формирует список URL: GitHub CDN первый, VPS как fallback"""
        urls = []
        upd_url = release_info["update_url"]
        verify_ssl = release_info.get("verify_ssl", True)

        # Извлекаем имя файла
        filename = (release_info.get("file_name") or "").strip()
        if not filename and not upd_url.startswith("telegram://"):
            filename = upd_url.split('/')[-1]
        if not filename:
            filename = "Zapret2Setup.exe"

        # 1. Основной URL (GitHub CDN если источник — GitHub)
        if not upd_url.startswith("telegram://"):
            urls.append((upd_url, verify_ssl))

        # 2. Если источник не GitHub — добавить GitHub как приоритетный fallback
        if "github.com" not in upd_url:
            try:
                from .github_release import get_latest_release as github_get_latest
                gh_release = github_get_latest(CHANNEL)
                if gh_release and gh_release.get("update_url"):
                    urls.append((gh_release["update_url"], True))
            except Exception:
                pass

        # 3. VPS серверы как финальный fallback
        try:
            from .server_config import VPS_SERVERS, should_verify_ssl

            for server in VPS_SERVERS:
                https_url = f"https://{server['host']}:{server['https_port']}/download/{filename}"
                if https_url != upd_url:
                    urls.append((https_url, should_verify_ssl()))

            for server in VPS_SERVERS:
                http_url = f"http://{server['host']}:{server['http_port']}/download/{filename}"
                if http_url != upd_url:
                    urls.append((http_url, False))

        except Exception as e:
            log(f"Не удалось добавить VPS fallback: {e}", "🔁 UPDATE")

        log(f"Сформировано {len(urls)} URL для скачивания", "🔁 UPDATE")
        return urls
    
    def _run_installer(self, setup_exe: str, version: str, tmp_dir: str) -> bool:
        """
        Запускает установщик через ShellExecuteW с правами администратора.
        """
        try:
            self._emit("Запуск установщика…")

            # Копируем установщик в постоянную папку (чтобы temp не удалился)
            persistent_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ZapretUpdate")
            os.makedirs(persistent_dir, exist_ok=True)

            persistent_exe = os.path.join(persistent_dir, "Zapret2Setup.exe")

            # Удаляем старый файл
            if os.path.exists(persistent_exe):
                try:
                    os.remove(persistent_exe)
                except:
                    pass

            # Копируем установщик
            shutil.copy2(setup_exe, persistent_exe)
            file_size = os.path.getsize(persistent_exe)
            log(f"📁 Установщик скопирован: {persistent_exe} ({file_size / 1024 / 1024:.1f} MB)", "🔁 UPDATE")

            # Путь установки
            install_dir = os.path.dirname(sys.executable)

            # Аргументы для тихой установки.
            # Важно: при автообновлении всегда отключаем задачу installzaphub,
            # чтобы ZapretHub не устанавливался поверх другой версии.
            base_args = (
                '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOCANCEL '
                '/CLOSEAPPLICATIONS /RESTARTAPPLICATIONS /MERGETASKS=!installzaphub'
            )

            # Примечание: если путь содержит пробелы, нужно экранировать кавычки
            if ' ' in install_dir:
                arguments = f'{base_args} /DIR="{install_dir}"'
            else:
                arguments = f'{base_args} /DIR={install_dir}'

            # Запускаем установщик через WinAPI с правами администратора
            success = launch_installer_winapi(persistent_exe, arguments, persistent_dir)

            if not success:
                self._emit("Не удалось запустить установщик")
                log("❌ launch_installer_winapi вернул False", "🔁❌ ERROR")
                shutil.rmtree(tmp_dir, True)
                return False

            # Очищаем temp
            shutil.rmtree(tmp_dir, True)

            log("⏳ Закрытие через 5с (дождитесь UAC)...", "🔁 UPDATE")
            QTimer.singleShot(5000, lambda: os._exit(0))

            return True

        except Exception as e:
            self._emit(f"Ошибка запуска: {e}")
            log(f"❌ Ошибка запуска установщика: {e}", "🔁❌ ERROR")
            import traceback
            log(traceback.format_exc(), "🔁❌ ERROR")
            shutil.rmtree(tmp_dir, True)
            return False
    
    def _download_update(self, release_info: dict, is_retry: bool = False) -> bool:
        new_ver = release_info["version"]
        log(f"UpdateWorker: загрузка v{new_ver} (retry={is_retry})", "🔁 UPDATE")

        tmp_dir = tempfile.mkdtemp(prefix="zapret_upd_")
        setup_exe = os.path.join(tmp_dir, "Zapret2Setup.exe")
        
        def _prog(done, total):
            percent = done * 100 // total if total > 0 else 0
            self.progress_bytes.emit(percent, done, total)
            self._emit(f"Скачивание… {percent}%")
        
        download_urls = self._get_download_urls(release_info)
        
        download_error = None
        for idx, (url, verify_ssl) in enumerate(download_urls):
            if url.startswith("telegram://"):
                continue

            try:
                log(f"Попытка #{idx+1} с {url} (SSL={verify_ssl})", "🔁 UPDATE")
                
                # Для тихих автообновлений не долбим сервер — максимум 1 попытка,
                # для ручного режима можно 2.
                retries = 1 if self._silent else 2
                
                _download_with_retry(
                    url,
                    setup_exe,
                    _prog,
                    verify_ssl=verify_ssl,
                    max_retries=retries,
                    enable_slow_mirror_switch=(idx < len(download_urls) - 1),
                )
                
                download_error = None
                self.download_complete.emit()
                break
                
            except Exception as e:
                download_error = e
                log(f"❌ Ошибка: {e}", "🔁❌ ERROR")
                
                if idx < len(download_urls) - 1:
                    self._emit("Пробуем альтернативный источник...")
                    time.sleep(1)
        
        if download_error:
            error_msg = str(download_error)
            if "ConnectionPool" in error_msg or "Connection" in error_msg:
                error_msg = "Ошибка подключения. Проверьте интернет."

            self.download_failed.emit(error_msg)
            self._emit(f"Ошибка: {error_msg}")
            shutil.rmtree(tmp_dir, True)
            return False

        if not os.path.exists(setup_exe):
            error_msg = "Нет доступных источников для скачивания обновления"
            log(f"❌ {error_msg}", "🔁❌ ERROR")
            self.download_failed.emit(error_msg)
            self._emit(f"Ошибка: {error_msg}")
            shutil.rmtree(tmp_dir, True)
            return False

        # Запуск установщика
        log(f"📦 Скачивание завершено, запускаем установщик: {setup_exe}", "🔁 UPDATE")
        log(f"   Файл существует: {os.path.exists(setup_exe)}", "🔁 UPDATE")
        if os.path.exists(setup_exe):
            log(f"   Размер: {os.path.getsize(setup_exe)} байт", "🔁 UPDATE")
        return self._run_installer(setup_exe, new_ver, tmp_dir)

    def run(self):
        try:
            ok = self._check_and_run_update()
            self.finished.emit(ok)
        except Exception as e:
            log(f"UpdateWorker error: {e}", "🔁❌ ERROR")
            self._emit(f"Ошибка: {e}")
            self.finished.emit(False)

    def _check_and_run_update(self) -> bool:
        self._emit("Проверка обновлений…")
        
        # ═══════════════════════════════════════════════════════════════
        # ✅ ПРОВЕРКА RATE LIMIT (пропускается если skip_rate_limit=True)
        # ═══════════════════════════════════════════════════════════════
        if not self._skip_rate_limit:
            is_auto = self._silent
            can_check, error_msg = UpdateRateLimiter.can_check_update(is_auto=is_auto)
            
            if not can_check:
                self._emit(error_msg)
                log(f"⏱️ Проверка заблокирована rate limiter: {error_msg}", "🔁 UPDATE")
                
                # Для ручных проверок показываем сообщение (кроме dev/test версий)
                if not self._silent and CHANNEL not in ('dev', 'test'):
                    self.show_no_updates.emit(f"Rate limit: {error_msg}")
                
                return False
            
            # Записываем факт проверки
            UpdateRateLimiter.record_check(is_auto=is_auto)
        else:
            log("⏭️ Rate limiter пропущен (ручная установка)", "🔁 UPDATE")
        
        # ✅ АВТООБНОВЛЕНИЯ ИСПОЛЬЗУЮТ КЭШ, РУЧНЫЕ - НЕТ
        use_cache = self._silent  # silent=True для автопроверок
        
        if not use_cache:
            log("🔄 Принудительная проверка обновлений (кэш игнорируется)", "🔁 UPDATE")
        
        release_info = get_latest_release(CHANNEL, use_cache=use_cache)
        
        if not release_info:
            self._emit("Не удалось проверить обновления.")
            return False

        new_ver = release_info["version"]
        notes   = release_info["release_notes"]
        is_pre  = release_info["prerelease"]
        
        try:
            app_ver_norm = normalize_version(APP_VERSION)
        except ValueError:
            log(f"Invalid APP_VERSION: {APP_VERSION}", "🔁❌ ERROR")
            self._emit("Ошибка версии.")
            return False
        
        log(f"Update check: {CHANNEL}, local={app_ver_norm}, remote={new_ver}, use_cache={use_cache}", "🔁 UPDATE")

        cmp_result = compare_versions(app_ver_norm, new_ver)

        if cmp_result >= 0:
            self._emit(f"✅ Обновлений нет (v{app_ver_norm})")
            if not self._silent:
                self.show_no_updates.emit(app_ver_norm)
            return False

        user_confirmed = self._ask_user_dialog(new_ver, notes, is_pre)
        
        if not user_confirmed:
            self._emit("Обновление отменено")
            return False

        return self._download_update(release_info)

# ──────────────────────────── public-API ──────────────────────────────────
# ПРИМЕЧАНИЕ: Автообновление при запуске ОТКЛЮЧЕНО.
# Обновления проверяются и устанавливаются только через вкладку "Серверы" (ui/pages/servers_page.py)
# Функция run_update_async оставлена для обратной совместимости, но не используется.
