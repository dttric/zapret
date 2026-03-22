"""
Редактор конфига preset-zapret2.txt - WinUI Fluent Design
Поддержка hot-reload через автосохранение с debounce
"""

import os
import subprocess

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QWidget, QGraphicsDropShadowEffect
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QEvent
from PyQt6.QtGui import QColor, QFont

from qfluentwidgets import (
    BodyLabel, CaptionLabel, StrongBodyLabel,
    PushButton, TransparentToolButton, FluentIcon,
    PlainTextEdit, SimpleCardWidget,
)

from log import log
from ui.theme import get_theme_tokens
from ui.theme_semantic import get_semantic_palette


class PresetEditorDialog(QDialog):
    """Редактор конфига preset-zapret2.txt - WinUI Fluent Design"""

    AUTOSAVE_DELAY_MS = 1000

    def __init__(self, preset_path: str, parent=None):
        super().__init__(parent)

        self.preset_path = preset_path
        self._has_unsaved_changes = False
        self._is_loading = False

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_file)

        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(False)

        self.opacity_animation = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_animation.setDuration(150)
        self.opacity_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._init_ui()
        self._load_file()
        self.setWindowOpacity(0.0)

    def _init_ui(self):
        """Инициализация интерфейса"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # Контейнер — нативная WinUI карточка
        self.container = SimpleCardWidget()
        self.container.setObjectName("fluentContainer")

        # Тень
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(0, 8)
        self.container.setGraphicsEffect(shadow)

        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(16, 12, 16, 16)
        container_layout.setSpacing(12)

        # === Заголовок ===
        header = QHBoxLayout()
        header.setSpacing(8)

        self.title_label = StrongBodyLabel("Редактор конфига")
        header.addWidget(self.title_label, 1)

        self.close_btn = TransparentToolButton(FluentIcon.CLOSE)
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.clicked.connect(self._close_dialog)
        header.addWidget(self.close_btn)
        container_layout.addLayout(header)

        # === Путь к файлу ===
        self.path_label = CaptionLabel(self.preset_path)
        self.path_label.setWordWrap(True)
        container_layout.addWidget(self.path_label)

        # === Текстовое поле ===
        self.text_edit = PlainTextEdit()

        font = QFont("Cascadia Code", 12)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.text_edit.setFont(font)
        self.text_edit.setMinimumSize(580, 380)
        self.text_edit.textChanged.connect(self._on_text_changed)

        container_layout.addWidget(self.text_edit)

        # === Статус-бар ===
        status_layout = QHBoxLayout()
        status_layout.setSpacing(8)

        self.status_label = CaptionLabel("Загружено")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        container_layout.addLayout(status_layout)

        # === Кнопки ===
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(8)

        self.reload_btn = PushButton()
        self.reload_btn.setText("Перезагрузить")
        self.reload_btn.setFixedHeight(32)
        self.reload_btn.clicked.connect(self._load_file)
        buttons_layout.addWidget(self.reload_btn)

        buttons_layout.addStretch()

        self.open_btn = PushButton()
        self.open_btn.setText("Открыть в редакторе")
        self.open_btn.setFixedHeight(32)
        self.open_btn.clicked.connect(self._open_in_editor)
        buttons_layout.addWidget(self.open_btn)

        container_layout.addLayout(buttons_layout)

        # === Подсказка ===
        self.hint_label = CaptionLabel("Изменения сохраняются автоматически • ESC — закрыть")
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(self.hint_label)

        main_layout.addWidget(self.container)
        self.setFixedSize(620, 520)

    def _load_file(self):
        self._is_loading = True
        try:
            if os.path.exists(self.preset_path):
                with open(self.preset_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.text_edit.setPlainText(content)
                self._update_status("Загружено", success=True)
                log(f"PresetEditorDialog: загружен файл {self.preset_path}")
            else:
                self.text_edit.setPlainText("")
                self._update_status("Файл не найден", error=True)
                log(f"PresetEditorDialog: файл не найден {self.preset_path}", "WARNING")
        except Exception as e:
            self._update_status(f"Ошибка загрузки: {e}", error=True)
            log(f"PresetEditorDialog: ошибка загрузки {e}", "ERROR")
        finally:
            self._is_loading = False
            self._has_unsaved_changes = False

    def _save_file(self):
        try:
            content = self.text_edit.toPlainText()

            dir_path = os.path.dirname(self.preset_path)
            if dir_path and not os.path.exists(dir_path):
                os.makedirs(dir_path)

            with open(self.preset_path, 'w', encoding='utf-8') as f:
                f.write(content)

            self._has_unsaved_changes = False
            self._update_status("Сохранено", success=True)
            log(f"PresetEditorDialog: файл сохранён {self.preset_path}")
        except Exception as e:
            self._update_status(f"Ошибка сохранения: {e}", error=True)
            log(f"PresetEditorDialog: ошибка сохранения {e}", "ERROR")

    def _on_text_changed(self):
        if self._is_loading:
            return
        self._has_unsaved_changes = True
        self._update_status("Изменено...", pending=True)
        self._save_timer.stop()
        self._save_timer.start(self.AUTOSAVE_DELAY_MS)

    def _update_status(self, text: str, success: bool = False, error: bool = False, pending: bool = False):
        tokens = get_theme_tokens()
        semantic = get_semantic_palette(tokens.theme_name)
        if error:
            color = semantic.error
        elif success:
            color = semantic.success
        elif pending:
            color = semantic.warning
        else:
            color = tokens.fg_muted

        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"QLabel{{color:{color};font-size:11px;}}")

    def _open_in_editor(self):
        try:
            if self._has_unsaved_changes:
                self._save_file()
            if os.name == 'nt':
                os.startfile(self.preset_path)
            else:
                subprocess.run(['xdg-open', self.preset_path])
            log(f"PresetEditorDialog: открыт в редакторе {self.preset_path}")
        except Exception as e:
            self._update_status(f"Ошибка открытия: {e}", error=True)
            log(f"PresetEditorDialog: ошибка открытия в редакторе {e}", "ERROR")

    def show_animated(self, pos=None):
        if pos:
            self.move(pos)
        self.show()
        self.opacity_animation.setStartValue(0.0)
        self.opacity_animation.setEndValue(1.0)
        self.opacity_animation.start()

    def _close_dialog(self):
        if self._has_unsaved_changes:
            self._save_timer.stop()
            self._save_file()
        self._hide_animated()

    def _hide_animated(self):
        self.opacity_animation.setStartValue(1.0)
        self.opacity_animation.setEndValue(0.0)
        self.opacity_animation.finished.connect(self._on_hide_finished)
        self.opacity_animation.start()

    def _on_hide_finished(self):
        try:
            self.opacity_animation.finished.disconnect(self._on_hide_finished)
        except Exception:
            pass
        self.hide()
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._close_dialog()
        elif event.key() == Qt.Key.Key_S and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self._save_timer.stop()
            self._save_file()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        if self._has_unsaved_changes:
            self._save_timer.stop()
            self._save_file()
        event.accept()