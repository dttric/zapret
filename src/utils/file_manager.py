"""Утилиты для управления файлами приложения."""

import os

from log import log
from config import LISTS_FOLDER


def ensure_required_files():
    """Проверяет/подготавливает обязательные файлы списков."""
    try:
        os.makedirs(LISTS_FOLDER, exist_ok=True)

        from utils.hostlists_manager import ensure_hostlists_exist
        from utils.ipsets_manager import ensure_ipsets_exist
        from utils.netrogat_manager import ensure_netrogat_exists

        hostlists_ok = ensure_hostlists_exist()
        ipsets_ok = ensure_ipsets_exist()
        netrogat_ok = ensure_netrogat_exists()

        result = bool(hostlists_ok and ipsets_ok and netrogat_ok)
        if result:
            log("Обязательные файлы списков готовы", "DEBUG")
        else:
            log(
                f"Не все обязательные файлы готовы: hostlists={hostlists_ok}, ipsets={ipsets_ok}, netrogat={netrogat_ok}",
                "WARNING",
            )
        return result
    except Exception as e:
        log(f"Ошибка ensure_required_files: {e}", "❌ ERROR")
        return False


def _get_other_default_content():
    """Возвращает актуальный шаблон other.txt из кода."""
    try:
        from utils.hostlists_manager import build_other_template_content

        return build_other_template_content()
    except Exception:
        return "youtube.com\ngooglevideo.com\ndiscord.com\ndiscord.gg\n"


def create_file_if_missing(file_path, content="", description="файл"):
    """Создает конкретный файл, если он отсутствует."""
    if not os.path.exists(file_path):
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            filename = os.path.basename(file_path)
            log(f"Создан {description}: {filename}", "INFO")
            return True
        except Exception as e:
            filename = os.path.basename(file_path)
            log(f"Ошибка создания файла {filename}: {e}", "❌ ERROR")
            return False

    return False


def ensure_file_exists(file_path, default_content=""):
    """Устаревшая функция - используйте create_file_if_missing."""
    return create_file_if_missing(file_path, default_content)
