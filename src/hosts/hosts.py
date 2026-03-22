import ctypes
import stat
import os
import subprocess
from pathlib import Path
from .proxy_domains import (
    get_all_services,
    get_dns_profiles,
    get_service_domain_ip_rows,
    get_service_domain_ip_map,
    get_service_domain_names,
    get_service_domains,
)
from .adobe_domains import ADOBE_DOMAINS
from log import log

def _get_hosts_path_from_env() -> Path:
    """
    Возвращает путь к hosts через переменные окружения, чтобы корректно работать
    когда Windows установлена не на C:.
    """
    sys_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
    if sys_root:
        return Path(sys_root, "System32", "drivers", "etc", "hosts")
    return Path(r"C:\Windows\System32\drivers\etc\hosts")


HOSTS_PATH = _get_hosts_path_from_env() if os.name == "nt" else Path(r"C:\Windows\System32\drivers\etc\hosts")

_GITHUB_API_DOMAIN = "api.github.com"
_ZAPRET_TRACKER_DOMAIN = "zapret-tracker.duckdns.org"
_ZAPRET_TRACKER_IP = "88.210.52.47"
_HOSTS_BOOTSTRAP_SIGNATURE_VERSION = "v2"


def _get_hosts_bootstrap_signature() -> str:
    return f"{_HOSTS_BOOTSTRAP_SIGNATURE_VERSION}|{_ZAPRET_TRACKER_DOMAIN}|{_ZAPRET_TRACKER_IP}"


def _extract_tracker_from_bootstrap_signature(signature: str | None) -> tuple[str | None, str | None]:
    if not isinstance(signature, str):
        return None, None
    parts = [part.strip() for part in signature.split("|")]
    if len(parts) < 3:
        return None, None
    domain = parts[1].lower()
    ip = parts[2]
    if not domain or not ip:
        return None, None
    return domain, ip


# ───────────────────────── hosts file read cache ─────────────────────────
#
# На старте приложение может несколько раз читать hosts подряд (проверки/страницы UI).
# Файл маленький, но повторные чтения + перебор кодировок/обработка PermissionError
# могут давать заметную задержку. Делаем безопасный кэш "на процесс":
# - инвалидируем по сигнатуре файла (mtime_ns + size)
# - обновляем кэш после успешной записи

_HOSTS_TEXT_CACHE: str | None = None
_HOSTS_SIG_CACHE: tuple[int, int] | None = None  # (mtime_ns, size)


def _get_hosts_sig(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
        mtime_ns = getattr(st, "st_mtime_ns", None)
        if mtime_ns is None:
            mtime_ns = int(st.st_mtime * 1_000_000_000)
        return (int(mtime_ns), int(st.st_size))
    except Exception:
        return None


def _set_hosts_cache(content: str | None, sig: tuple[int, int] | None) -> None:
    global _HOSTS_TEXT_CACHE, _HOSTS_SIG_CACHE
    _HOSTS_TEXT_CACHE = content
    _HOSTS_SIG_CACHE = sig


def invalidate_hosts_file_cache() -> None:
    """Принудительно сбрасывает кэш чтения hosts (на случай внешних изменений)."""
    _set_hosts_cache(None, None)


def _get_all_managed_domains() -> set[str]:
    domains: set[str] = set()
    for service_name in get_all_services():
        domains.update(get_service_domain_names(service_name))
    return domains


def _run_cmd(args, description):
    """Выполняет команду и логирует результат"""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if result.returncode == 0:
            log(f"✅ {description}: успешно")
            return True
        else:
            # Проверяем stderr или stdout на наличие ошибки
            error = result.stderr.strip() or result.stdout.strip()
            log(f"⚠ {description}: {error}", "⚠ WARNING")
            return False
    except Exception as e:
        log(f"❌ {description}: {e}", "❌ ERROR")
        return False


def _get_current_username():
    """Получает имя текущего пользователя"""
    try:
        import getpass
        return getpass.getuser()
    except:
        return None


def restore_hosts_permissions():
    """
    Агрессивно восстанавливает права доступа к файлу hosts.
    Использует множество методов для обхода блокировок антивирусов.

    Returns:
        tuple: (success: bool, message: str)
    """
    hosts_path = str(HOSTS_PATH)

    log("🔧 Начинаем АГРЕССИВНОЕ восстановление прав доступа к файлу hosts...")

    # Well-known SIDs (работают на любой локализации Windows)
    # S-1-5-32-544 = Administrators / Администраторы
    # S-1-5-32-545 = Users / Пользователи
    # S-1-5-18 = SYSTEM
    # S-1-1-0 = Everyone / Все
    SID_ADMINISTRATORS = "*S-1-5-32-544"
    SID_USERS = "*S-1-5-32-545"
    SID_SYSTEM = "*S-1-5-18"
    SID_EVERYONE = "*S-1-1-0"

    current_user = _get_current_username()

    try:
        # ========== ЭТАП 1: Снимаем атрибуты файла ==========
        log("Этап 1: Снимаем системные атрибуты файла...")
        _run_cmd(['attrib', '-R', '-S', '-H', hosts_path], "attrib -R -S -H")

        # ========== ЭТАП 2: Забираем владение файлом ==========
        log("Этап 2: Забираем владение файлом...")

        # Способ 1: takeown для администраторов
        _run_cmd(['takeown', '/F', hosts_path, '/A'], "takeown /A (для группы администраторов)")

        # Способ 2: takeown для текущего пользователя
        if current_user:
            _run_cmd(['takeown', '/F', hosts_path], "takeown (для текущего пользователя)")

        # ========== ЭТАП 3: Сбрасываем ACL ==========
        log("Этап 3: Сбрасываем ACL...")
        _run_cmd(['icacls', hosts_path, '/reset'], "icacls /reset")

        # ========== ЭТАП 4: Выдаём права через SID (работает на любой локализации) ==========
        log("Этап 4: Выдаём права через SID...")

        # Полный доступ для Administrators через SID
        _run_cmd(['icacls', hosts_path, '/grant', f'{SID_ADMINISTRATORS}:F'],
                 "icacls /grant Administrators (SID)")

        # Полный доступ для SYSTEM через SID
        _run_cmd(['icacls', hosts_path, '/grant', f'{SID_SYSTEM}:F'],
                 "icacls /grant SYSTEM (SID)")

        # Чтение для Users через SID
        _run_cmd(['icacls', hosts_path, '/grant', f'{SID_USERS}:R'],
                 "icacls /grant Users (SID)")

        # Полный доступ для Everyone через SID (агрессивно!)
        _run_cmd(['icacls', hosts_path, '/grant', f'{SID_EVERYONE}:F'],
                 "icacls /grant Everyone (SID)")

        # ========== ЭТАП 5: Пробуем с английскими именами (для английской Windows) ==========
        log("Этап 5: Пробуем с английскими именами групп...")
        _run_cmd(['icacls', hosts_path, '/grant', 'Administrators:F'], "icacls Administrators:F")
        _run_cmd(['icacls', hosts_path, '/grant', 'SYSTEM:F'], "icacls SYSTEM:F")
        _run_cmd(['icacls', hosts_path, '/grant', 'Users:R'], "icacls Users:R")
        _run_cmd(['icacls', hosts_path, '/grant', 'Everyone:F'], "icacls Everyone:F")

        # ========== ЭТАП 6: Пробуем с русскими именами (для русской Windows) ==========
        log("Этап 6: Пробуем с русскими именами групп...")
        _run_cmd(['icacls', hosts_path, '/grant', 'Администраторы:F'], "icacls Администраторы:F")
        _run_cmd(['icacls', hosts_path, '/grant', 'Пользователи:R'], "icacls Пользователи:R")
        _run_cmd(['icacls', hosts_path, '/grant', 'Все:F'], "icacls Все:F")

        # ========== ЭТАП 7: Права для текущего пользователя ==========
        if current_user:
            log(f"Этап 7: Выдаём права текущему пользователю ({current_user})...")
            _run_cmd(['icacls', hosts_path, '/grant', f'{current_user}:F'],
                     f"icacls /grant {current_user}:F")

        # ========== ЭТАП 8: PowerShell для обхода некоторых блокировок ==========
        log("Этап 8: Пробуем через PowerShell...")
        ps_script = f'''
$acl = Get-Acl "{hosts_path}"
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule("Everyone","FullControl","Allow")
$acl.SetAccessRule($rule)
Set-Acl "{hosts_path}" $acl
'''
        _run_cmd(['powershell', '-Command', ps_script], "PowerShell Set-Acl")

        # ========== ЭТАП 9: Наследование от родительской папки ==========
        log("Этап 9: Включаем наследование прав от родительской папки...")
        _run_cmd(['icacls', hosts_path, '/inheritance:e'], "icacls /inheritance:e")

        # ========== ЭТАП 10: Финальная проверка ==========
        log("Этап 10: Проверяем результат...")

        # Пробуем прочитать файл
        try:
            content = HOSTS_PATH.read_text(encoding='utf-8')
            log("✅ Права восстановлены! Файл hosts доступен для ЧТЕНИЯ")

            # Пробуем открыть на запись (проверка прав на запись)
            try:
                with HOSTS_PATH.open('a', encoding='utf-8-sig'):
                    pass
                log("✅ Файл hosts доступен для ЗАПИСИ")
                return True, "Права доступа к файлу hosts успешно восстановлены"
            except PermissionError:
                log("❌ Файл доступен для чтения, но НЕ для записи", "❌ ERROR")
                return False, (
                    "Файл hosts доступен для чтения, но запись запрещена.\n"
                    "Чаще всего это защита антивируса/Defender.\n"
                    "Добавьте исключение для hosts или временно отключите защиту и повторите."
                )

        except PermissionError:
            log("❌ После всех попыток файл все еще недоступен", "❌ ERROR")

            # Последняя попытка - копирование через temp
            log("Этап 11: Последняя попытка - копирование через временный файл...")
            success = _try_copy_workaround(hosts_path)
            if success:
                return True, "Права восстановлены через копирование"

            return False, "Не удалось восстановить права. Возможно, антивирус блокирует доступ. Попробуйте:\n1. Временно отключить антивирус\n2. Добавить исключение для файла hosts\n3. Запустить программу от имени администратора"

        except Exception as e:
            log(f"Ошибка при проверке: {e}", "❌ ERROR")
            return False, f"Ошибка при проверке прав: {e}"

    except FileNotFoundError as e:
        log(f"Команда не найдена: {e}", "❌ ERROR")
        return False, f"Системная команда не найдена: {e}"
    except Exception as e:
        log(f"Ошибка при восстановлении прав: {e}", "❌ ERROR")
        return False, f"Ошибка: {e}"


def _try_copy_workaround(hosts_path):
    """
    Последняя попытка - копируем hosts через временный файл.
    Иногда помогает обойти блокировку антивируса.
    """
    import tempfile
    import shutil

    try:
        # Создаём временный файл
        temp_dir = tempfile.gettempdir()
        temp_hosts = os.path.join(temp_dir, "hosts_temp_copy")

        # Копируем hosts во временный файл через cmd (обход блокировок)
        result = subprocess.run(
            ['cmd', '/c', 'copy', '/Y', hosts_path, temp_hosts],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )

        if result.returncode == 0:
            log("✅ Hosts скопирован во временный файл")

            # Удаляем оригинал
            subprocess.run(
                ['cmd', '/c', 'del', '/F', '/Q', hosts_path],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            # Копируем обратно
            result = subprocess.run(
                ['cmd', '/c', 'copy', '/Y', temp_hosts, hosts_path],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            if result.returncode == 0:
                log("✅ Hosts восстановлен из временного файла")

                # Удаляем временный файл
                try:
                    os.remove(temp_hosts)
                except:
                    pass

                # Проверяем доступ
                try:
                    HOSTS_PATH.read_text(encoding='utf-8')
                    return True
                except:
                    return False

        return False

    except Exception as e:
        log(f"Ошибка при копировании через temp: {e}", "❌ ERROR")
        return False

def check_hosts_file_name():
    """Проверяет правильность написания имени файла hosts"""
    hosts_dir = Path(r"C:\Windows\System32\drivers\etc")
    
    # ✅ НОВОЕ: Создаем директорию если её нет
    if not hosts_dir.exists():
        try:
            hosts_dir.mkdir(parents=True, exist_ok=True)
            log(f"Создана директория: {hosts_dir}")
        except Exception as e:
            log(f"Не удалось создать директорию: {e}", "❌ ERROR")
            return False, f"Не удалось создать директорию etc: {e}"
    
    # Сначала проверяем правильный файл hosts
    hosts_lower = hosts_dir / "hosts"
    if hosts_lower.exists():
        # Дополнительно проверяем кодировку файла
        try:
            hosts_lower.read_text(encoding="utf-8-sig")
            return True, None
        except UnicodeDecodeError:
            # Файл существует, но с проблемами кодировки
            log("Файл hosts существует, но содержит некорректные символы", level="⚠ WARNING")
            return False, "Файл hosts содержит некорректные символы и не может быть прочитан в UTF-8"
    
    # Если правильного файла нет, проверяем есть ли неправильный HOSTS
    hosts_upper = hosts_dir / "HOSTS"
    if hosts_upper.exists():
        log("Обнаружен файл HOSTS (с большими буквами) - это неправильно!", level="⚠ WARNING")
        return False, "Файл должен называться 'hosts' (с маленькими буквами), а не 'HOSTS'"
    
    # ✅ НОВОЕ: Если файла нет вообще - это нормально, мы его создадим
    return True, None  # Изменено с False на True

def is_file_readonly(filepath):
    """Проверяет, установлен ли атрибут 'только для чтения' у файла"""
    try:
        file_stat = os.stat(filepath)
        return not (file_stat.st_mode & stat.S_IWRITE)
    except Exception as e:
        log(f"Ошибка при проверке атрибутов файла: {e}")
        return False

def remove_readonly_attribute(filepath):
    """Снимает атрибут 'только для чтения' с файла"""
    try:
        # Получаем текущие атрибуты файла
        file_stat = os.stat(filepath)
        # Добавляем право на запись
        os.chmod(filepath, file_stat.st_mode | stat.S_IWRITE)
        log(f"Атрибут 'только для чтения' снят с файла: {filepath}")
        return True
    except Exception as e:
        log(f"Ошибка при снятии атрибута 'только для чтения': {e}")
        return False

def safe_read_hosts_file():
    """Безопасно читает файл hosts с обработкой различных кодировок"""
    hosts_path = HOSTS_PATH

    # Fast path: используем кэш если файл не менялся.
    try:
        if hosts_path.exists():
            sig = _get_hosts_sig(hosts_path)
            if sig is not None and _HOSTS_SIG_CACHE == sig and _HOSTS_TEXT_CACHE is not None:
                return _HOSTS_TEXT_CACHE
    except Exception:
        pass
    
    # ✅ НОВОЕ: Проверяем существование файла
    if not hosts_path.exists():
        log(f"Файл hosts не существует, создаем новый: {hosts_path}")
        try:
            # Создаем директорию если её нет
            hosts_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Создаем пустой файл hosts с базовым содержимым
            default_content = """# Copyright (c) 1993-2009 Microsoft Corp.
#
# This is a sample HOSTS file used by Microsoft TCP/IP for Windows.
#
# This file contains the mappings of IP addresses to host names. Each
# entry should be kept on an individual line. The IP address should
# be placed in the first column followed by the corresponding host name.
# The IP address and the host name should be separated by at least one
# space.
#
# Additionally, comments (such as these) may be inserted on individual
# lines or following the machine name denoted by a '#' symbol.
#
# For example:
#
#      102.54.94.97     rhino.acme.com          # source server
#       38.25.63.10     x.acme.com              # x client host

# localhost name resolution is handled within DNS itself.
#	127.0.0.1       localhost
#	::1             localhost
"""
            hosts_path.write_text(default_content, encoding='utf-8-sig')
            _set_hosts_cache(default_content, _get_hosts_sig(hosts_path))
            log("Файл hosts успешно создан с базовым содержимым")
            return default_content
            
        except Exception as e:
            log(f"Ошибка при создании файла hosts: {e}", "❌ ERROR")
            return None
    
    # Если файл существует, пробуем прочитать с разными кодировками
    encodings = ['utf-8', 'utf-8-sig', 'cp1251', 'cp866', 'latin1']

    permission_error_occurred = False

    sig_before = _get_hosts_sig(hosts_path)
    for encoding in encodings:
        try:
            content = hosts_path.read_text(encoding=encoding)
            log(f"Файл hosts успешно прочитан с кодировкой: {encoding}")
            _set_hosts_cache(content, sig_before or _get_hosts_sig(hosts_path))
            return content
        except UnicodeDecodeError:
            continue
        except PermissionError as e:
            log(f"Ошибка при чтении файла hosts с кодировкой {encoding}: {e}")
            permission_error_occurred = True
            continue
        except Exception as e:
            log(f"Ошибка при чтении файла hosts с кодировкой {encoding}: {e}")
            continue

    # Если была ошибка доступа, пробуем восстановить права
    if permission_error_occurred:
        log("🔧 Обнаружена проблема с правами доступа, пытаемся восстановить...")
        success, message = restore_hosts_permissions()
        if success:
            # Пробуем прочитать снова после восстановления прав
            for encoding in encodings:
                try:
                    content = hosts_path.read_text(encoding=encoding)
                    log(f"Файл hosts успешно прочитан после восстановления прав с кодировкой: {encoding}")
                    _set_hosts_cache(content, _get_hosts_sig(hosts_path))
                    return content
                except UnicodeDecodeError:
                    continue
                except Exception as e:
                    log(f"Ошибка при повторном чтении с кодировкой {encoding}: {e}")
                    continue
        else:
            log(f"Не удалось восстановить права: {message}", "❌ ERROR")

    # Если ни одна кодировка не подошла, пробуем с игнорированием ошибок
    try:
        content = hosts_path.read_text(encoding='utf-8', errors='ignore')
        log("Файл hosts прочитан с игнорированием ошибок кодировки", level="⚠ WARNING")
        _set_hosts_cache(content, _get_hosts_sig(hosts_path))
        return content
    except Exception as e:
        log(f"Критическая ошибка при чтении файла hosts: {e}", "❌ ERROR")
        return None

def safe_write_hosts_file(content):
    """Безопасно записывает файл hosts с правильной кодировкой"""
    try:
        # Проверяем атрибут "только для чтения" перед записью
        if is_file_readonly(HOSTS_PATH):
            log("Файл hosts имеет атрибут 'только для чтения', пытаемся снять...")
            if not remove_readonly_attribute(HOSTS_PATH):
                log("Не удалось снять атрибут 'только для чтения'")
                return False

        HOSTS_PATH.write_text(content, encoding="utf-8-sig", newline='\n')
        _set_hosts_cache(content, _get_hosts_sig(HOSTS_PATH))
        return True
    except PermissionError:
        log("Ошибка доступа при записи файла hosts, пытаемся восстановить права...")
        # Пробуем восстановить права и записать снова
        success, message = restore_hosts_permissions()
        if success:
            try:
                HOSTS_PATH.write_text(content, encoding="utf-8-sig", newline='\n')
                log("✅ Файл hosts успешно записан после восстановления прав")
                _set_hosts_cache(content, _get_hosts_sig(HOSTS_PATH))
                return True
            except Exception as e:
                log(f"Ошибка при повторной записи после восстановления прав: {e}", "❌ ERROR")
                return False
        else:
            log(f"Не удалось восстановить права: {message}", "❌ ERROR")
            return False
    except Exception as e:
        log(f"Ошибка при записи файла hosts: {e}")
        return False
    
class HostsManager:
    def __init__(self, status_callback=None):
        self.status_callback = status_callback
        self._last_status: str | None = None
        # При инициализации выполняем единоразовый bootstrap hosts.
        self.check_and_remove_github_api()

    def restore_permissions(self):
        """Восстанавливает права доступа к файлу hosts"""
        success, message = restore_hosts_permissions()
        self.set_status(message)
        return success

    # 🆕 НОВЫЕ МЕТОДЫ ДЛЯ РАБОТЫ С api.github.com
    def check_github_api_in_hosts(self):
        """Проверяет, есть ли запись api.github.com в hosts файле"""
        try:
            content = safe_read_hosts_file()
            if content is None:
                return False
                
            lines = content.splitlines()
            
            for line in lines:
                line = line.strip()
                # Пропускаем пустые строки и комментарии
                if not line or line.startswith('#'):
                    continue
                    
                # Разбиваем строку на части (IP домен)
                parts = line.split()
                if len(parts) >= 2:
                    domain = parts[1]  # Второй элемент - это домен
                    if domain.lower() == "api.github.com":
                        return True
                        
            return False
        except Exception as e:
            log(f"Ошибка при проверке api.github.com в hosts: {e}")
            return False

    def remove_github_api_from_hosts(self):
        """Принудительно удаляет запись api.github.com из hosts файла"""
        try:
            content = safe_read_hosts_file()
            if content is None:
                log("Не удалось прочитать файл hosts для удаления api.github.com")
                return False
                
            lines = content.splitlines(keepends=True)
            new_lines = []
            removed_lines = []
            
            for line in lines:
                line_stripped = line.strip()
                # Пропускаем пустые строки и комментарии
                if not line_stripped or line_stripped.startswith('#'):
                    new_lines.append(line)
                    continue
                    
                # Разбиваем строку на части (IP домен)
                parts = line_stripped.split()
                if len(parts) >= 2:
                    domain = parts[1]  # Второй элемент - это домен
                    if domain.lower() == "api.github.com":
                        # Нашли запись api.github.com - не добавляем её в новый файл
                        removed_lines.append(line_stripped)
                        log(f"Удаляем из hosts: {line_stripped}")
                        continue
                
                # Добавляем все остальные строки
                new_lines.append(line)
            
            if removed_lines:
                # Убираем лишние пустые строки в конце файла
                while new_lines and new_lines[-1].strip() == "":
                    new_lines.pop()
                
                # Оставляем одну пустую строку в конце, если файл не пустой
                if new_lines and not new_lines[-1].endswith('\n'):
                    new_lines[-1] += '\n'
                elif new_lines:
                    new_lines.append('\n')

                if not safe_write_hosts_file("".join(new_lines)):
                    log("Не удалось записать файл hosts после удаления api.github.com")
                    return False
                
                log(f"✅ Удалена запись api.github.com из hosts файла: {removed_lines}")
                self.set_status("Запись api.github.com удалена из hosts файла")
                return True
            else:
                log("Запись api.github.com не найдена в hosts файле")
                return True  # Не ошибка, просто нет записи
                
        except PermissionError:
            log("Нет прав для удаления api.github.com из hosts файла")
            return False
        except Exception as e:
            log(f"Ошибка при удалении api.github.com из hosts: {e}")
            return False

    def check_and_remove_github_api(self):
        """Единоразово применяет bootstrap hosts для текущей сигнатуры."""
        try:
            from config import get_remove_github_api
            from config.reg import (
                get_hosts_bootstrap_signature,
                set_hosts_bootstrap_signature,
                set_hosts_bootstrap_v1_done,
            )

            expected_signature = _get_hosts_bootstrap_signature()
            applied_signature = get_hosts_bootstrap_signature()

            if applied_signature == expected_signature:
                log("Bootstrap hosts уже применён для текущей сигнатуры", "DEBUG")
                return

            previous_tracker_domain, _ = _extract_tracker_from_bootstrap_signature(applied_signature)
            if previous_tracker_domain == _ZAPRET_TRACKER_DOMAIN:
                previous_tracker_domain = None

            if applied_signature:
                log(
                    f"Обновляем bootstrap hosts: сигнатура изменена ({applied_signature} -> {expected_signature})",
                    "DEBUG",
                )
            else:
                log("Выполняем bootstrap hosts для текущей сигнатуры", "DEBUG")

            content = safe_read_hosts_file()
            if content is None:
                log("Не удалось прочитать hosts для bootstrap", "❌ ERROR")
                return

            remove_github = bool(get_remove_github_api())

            lines = content.splitlines(keepends=True)
            new_lines: list[str] = []

            removed_github = False
            tracker_has_correct_ip = False
            tracker_ip_corrected = False
            previous_tracker_removed = False

            for line in lines:
                line_stripped = line.strip()
                if not line_stripped:
                    new_lines.append(line)
                    continue

                mapping_part, sep, comment_part = line.partition('#')
                mapping_stripped = mapping_part.strip()
                if not mapping_stripped:
                    new_lines.append(line)
                    continue

                parts = mapping_stripped.split()
                if len(parts) < 2:
                    new_lines.append(line)
                    continue

                ip = parts[0]
                domains = parts[1:]
                domains_lower = [domain.lower() for domain in domains]
                updated_domains = domains
                line_changed = False

                if remove_github and _GITHUB_API_DOMAIN in domains_lower:
                    removed_github = True
                    updated_domains = [domain for domain in updated_domains if domain.lower() != _GITHUB_API_DOMAIN]
                    line_changed = True

                if previous_tracker_domain and previous_tracker_domain in domains_lower:
                    updated_domains = [domain for domain in updated_domains if domain.lower() != previous_tracker_domain]
                    previous_tracker_removed = True
                    line_changed = True
                    log(f"Удаляем устаревший трекер-домен: {mapping_stripped}")

                if _ZAPRET_TRACKER_DOMAIN in domains_lower:
                    if ip == _ZAPRET_TRACKER_IP:
                        tracker_has_correct_ip = True
                    else:
                        tracker_ip_corrected = True
                        updated_domains = [domain for domain in updated_domains if domain.lower() != _ZAPRET_TRACKER_DOMAIN]
                        line_changed = True
                        log(f"Удаляем запись {_ZAPRET_TRACKER_DOMAIN} с некорректным IP: {mapping_stripped}")

                if line_changed:
                    if not updated_domains:
                        log(f"Удаляем из hosts: {mapping_stripped}")
                        continue

                    rebuilt_line = f"{ip} {' '.join(updated_domains)}"
                    comment = comment_part.strip() if sep else ""
                    if comment:
                        rebuilt_line += f" # {comment}"
                    new_lines.append(rebuilt_line + "\n")
                    if remove_github and _GITHUB_API_DOMAIN in domains_lower:
                        log(f"Обновляем строку hosts без api.github.com: {mapping_stripped}")
                    continue

                new_lines.append(line)

            tracker_added = False
            if not tracker_has_correct_ip:
                while new_lines and new_lines[-1].strip() == "":
                    new_lines.pop()

                if new_lines and not new_lines[-1].endswith('\n'):
                    new_lines[-1] += '\n'
                if new_lines:
                    new_lines.append('\n')

                new_lines.append(f"{_ZAPRET_TRACKER_IP} {_ZAPRET_TRACKER_DOMAIN}\n")
                tracker_added = True
                log(f"Добавляем в hosts: {_ZAPRET_TRACKER_IP} {_ZAPRET_TRACKER_DOMAIN}")

            changed = removed_github or tracker_ip_corrected or previous_tracker_removed or tracker_added
            if changed and not safe_write_hosts_file("".join(new_lines)):
                log("Не удалось записать hosts после bootstrap", "❌ ERROR")
                return

            if not set_hosts_bootstrap_signature(expected_signature):
                log("Не удалось сохранить сигнатуру bootstrap hosts", "⚠ WARNING")
                return

            if not set_hosts_bootstrap_v1_done(True):
                log("Не удалось сохранить legacy-флаг bootstrap hosts", "DEBUG")

            if remove_github:
                if removed_github:
                    log("✅ Запись api.github.com удалена из hosts (первый запуск)")
                else:
                    log("✅ Запись api.github.com не найдена в hosts (первый запуск)")
            else:
                log("⚙️ Удаление api.github.com отключено в настройках")

            if tracker_added and (tracker_ip_corrected or previous_tracker_removed):
                log("✅ Запись zapret-tracker.duckdns.org обновлена на корректный IP (первый запуск)")
            elif tracker_added:
                log("✅ Запись zapret-tracker.duckdns.org добавлена в hosts (первый запуск)")
            elif tracker_ip_corrected or previous_tracker_removed:
                log("✅ Удалены некорректные записи zapret-tracker.duckdns.org (первый запуск)")
            else:
                log("✅ Запись zapret-tracker.duckdns.org уже есть в hosts")
        except Exception as e:
            log(f"Ошибка при bootstrap hosts: {e}")

    # ------------------------- сервис -------------------------
    def get_active_domains_map(self) -> dict[str, str]:
        """Возвращает {domain: ip} для всех управляемых доменов, найденных в hosts (без проверки IP)."""
        current_active: dict[str, str] = {}
        managed_domains = _get_all_managed_domains()
        try:
            content = safe_read_hosts_file()
            if content is None:
                return current_active
                
            lines = content.splitlines()
            
            for line in lines:
                line = line.strip()
                # Пропускаем пустые строки и комментарии
                if not line or line.startswith('#'):
                    continue
                    
                # Разбиваем строку на части (IP домен)
                parts = line.split()
                if len(parts) >= 2:
                    ip = parts[0]
                    domain = parts[1]
                    
                    if domain in managed_domains:
                        current_active[domain] = ip
                            
            log(f"Найдено активных управляемых доменов: {len(current_active)}", "DEBUG")
        except Exception as e:
            log(f"Ошибка при чтении hosts: {e}", "ERROR")
        return current_active

    def get_active_domains(self) -> set:
        """Back-compat: возвращает множество активных доменов (без проверки IP)."""
        return set(self.get_active_domains_map().keys())

    def set_status(self, message: str):
        self._last_status = message
        if self.status_callback:
            self.status_callback(message)
        else:
            print(message)

    @property
    def last_status(self) -> str | None:
        return self._last_status

    # ------------------------- проверки -------------------------

    def is_proxy_domains_active(self) -> bool:
        """Проверяет, есть ли активные (НЕ закомментированные) записи управляемых доменов в hosts"""
        try:
            content = safe_read_hosts_file()
            if content is None:
                return False
                
            lines = content.splitlines()
            domains = _get_all_managed_domains()
            
            for line in lines:
                line = line.strip()
                # Пропускаем пустые строки и комментарии
                if not line or line.startswith('#'):
                    continue
                    
                # Разбиваем строку на части (IP домен)
                parts = line.split()
                if len(parts) >= 2:
                    domain = parts[1]  # Второй элемент - это домен
                    if domain in domains:
                        # Найден активный (не закомментированный) домен
                        return True
                        
            return False
        except Exception as e:
            log(f"Ошибка при проверке hosts: {e}")
            return False

    def is_adobe_domains_active(self) -> bool:
        """Проверяет, есть ли активные записи Adobe в hosts"""
        try:
            content = safe_read_hosts_file()
            if content is None:
                return False
                
            lines = content.splitlines()
            domains = set(ADOBE_DOMAINS.keys())
            
            for line in lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                    
                parts = line.split()
                if len(parts) >= 2:
                    domain = parts[1]
                    if domain in domains:
                        return True
                        
            return False
        except Exception as e:
            log(f"Ошибка при проверке Adobe в hosts: {e}")
            return False

    def is_hosts_file_accessible(self) -> bool:
        """Проверяет, доступен ли файл hosts для чтения и записи."""
        try:
            # Проверяем правильность написания имени файла
            is_correct, error_msg = check_hosts_file_name()
            if not is_correct:
                log(error_msg)
                return False
            
            # ✅ НОВОЕ: Если файла нет, создаем его
            if not HOSTS_PATH.exists():
                log("Файл hosts не существует, будет создан при первой записи")
                # Проверяем, можем ли мы создать файл
                try:
                    # Пробуем создать временный файл в той же директории
                    test_file = HOSTS_PATH.parent / "test_write_permission.tmp"
                    test_file.write_text("test", encoding="utf-8")
                    test_file.unlink()  # Удаляем тестовый файл
                    return True
                except PermissionError:
                    log("Нет прав для создания файла hosts. Требуются права администратора.")
                    return False
            
            # Проверяем возможность чтения с безопасной функцией
            content = safe_read_hosts_file()
            if content is None:
                return False
                    
            # Проверяем атрибут "только для чтения"
            if is_file_readonly(HOSTS_PATH):
                log("Файл hosts имеет атрибут 'только для чтения'")
            
            # Проверяем возможность записи (пробуем открыть в режиме добавления)
            try:
                with HOSTS_PATH.open("a", encoding="utf-8-sig") as f:
                    pass
            except PermissionError:
                # Если не можем открыть для записи, но файл НЕ readonly, 
                # значит действительно нет прав администратора
                if not is_file_readonly(HOSTS_PATH):
                    raise
                # Если файл readonly, попробуем снять атрибут
                log("Не удается открыть файл для записи из-за атрибута 'только для чтения'")
            
            return True
            
        except PermissionError:
            log(f"Нет прав доступа к файлу hosts: {HOSTS_PATH}")
            return False
        except FileNotFoundError:
            log(f"Файл hosts не найден: {HOSTS_PATH}")
            return False
        except Exception as e:
            log(f"Ошибка при проверке доступности hosts: {e}")
            return False

    def _no_perm(self):
        """Обработка ошибки прав доступа"""
        self.set_status("Нет прав для изменения файла hosts")
        log("Нет прав для изменения файла hosts")

    def add_proxy_domains(self) -> bool:
        """LEGACY: включает все домены (профиль 0) + статические."""
        log("🟡 add_proxy_domains начат (legacy)", "DEBUG")

        all_domains: dict[str, str] = {}
        default_profile = (get_dns_profiles() or [None])[0]
        for service_name in get_all_services():
            domain_map = get_service_domain_ip_map(service_name, default_profile) if default_profile else {}
            if domain_map:
                all_domains.update(domain_map)
            else:
                all_domains.update(get_service_domains(service_name))

        return self.apply_domain_ip_map(all_domains)

    def remove_proxy_domains(self) -> bool:
        """LEGACY: удаляет все управляемые домены из hosts."""
        log("🟡 remove_proxy_domains начат (legacy)", "DEBUG")
        return self.apply_domain_ip_map({})
    
    def apply_selected_domains(self, selected_domains):
        """LEGACY: применяет выбранные домены (IP берётся из профиля 0)."""
        try:
            selected = set(selected_domains or [])
        except Exception:
            selected = set()

        log(f"🟡 apply_selected_domains начат (legacy): {len(selected)} доменов", "DEBUG")

        if not selected:
            return self.apply_domain_ip_map({})

        base_map: dict[str, str] = {}
        default_profile = (get_dns_profiles() or [None])[0]
        for service_name in get_all_services():
            domain_map = get_service_domain_ip_map(service_name, default_profile) if default_profile else {}
            if domain_map:
                base_map.update(domain_map)
            else:
                base_map.update(get_service_domains(service_name))

        out: dict[str, str] = {domain: ip for domain, ip in base_map.items() if domain in selected}
        return self.apply_domain_ip_map(out)

    def apply_service_dns_selections(self, service_dns: dict[str, str], static_enabled: set[str] | None = None) -> bool:
        """
        Применяет выбор DNS-профилей по сервисам.

        Args:
            service_dns: {service_name: profile_name or 'off'}
            static_enabled: set(service_name) для сервисов, которые включаются без выбора профиля
        """
        log("🟡 apply_service_dns_selections начат", "DEBUG")

        # key = normalized domain; value = (display_domain, [ip1, ip2, ...]).
        selected_by_domain: dict[str, tuple[str, list[str]]] = {}
        domain_order: list[str] = []

        def merge_rows(rows: list[tuple[str, str]]) -> None:
            per_service: dict[str, tuple[str, list[str], set[str]]] = {}
            per_service_order: list[str] = []

            for domain, ip in rows:
                domain_s = (domain or "").strip()
                ip_s = (ip or "").strip()
                if not domain_s or not ip_s:
                    continue

                domain_key = domain_s.casefold()
                ip_key = ip_s.casefold()
                item = per_service.get(domain_key)
                if item is None:
                    per_service[domain_key] = (domain_s, [ip_s], {ip_key})
                    per_service_order.append(domain_key)
                    continue

                display_domain, ips, seen_ips = item
                if ip_key in seen_ips:
                    continue
                ips.append(ip_s)
                seen_ips.add(ip_key)
                per_service[domain_key] = (display_domain, ips, seen_ips)

            for domain_key in per_service_order:
                display_domain, ips, _seen_ips = per_service[domain_key]
                if domain_key not in selected_by_domain:
                    domain_order.append(domain_key)
                # Keep old override semantics between services: later service replaces domain mapping.
                selected_by_domain[domain_key] = (display_domain, ips)

        for service_name, profile_name in (service_dns or {}).items():
            if not isinstance(service_name, str):
                continue
            if not isinstance(profile_name, str):
                continue

            normalized = profile_name.strip().lower()
            if not normalized or normalized in ("off", "откл", "откл.", "0", "false"):
                continue

            rows = get_service_domain_ip_rows(service_name, profile_name.strip())
            if not rows:
                # Профиль недоступен для сервиса (не хватает IP) — просто пропускаем.
                continue
            merge_rows(rows)

        if static_enabled:
            default_profile = (get_dns_profiles() or [None])[0]
            for service_name in static_enabled:
                rows = get_service_domain_ip_rows(service_name, default_profile) if default_profile else []
                if rows:
                    merge_rows(rows)

        selected_rows: list[tuple[str, str]] = []
        for domain_key in domain_order:
            display_domain, ips = selected_by_domain.get(domain_key, ("", []))
            for ip in ips:
                selected_rows.append((display_domain, ip))

        return self.apply_domain_ip_rows(selected_rows)

    def apply_domain_ip_map(self, domain_ip_map: dict[str, str]) -> bool:
        """Применяет домены в hosts из словаря {domain: ip}."""
        rows: list[tuple[str, str]] = []
        for domain, ip in (domain_ip_map or {}).items():
            if not isinstance(domain, str) or not isinstance(ip, str):
                continue
            rows.append((domain, ip))
        return self.apply_domain_ip_rows(rows)

    def apply_domain_ip_rows(self, domain_ip_rows: list[tuple[str, str]]) -> bool:
        """Применяет домены в hosts: удаляет все управляемые и добавляет указанные строки (domain, ip)."""
        log(f"🟡 apply_domain_ip_rows начат: {len(domain_ip_rows)} записей", "DEBUG")

        if not self.is_hosts_file_accessible():
            self.set_status("Файл hosts недоступен для изменения")
            return False

        managed_domains = _get_all_managed_domains()

        try:
            content = safe_read_hosts_file()
            if content is None:
                self.set_status("Не удалось прочитать файл hosts")
                return False

            lines = content.splitlines(keepends=True)
            new_lines: list[str] = []

            removed_count = 0
            for line in lines:
                if (
                    line.strip()
                    and not line.lstrip().startswith("#")
                    and len(line.split()) >= 2
                    and line.split()[1] in managed_domains
                ):
                    removed_count += 1
                    continue
                new_lines.append(line)

            # Убираем лишние пустые строки в конце
            while new_lines and new_lines[-1].strip() == "":
                new_lines.pop()

            desired_rows: list[tuple[str, str]] = []
            seen_rows: set[tuple[str, str]] = set()
            for row in (domain_ip_rows or []):
                if not isinstance(row, (tuple, list)) or len(row) < 2:
                    continue
                domain = str(row[0]).strip()
                ip = str(row[1]).strip()
                if not domain or not ip:
                    continue
                row_key = (domain.casefold(), ip.casefold())
                if row_key in seen_rows:
                    continue
                seen_rows.add(row_key)
                desired_rows.append((domain, ip))

            # Ничего не добавляем — просто очищаем управляемые домены
            if not desired_rows:
                if new_lines and not new_lines[-1].endswith("\n"):
                    new_lines[-1] += "\n"
                if not safe_write_hosts_file("".join(new_lines)):
                    return False
                self.set_status(f"Файл hosts обновлён: удалено {removed_count} записей")
                return True

            # Добавляем выбранные домены
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines.append("\n")
            new_lines.append("\n")  # Разделитель

            for domain, ip in desired_rows:
                new_lines.append(f"{ip} {domain}\n")

            if not safe_write_hosts_file("".join(new_lines)):
                self.set_status("Не удалось записать файл hosts")
                return False

            self.set_status(f"Файл hosts обновлён: добавлено {len(desired_rows)} записей")
            log(f"✅ apply_domain_ip_rows: removed={removed_count}, added={len(desired_rows)}", "DEBUG")
            return True

        except PermissionError:
            log("Ошибка прав доступа в apply_domain_ip_rows", "ERROR")
            self._no_perm()
            return False
        except Exception as e:
            log(f"Ошибка в apply_domain_ip_rows: {e}", "ERROR")
            return False

    # НОВЫЕ МЕТОДЫ ДЛЯ ADOBE
    def add_adobe_domains(self) -> bool:
        """Добавляет домены Adobe для блокировки активации"""
        log("🔒 Добавление доменов Adobe для блокировки активации", "DEBUG")
        
        if not self.is_hosts_file_accessible():
            self.set_status("Файл hosts недоступен для изменения")
            return False
        
        try:
            content = safe_read_hosts_file()
            if content is None:
                return False
            
            # Удаляем старые записи Adobe
            lines = content.splitlines(keepends=True)
            domains_to_remove = set(ADOBE_DOMAINS.keys())
            
            new_lines = []
            skip_adobe_comment = False
            for line in lines:
                # Пропускаем старый комментарий Adobe
                if "# Adobe Activation Block" in line or "# Adobe Block" in line:
                    skip_adobe_comment = True
                    continue
                if skip_adobe_comment and "# Generated by" in line:
                    skip_adobe_comment = False
                    continue
                    
                if (line.strip() and 
                    not line.lstrip().startswith("#") and 
                    len(line.split()) >= 2 and 
                    line.split()[1] in domains_to_remove):
                    continue
                new_lines.append(line)
            
            # Убираем лишние пустые строки
            while new_lines and new_lines[-1].strip() == "":
                new_lines.pop()
            
            # Добавляем новые домены Adobe
            if new_lines and not new_lines[-1].endswith('\n'):
                new_lines.append('\n')
            new_lines.append('\n')
            new_lines.append('# Adobe Activation Block\n')
            new_lines.append('# Generated by Zapret-WinGUI\n')
            
            for domain, ip in ADOBE_DOMAINS.items():
                new_lines.append(f"{ip} {domain}\n")
            
            # Записываем
            if not safe_write_hosts_file("".join(new_lines)):
                return False
            
            self.set_status(f"Блокировка Adobe активирована: добавлено {len(ADOBE_DOMAINS)} записей")
            log(f"✅ Добавлены домены Adobe для блокировки", "DEBUG")
            return True
            
        except PermissionError:
            log("Ошибка прав доступа при добавлении Adobe доменов", "ERROR")
            self._no_perm()
            return False
        except Exception as e:
            log(f"Ошибка при добавлении Adobe доменов: {e}", "ERROR")
            return False

    def clear_hosts_file(self) -> bool:
        """Полностью очищает файл hosts, оставляя только базовое содержимое Windows"""
        log("🗑️ Полная очистка файла hosts", "DEBUG")
        
        if not self.is_hosts_file_accessible():
            self.set_status("Файл hosts недоступен для изменения")
            return False
        
        try:
            # Базовое содержимое hosts файла Windows
            default_content = """# Copyright (c) 1993-2009 Microsoft Corp.
    #
    # This is a sample HOSTS file used by Microsoft TCP/IP for Windows.
    #
    # This file contains the mappings of IP addresses to host names. Each
    # entry should be kept on an individual line. The IP address should
    # be placed in the first column followed by the corresponding host name.
    # The IP address and the host name should be separated by at least one
    # space.
    #
    # Additionally, comments (such as these) may be inserted on individual
    # lines or following the machine name denoted by a '#' symbol.
    #
    # For example:
    #
    #      102.54.94.97     rhino.acme.com          # source server
    #       38.25.63.10     x.acme.com              # x client host

    # localhost name resolution is handled within DNS itself.
    #	127.0.0.1       localhost
    #	::1             localhost
    """
            
            if not safe_write_hosts_file(default_content):
                log("Не удалось записать файл hosts после очистки")
                return False
            
            self.set_status("Файл hosts полностью очищен")
            log("✅ Файл hosts успешно очищен (восстановлено базовое содержимое)", "DEBUG")
            return True
            
        except PermissionError:
            log("Ошибка прав доступа при очистке hosts файла", "ERROR")
            self._no_perm()
            return False
        except Exception as e:
            log(f"Ошибка при очистке hosts файла: {e}", "ERROR")
            return False
        
    def remove_adobe_domains(self) -> bool:
        """Удаляет домены Adobe из hosts файла"""
        log("🔓 Удаление доменов Adobe", "DEBUG")
        
        if not self.is_hosts_file_accessible():
            self.set_status("Файл hosts недоступен для изменения")
            return False
        
        try:
            content = safe_read_hosts_file()
            if content is None:
                return False
            
            lines = content.splitlines(keepends=True)
            domains = set(ADOBE_DOMAINS.keys())
            
            new_lines = []
            removed_count = 0
            skip_next = False
            
            for line in lines:
                # Удаляем комментарии Adobe
                if "# Adobe Activation Block" in line or "# Adobe Block" in line:
                    skip_next = True
                    continue
                if skip_next and "# Generated by" in line:
                    skip_next = False
                    continue
                    
                if (line.strip() and 
                    not line.lstrip().startswith("#") and 
                    len(line.split()) >= 2 and 
                    line.split()[1] in domains):
                    removed_count += 1
                    continue
                    
                new_lines.append(line)
            
            # Убираем лишние пустые строки
            while new_lines and new_lines[-1].strip() == "":
                new_lines.pop()
            
            if new_lines and not new_lines[-1].endswith('\n'):
                new_lines.append('\n')
            
            if not safe_write_hosts_file("".join(new_lines)):
                return False
            
            self.set_status(f"Блокировка Adobe отключена: удалено {removed_count} записей")
            log(f"✅ Удалено {removed_count} доменов Adobe", "DEBUG")
            return True
            
        except PermissionError:
            log("Ошибка прав доступа при удалении Adobe доменов", "ERROR")
            self._no_perm()
            return False
        except Exception as e:
            log(f"Ошибка при удалении Adobe доменов: {e}", "ERROR")
            return False
