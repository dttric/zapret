# ui/pages/preset_config_page.py
"""Страница редактора конфига preset-zapret1.txt / preset-zapret2.txt"""

import os
import subprocess
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel
)
from PyQt6.QtGui import QFont

from .base_page import BasePage, ScrollBlockingPlainTextEdit
from config import MAIN_DIRECTORY
from config.config import ZAPRET2_MODES, ZAPRET1_DIRECT_MODES
from strategy_menu import get_strategy_launch_method
from ui.theme import get_theme_tokens
from ui.compat_widgets import ActionButton
from ui.text_catalog import tr as tr_catalog
from log import log

try:
    from qfluentwidgets import CaptionLabel
except ImportError:
    CaptionLabel = QLabel
from utils.process_status import format_expected_process_status


class PresetConfigPage(BasePage):
    """Страница редактора конфига preset-zapret1.txt / preset-zapret2.txt"""

    def __init__(self, parent=None):
        # Сначала определяем путь к файлу, чтобы использовать в subtitle
        self._preset_path, self._preset_display_name = self._get_current_preset_path()

        super().__init__(
            "Активный пресет",
            tr_catalog(
                "page.preset_config.subtitle_template",
                default=(
                    "Пресет - это txt файл с настройками программы, вместо использования GUI Вы можете "
                    "обмениваться напрямую этими пресетами, чтобы быстро изменить настройки программы. "
                    "GUI подхватывает настройки отсюда. В данном окне представлен редактор основного txt файла "
                    "— {preset_name}"
                ),
            ).format(preset_name=self._preset_display_name),
            parent,
            title_key="page.preset_config.title",
        )

        self._is_loading = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_file)

        self._last_mtime = 0  # Для отслеживания изменений файла
        self._file_status = ""
        self._process_status = "⏳ Проверка..."
        self._process_monitor_connected = False
        self._loaded_once = False

        self._build_ui()
        self._setup_shortcuts()
        self._update_status("Подготовка редактора...")

        # Таймер только для проверки изменений файла (без проверки процесса в GUI-потоке)
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._on_timer_tick)

        # Подписываемся на глобальный монитор процессов (асинхронно, без фризов UI)
        self._connect_process_monitor()
        self._sync_process_status_from_cache()

    def _get_current_preset_path(self) -> tuple[str, str]:
        """Returns (preset_path, display_name) based on current mode"""
        method = get_strategy_launch_method()

        if method == "direct_zapret2_orchestra":
            # Orchestra режим использует отдельный файл
            return (os.path.join(MAIN_DIRECTORY, "preset-zapret2-orchestra.txt"),
                    "preset-zapret2-orchestra.txt (Zapret 2 Orchestra)")
        elif method in ZAPRET2_MODES or method == "direct_zapret2":
            return (os.path.join(MAIN_DIRECTORY, "preset-zapret2.txt"),
                    "preset-zapret2.txt (Zapret 2)")
        elif method in ZAPRET1_DIRECT_MODES or method == "direct_zapret1":
            return (os.path.join(MAIN_DIRECTORY, "preset-zapret1.txt"),
                    "preset-zapret1.txt (Zapret 1)")
        else:
            # BAT mode or other - default to Zapret 2
            return (os.path.join(MAIN_DIRECTORY, "preset-zapret2.txt"),
                    "preset-zapret2.txt (Zapret 2)")

    def refresh_for_current_mode(self):
        """Called when strategy launch method changes - reloads correct preset file"""
        new_path, new_display = self._get_current_preset_path()
        if new_path != self._preset_path:
            # Save pending changes to old file first
            if self._save_timer.isActive():
                self._save_timer.stop()
                self._save_file()

            # Switch to new file
            self._preset_path = new_path
            self._preset_display_name = new_display
            if self._loaded_once or self.isVisible():
                self._load_file()
                self._loaded_once = True
            try:
                if hasattr(self, 'subtitle_label'):
                    self.subtitle_label.setText(
                        tr_catalog(
                            "page.preset_config.subtitle_template",
                            default=(
                                "Пресет - это txt файл с настройками программы, вместо использования GUI Вы можете "
                                "обмениваться напрямую этими пресетами, чтобы быстро изменить настройки программы. "
                                "GUI подхватывает настройки отсюда. В данном окне представлен редактор основного txt файла "
                                "— {preset_name}"
                            ),
                        ).format(preset_name=self._preset_display_name)
                    )
            except Exception:
                pass
        # В любом случае обновляем ожидаемый процесс под новый режим
        self._sync_process_status_from_cache()

    def set_ui_language(self, language: str) -> None:
        super().set_ui_language(language)
        try:
            if self.subtitle_label is not None:
                self.subtitle_label.setText(
                    tr_catalog(
                        "page.preset_config.subtitle_template",
                        language=language,
                        default=(
                            "Пресет - это txt файл с настройками программы, вместо использования GUI Вы можете "
                            "обмениваться напрямую этими пресетами, чтобы быстро изменить настройки программы. "
                            "GUI подхватывает настройки отсюда. В данном окне представлен редактор основного txt файла "
                            "— {preset_name}"
                        ),
                    ).format(preset_name=self._preset_display_name)
                )
            if getattr(self, "notepad_btn", None) is not None:
                self.notepad_btn.setText(
                    tr_catalog(
                        "page.preset_config.button.open_notepad",
                        language=language,
                        default="Открыть в блокноте",
                    )
                )
        except Exception:
            pass

    def _build_ui(self):
        """Строит UI страницы"""
        tokens = get_theme_tokens()

        # Панель кнопок
        buttons_widget = QWidget()
        buttons_layout = QHBoxLayout(buttons_widget)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(8)

        # Кнопка "Открыть в блокноте"
        self.notepad_btn = ActionButton(
            tr_catalog(
                "page.preset_config.button.open_notepad",
                language=self._ui_language,
                default="Открыть в блокноте",
            ),
            "mdi.open-in-new",
            accent=False,
        )
        self.notepad_btn.setProperty("uiVariant", "compact")
        self.notepad_btn.setFixedHeight(32)
        self.notepad_btn.clicked.connect(self._open_in_notepad)
        buttons_layout.addWidget(self.notepad_btn)

        buttons_layout.addStretch()
        self.layout.addWidget(buttons_widget)

        # Редактор
        self.editor = ScrollBlockingPlainTextEdit()
        self.editor.setFont(QFont("Consolas", 11))
        self.editor.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {tokens.surface_bg};
                color: {tokens.fg};
                border: 1px solid {tokens.surface_border};
                border-radius: 6px;
                padding: 12px;
                selection-background-color: {tokens.accent_soft_bg_hover};
            }}
        """)
        self.editor.setMinimumHeight(400)
        self.editor.textChanged.connect(self._on_text_changed)
        self.layout.addWidget(self.editor, 1)

        # Статус-бар
        self.status_label = CaptionLabel()
        self.status_label.setStyleSheet(f"color: {tokens.fg_faint}; padding-top: 8px;")
        self.status_label.setFont(QFont("Segoe UI Variable", 8))
        self.layout.addWidget(self.status_label)

    def _setup_shortcuts(self):
        """Настраивает горячие клавиши"""
        # Ctrl+S для сохранения (уже работает автоматически)
        pass

    def _load_file(self):
        """Загружает файл с диска, создаёт если не существует"""
        self._is_loading = True
        try:
            if not os.path.exists(self._preset_path):
                method = get_strategy_launch_method()
                if method == "direct_zapret2_orchestra":
                    from preset_orchestra_zapret2 import ensure_default_preset_exists
                    ok = ensure_default_preset_exists()
                    if ok:
                        log("Создан дефолтный orchestra пресет через ensure_default_preset_exists()", "INFO")
                    else:
                        log(
                            "Не удалось создать preset-zapret2-orchestra.txt: отсутствует built-in шаблон Default. "
                            "Ожидается: %APPDATA%/zapret/orchestra_zapret2/presets_orchestra_zapret2_template/Default.txt",
                            "ERROR",
                        )
                        try:
                            with open(self._preset_path, 'w', encoding='utf-8') as f:
                                f.write(
                                    "# ERROR: missing orchestra preset template: Default\n"
                                    "# Expected: %APPDATA%/zapret/orchestra_zapret2/presets_orchestra_zapret2_template/Default.txt\n"
                                    "#\n"
                                    "# Fix: reinstall/update the app or restore orchestra templates folder.\n\n"
                                )
                        except Exception:
                            pass
                elif method == "direct_zapret2":
                    from preset_zapret2 import ensure_default_preset_exists
                    ok = ensure_default_preset_exists()
                    if ok:
                        log("Создан дефолтный пресет через ensure_default_preset_exists()", "INFO")
                    else:
                        log(
                            "Не удалось создать preset-zapret2.txt: отсутствует built-in шаблон Default. "
                            "Ожидается: %APPDATA%/zapret/presets_v2_template/Default.txt",
                            "ERROR",
                        )
                        try:
                            with open(self._preset_path, 'w', encoding='utf-8') as f:
                                f.write(
                                    "# ERROR: missing built-in preset template: Default\n"
                                    "# Expected: %APPDATA%/zapret/presets_v2_template/Default.txt\n"
                                    "#\n"
                                    "# Fix: reinstall/update the app or restore %APPDATA%/zapret/presets_v2_template.\n\n"
                                )
                        except Exception:
                            pass
                elif method in ZAPRET1_DIRECT_MODES or method == "direct_zapret1":
                    from preset_zapret1 import ensure_default_preset_exists_v1
                    ok = ensure_default_preset_exists_v1()
                    if ok:
                        log("Создан дефолтный пресет V1 через ensure_default_preset_exists_v1()", "INFO")
                    else:
                        log("Не удалось создать preset-zapret1.txt", "ERROR")
                        try:
                            with open(self._preset_path, 'w', encoding='utf-8') as f:
                                f.write("# Preset: Default\n# Zapret 1\n\n--wf-tcp=443\n--wf-udp=443\n")
                        except Exception:
                            pass
                else:
                    with open(self._preset_path, 'w', encoding='utf-8') as f:
                        f.write(f"# {self._preset_display_name}\n# Add your winws arguments here, one per line\n\n")
                    log(f"Создан новый пустой файл: {self._preset_path}", "INFO")

            with open(self._preset_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.editor.setPlainText(content)
            self._last_mtime = os.path.getmtime(self._preset_path)
            self._update_status("Загружено")
        except Exception as e:
            log(f"Ошибка загрузки {os.path.basename(self._preset_path)}: {e}", "ERROR")
            self._update_status(f"Ошибка: {e}")
        finally:
            self._is_loading = False

    def _on_text_changed(self):
        """Обработчик изменения текста"""
        if self._is_loading:
            return

        # Debounce сохранения - 1 секунда
        self._save_timer.stop()
        self._save_timer.start(1000)
        self._update_status("Изменения...")

    def _save_file(self):
        """Сохраняет файл на диск и синхронизирует обратно в presets/."""
        try:
            content = self.editor.toPlainText()
            with open(self._preset_path, 'w', encoding='utf-8') as f:
                f.write(content)

            self._last_mtime = os.path.getmtime(self._preset_path)
            now = datetime.now().strftime("%H:%M:%S")
            self._update_status(f"Сохранено {now}")
            log(f"Сохранен {os.path.basename(self._preset_path)}", "DEBUG")

            # Sync back to presets/<active_name>.txt so changes persist
            # across preset switches (active file → source preset file).
            self._sync_active_to_preset_file(content)

        except Exception as e:
            log(f"Ошибка сохранения {os.path.basename(self._preset_path)}: {e}", "ERROR")
            self._update_status(f"Ошибка: {e}")

    def _sync_active_to_preset_file(self, content: str):
        """Writes active preset content back to presets/<name>.txt."""
        method = get_strategy_launch_method()
        try:
            if method in ZAPRET1_DIRECT_MODES or method == "direct_zapret1":
                from preset_zapret1 import get_active_preset_name_v1, get_preset_path_v1
                active_name = get_active_preset_name_v1()
                if not active_name:
                    log("Sync skip: no active V1 preset name", "DEBUG")
                    return
                preset_path = get_preset_path_v1(active_name)
            elif method == "direct_zapret2_orchestra":
                from preset_orchestra_zapret2 import get_active_preset_name, get_preset_path
                active_name = get_active_preset_name()
                if not active_name:
                    log("Sync skip: no active orchestra preset name", "DEBUG")
                    return
                preset_path = get_preset_path(active_name)
            else:
                from preset_zapret2 import get_active_preset_name, get_preset_path
                active_name = get_active_preset_name()
                if not active_name:
                    log("Sync skip: no active preset name", "DEBUG")
                    return
                preset_path = get_preset_path(active_name)

            preset_path.parent.mkdir(parents=True, exist_ok=True)

            with open(str(preset_path), 'w', encoding='utf-8') as f:
                f.write(content)
            log(f"Синхронизирован активный пресет → {preset_path}", "DEBUG")

        except Exception as e:
            log(f"Ошибка синхронизации в presets/: {e}", "ERROR")
            import traceback
            log(traceback.format_exc(), "DEBUG")

    def _open_in_notepad(self):
        """Открывает файл в блокноте"""
        try:
            # Сначала сохраняем текущие изменения
            if self._save_timer.isActive():
                self._save_timer.stop()
                self._save_file()

            subprocess.Popen(['notepad.exe', self._preset_path])
            log(f"Открыт {os.path.basename(self._preset_path)} в блокноте", "DEBUG")

        except Exception as e:
            log(f"Ошибка открытия в блокноте: {e}", "ERROR")
            self._update_status(f"Ошибка открытия: {e}")

    def _update_status(self, text: str):
        """Обновляет статус-бар (статус файла + процесса)"""
        self._file_status = text
        self._refresh_status_label()

    def _expected_process_name(self) -> str:
        method = get_strategy_launch_method()
        return "winws2.exe" if method in ZAPRET2_MODES else "winws.exe"

    def _connect_process_monitor(self) -> None:
        if self._process_monitor_connected:
            return
        try:
            app = getattr(self, "parent_app", None)
            monitor = getattr(app, "process_monitor", None) if app else None
            if monitor is None:
                return
            if hasattr(monitor, "processDetailsChanged"):
                monitor.processDetailsChanged.connect(self._on_process_details_changed)
            elif hasattr(monitor, "processStatusChanged"):
                monitor.processStatusChanged.connect(self._on_process_running_changed)
            self._process_monitor_connected = True
        except Exception as e:
            log(f"PresetConfigPage: ошибка подключения к process_monitor: {e}", "DEBUG")

    def _sync_process_status_from_cache(self) -> None:
        """Быстро синхронизирует статус из кэша (без psutil в UI-потоке)."""
        try:
            app = getattr(self, "parent_app", None)
            details = getattr(app, "process_details", None) if app else None
            expected = self._expected_process_name()
            self._process_status = format_expected_process_status(expected, details)
            self._refresh_status_label()
        except Exception as e:
            self._process_status = f"❓ Ошибка: {e}"
            self._refresh_status_label()

    def _on_process_details_changed(self, details: dict) -> None:
        try:
            expected = self._expected_process_name()
            self._process_status = format_expected_process_status(expected, details)
            self._refresh_status_label()
        except Exception as e:
            log(f"PresetConfigPage._on_process_details_changed error: {e}", "DEBUG")

    def _on_process_running_changed(self, is_running: bool) -> None:
        """Fallback, если доступен только bool-сигнал."""
        expected = self._expected_process_name()
        if is_running:
            self._process_status = f"✅ {expected} (запущен)"
        else:
            self._process_status = f"⚫ {expected} не запущен"
        self._refresh_status_label()

    def _refresh_status_label(self):
        """Обновляет лейбл статуса с обоими статусами"""
        file_status = getattr(self, '_file_status', '')
        process_status = getattr(self, '_process_status', '⏳ Проверка...')
        self.status_label.setText(f"{file_status}  •  {process_status}")

    def _on_timer_tick(self):
        """Обработчик таймера - проверяет изменения файла"""
        self._check_file_changed()

    def _check_file_changed(self):
        """Проверяет изменился ли файл извне и перезагружает если да"""
        try:
            if not os.path.exists(self._preset_path):
                return

            current_mtime = os.path.getmtime(self._preset_path)
            if self._last_mtime and current_mtime != self._last_mtime:
                # Файл изменился извне - перезагружаем
                self._load_file()
                self._update_status("Обновлено")
            self._last_mtime = current_mtime
        except Exception:
            pass

    def showEvent(self, event):  # noqa: N802 (Qt override)
        super().showEvent(event)

        try:
            spontaneous = bool(event.spontaneous())
        except Exception:
            spontaneous = False

        if (not spontaneous) and (not self._loaded_once):
            self._load_file()
            self._loaded_once = True

        self._connect_process_monitor()
        if not self._tick_timer.isActive():
            self._tick_timer.start(1000)
        self._sync_process_status_from_cache()
        self._check_file_changed()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._tick_timer.isActive():
            self._tick_timer.stop()
