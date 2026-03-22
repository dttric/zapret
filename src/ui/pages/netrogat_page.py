# ui/pages/netrogat_page.py
"""Страница управления пользовательскими исключениями netrogat.user.txt"""

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
)

try:
    from qfluentwidgets import LineEdit, MessageBox, InfoBar
    _HAS_FLUENT = True
except ImportError:
    LineEdit = QLineEdit
    MessageBox = None
    InfoBar = None
    _HAS_FLUENT = False

try:
    from qfluentwidgets import StrongBodyLabel, BodyLabel, CaptionLabel
    _HAS_FLUENT_LABELS = True
except ImportError:
    StrongBodyLabel = QLabel; BodyLabel = QLabel; CaptionLabel = QLabel
    _HAS_FLUENT_LABELS = False

from .base_page import BasePage, ScrollBlockingPlainTextEdit
from ui.compat_widgets import SettingsCard, ActionButton
from ui.theme import get_theme_tokens
from ui.text_catalog import tr as tr_catalog
from log import log
from utils.netrogat_manager import (
    NETROGAT_USER_PATH,
    ensure_netrogat_base_defaults,
    ensure_netrogat_user_file,
    get_netrogat_base_set,
    load_netrogat,
    save_netrogat,
    _normalize_domain,
)
import os
import re

def split_domains(text: str) -> list[str]:
    """Разделяет домены по пробелам и склеенные."""
    parts = re.split(r'[\s,;]+', text)
    result = []
    for part in parts:
        part = part.strip().lower()
        if not part or part.startswith('#'):
            if part:
                result.append(part)
            continue
        separated = _split_glued_domains(part)
        result.extend(separated)
    return result

def _split_glued_domains(text: str) -> list[str]:
    """Разделяет склеенные домены типа vk.comyoutube.com"""
    if not text or len(text) < 5:
        return [text] if text else []
    
    # Паттерн: TLD за которым идёт начало нового домена (буквы + точка)
    pattern = r'(\.(com|ru|org|net|io|me|by|uk|de|fr|it|es|nl|pl|ua|kz|su|co|tv|cc|to|ai|gg|info|biz|xyz|dev|app|pro|online|store|cloud|shop|blog|tech|site|рф))([a-z][a-z0-9-]*\.)'
    
    result = []
    remaining = text
    
    while remaining:
        match = re.search(pattern, remaining, re.IGNORECASE)
        if match:
            end_of_first = match.start() + len(match.group(1))
            first_domain = remaining[:end_of_first]
            result.append(first_domain)
            remaining = remaining[end_of_first:]
        else:
            if remaining:
                result.append(remaining)
            break
    
    return result if result else [text]


class NetrogatPage(BasePage):
    """Страница пользовательских исключений netrogat.user.txt"""

    data_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(
            "Исключения",
            "Управление пользовательским списком netrogat.user.txt. Итоговый netrogat.txt собирается автоматически.",
            parent,
            title_key="page.netrogat.title",
            subtitle_key="page.netrogat.subtitle",
        )
        self._base_domains_set_cache: set[str] | None = None
        self._desc_label = None
        self._add_card = None
        self._actions_card = None
        self._editor_card = None
        self._hint_label = None
        self._add_defaults_btn = None
        self._open_btn = None
        self._open_final_btn = None
        self._clear_btn = None
        self._status_state = {
            "total": 0,
            "base": 0,
            "user": 0,
            "saved": False,
        }
        self._build_ui()
        QTimer.singleShot(100, self._load)

    def _tr(self, key: str, default: str, **kwargs) -> str:
        text = tr_catalog(key, language=self._ui_language, default=default)
        if kwargs:
            try:
                return text.format(**kwargs)
            except Exception:
                return text
        return text

    def _build_ui(self):
        tokens = get_theme_tokens()
        # Описание
        desc_card = SettingsCard()
        desc = CaptionLabel(
            self._tr(
                "page.netrogat.description",
                "Редактируйте только netrogat.user.txt.\n"
                "Системная база хранится в netrogat.base.txt и автоматически объединяется в netrogat.txt.",
            )
        )
        self._desc_label = desc
        desc.setStyleSheet(f"color: {tokens.fg_muted};")
        desc.setWordWrap(True)
        desc_card.add_widget(desc)
        self.layout.addWidget(desc_card)

        # Добавление домена
        add_card = SettingsCard(self._tr("page.netrogat.section.add", "Добавить домен"))
        self._add_card = add_card
        add_layout = QHBoxLayout()
        add_layout.setSpacing(8)

        self.input = LineEdit()
        self.input.setPlaceholderText(
            self._tr(
                "page.netrogat.input.placeholder",
                "Например: example.com, site.com или через пробел",
            )
        )
        self.input.returnPressed.connect(self._add)
        add_layout.addWidget(self.input, 1)

        self.add_btn = ActionButton(self._tr("page.netrogat.button.add", "Добавить"), "fa5s.plus", accent=True)
        self.add_btn.setFixedHeight(38)
        self.add_btn.clicked.connect(self._add)
        add_layout.addWidget(self.add_btn)

        add_card.add_layout(add_layout)
        self.layout.addWidget(add_card)

        # Действия
        actions_card = SettingsCard(self._tr("page.netrogat.section.actions", "Действия"))
        self._actions_card = actions_card
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(8)

        self._add_defaults_btn = ActionButton(
            self._tr("page.netrogat.button.add_missing", "Добавить недостающие"),
            "fa5s.plus-circle",
        )
        self._add_defaults_btn.setFixedHeight(36)
        self._add_defaults_btn.clicked.connect(self._add_missing_defaults)
        actions_layout.addWidget(self._add_defaults_btn)

        self._open_btn = ActionButton(self._tr("page.netrogat.button.open_file", "Открыть файл"), "fa5s.external-link-alt")
        self._open_btn.setFixedHeight(36)
        self._open_btn.clicked.connect(self._open_file)
        actions_layout.addWidget(self._open_btn)

        self._open_final_btn = ActionButton(
            self._tr("page.netrogat.button.open_final", "Открыть итоговый"),
            "fa5s.file-alt",
        )
        self._open_final_btn.setFixedHeight(36)
        self._open_final_btn.clicked.connect(self._open_final_file)
        actions_layout.addWidget(self._open_final_btn)

        self._clear_btn = ActionButton(self._tr("page.netrogat.button.clear_all", "Очистить всё"), "fa5s.trash-alt")
        self._clear_btn.setFixedHeight(36)
        self._clear_btn.clicked.connect(self._clear_all)
        actions_layout.addWidget(self._clear_btn)

        actions_layout.addStretch()
        actions_card.add_layout(actions_layout)
        self.layout.addWidget(actions_card)

        # Текстовый редактор (вместо списка)
        editor_card = SettingsCard(self._tr("page.netrogat.section.editor", "netrogat.user.txt (редактор)"))
        self._editor_card = editor_card
        editor_layout = QVBoxLayout()
        editor_layout.setSpacing(8)

        self.text_edit = ScrollBlockingPlainTextEdit()
        self.text_edit.setPlaceholderText(
            self._tr(
                "page.netrogat.editor.placeholder",
                "Домены по одному на строку:\n"
                "gosuslugi.ru\n"
                "vk.com\n\n"
                "Комментарии начинаются с #",
            )
        )
        self.text_edit.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {tokens.surface_bg};
                border: 1px solid {tokens.surface_border};
                border-radius: 8px;
                padding: 12px;
                color: {tokens.fg};
                font-family: Consolas, 'Courier New', monospace;
                font-size: 13px;
            }}
            QPlainTextEdit:focus {{
                border: 1px solid {tokens.accent_hex};
            }}
        """)
        self.text_edit.setMinimumHeight(350)

        # Автосохранение
        self._save_timer = QTimer()
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._auto_save)
        self.text_edit.textChanged.connect(self._on_text_changed)

        editor_layout.addWidget(self.text_edit)

        self._hint_label = CaptionLabel(
            self._tr("page.netrogat.hint.autosave", "💡 Изменения сохраняются автоматически через 500мс")
        )
        self._hint_label.setStyleSheet(f"color: {tokens.fg_faint};")
        editor_layout.addWidget(self._hint_label)

        editor_card.add_layout(editor_layout)
        self.layout.addWidget(editor_card)

        self.status_label = CaptionLabel()
        self.status_label.setStyleSheet(f"color: {tokens.fg_faint};")
        self.layout.addWidget(self.status_label)

    def _load(self):
        ensure_netrogat_user_file()
        self._base_domains_set_cache = get_netrogat_base_set()
        domains = load_netrogat()
        # Блокируем сигнал чтобы не срабатывало автосохранение
        self.text_edit.blockSignals(True)
        self.text_edit.setPlainText('\n'.join(domains))
        self.text_edit.blockSignals(False)
        self._status_state["saved"] = False
        self._update_status()
        log(f"Загружено {len(domains)} строк из netrogat.user.txt", "INFO")

    def _render_status_label(self):
        summary = self._tr(
            "page.netrogat.status.summary",
            "📊 Доменов: {total} (база: {base}, пользовательские: {user})",
            total=self._status_state["total"],
            base=self._status_state["base"],
            user=self._status_state["user"],
        )
        if self._status_state.get("saved"):
            summary += self._tr("page.netrogat.status.saved_suffix", " • ✅ Сохранено")
        self.status_label.setText(summary)

    def set_ui_language(self, language: str) -> None:
        super().set_ui_language(language)

        if self._desc_label is not None:
            self._desc_label.setText(
                self._tr(
                    "page.netrogat.description",
                    "Редактируйте только netrogat.user.txt.\n"
                    "Системная база хранится в netrogat.base.txt и автоматически объединяется в netrogat.txt.",
                )
            )
        if self._add_card is not None:
            self._add_card.set_title(self._tr("page.netrogat.section.add", "Добавить домен"))
        if self._actions_card is not None:
            self._actions_card.set_title(self._tr("page.netrogat.section.actions", "Действия"))
        if self._editor_card is not None:
            self._editor_card.set_title(self._tr("page.netrogat.section.editor", "netrogat.user.txt (редактор)"))

        self.input.setPlaceholderText(
            self._tr(
                "page.netrogat.input.placeholder",
                "Например: example.com, site.com или через пробел",
            )
        )
        self.add_btn.setText(self._tr("page.netrogat.button.add", "Добавить"))
        if self._add_defaults_btn is not None:
            self._add_defaults_btn.setText(self._tr("page.netrogat.button.add_missing", "Добавить недостающие"))
        if self._open_btn is not None:
            self._open_btn.setText(self._tr("page.netrogat.button.open_file", "Открыть файл"))
        if self._open_final_btn is not None:
            self._open_final_btn.setText(self._tr("page.netrogat.button.open_final", "Открыть итоговый"))
        if self._clear_btn is not None:
            self._clear_btn.setText(self._tr("page.netrogat.button.clear_all", "Очистить всё"))

        self.text_edit.setPlaceholderText(
            self._tr(
                "page.netrogat.editor.placeholder",
                "Домены по одному на строку:\n"
                "gosuslugi.ru\n"
                "vk.com\n\n"
                "Комментарии начинаются с #",
            )
        )
        if self._hint_label is not None:
            self._hint_label.setText(
                self._tr("page.netrogat.hint.autosave", "💡 Изменения сохраняются автоматически через 500мс")
            )

        self._render_status_label()

    def _on_text_changed(self):
        self._save_timer.start(500)
        self._status_state["saved"] = False
        self._update_status()

    def _auto_save(self):
        self._save()
        self._status_state["saved"] = True
        self._render_status_label()

    def _save(self):
        text = self.text_edit.toPlainText()
        domains = []
        normalized_lines = []  # Для обновления UI
        
        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue
            # Сохраняем комментарии как есть
            if line.startswith('#'):
                domains.append(line)
                normalized_lines.append(line)
                continue
            
            # Разделяем склеенные домены (vk.comyoutube.com -> vk.com, youtube.com)
            separated = split_domains(line)
            
            for item in separated:
                # Нормализуем каждый домен
                norm = _normalize_domain(item)
                if norm:
                    if norm not in domains:
                        domains.append(norm)
                        normalized_lines.append(norm)
                else:
                    # Невалидная строка - оставляем как есть
                    normalized_lines.append(item)
        
        if save_netrogat(domains):
            # Обновляем UI - заменяем URL на домены
            new_text = '\n'.join(normalized_lines)
            if new_text != text:
                cursor = self.text_edit.textCursor()
                pos = cursor.position()
                
                self.text_edit.blockSignals(True)
                self.text_edit.setPlainText(new_text)
                
                # Восстанавливаем позицию курсора
                cursor = self.text_edit.textCursor()
                cursor.setPosition(min(pos, len(new_text)))
                self.text_edit.setTextCursor(cursor)
                self.text_edit.blockSignals(False)
            
            self.data_changed.emit()

    def _update_status(self):
        text = self.text_edit.toPlainText()
        lines = [l.strip() for l in text.split('\n') if l.strip() and not l.strip().startswith('#')]

        base_set = self._get_base_domains_set()
        valid_entries: set[str] = set()
        for line in lines:
            for item in split_domains(line):
                norm = _normalize_domain(item)
                if norm:
                    valid_entries.add(norm)

        user_count = len({d for d in valid_entries if d not in base_set})
        base_count = len(base_set)
        total_count = len(base_set.union(valid_entries))
        self._status_state["total"] = total_count
        self._status_state["base"] = base_count
        self._status_state["user"] = user_count
        self._render_status_label()

    def _get_base_domains_set(self) -> set[str]:
        if self._base_domains_set_cache is not None:
            return self._base_domains_set_cache

        try:
            self._base_domains_set_cache = get_netrogat_base_set()
        except Exception:
            self._base_domains_set_cache = set()
        return self._base_domains_set_cache

    def _add(self):
        raw = self.input.text().strip()
        if not raw:
            return

        # Разделяем на несколько доменов
        parts = split_domains(raw)
        if not parts:
            if InfoBar:
                InfoBar.warning(
                    title=self._tr("common.error.title", "Ошибка"),
                    content=self._tr("page.netrogat.error.parse_domain", "Не удалось распознать домен."),
                    parent=self.window(),
                )
            return

        # Проверяем дубликаты
        current = self.text_edit.toPlainText()
        current_domains = [l.strip().lower() for l in current.split('\n') if l.strip() and not l.strip().startswith('#')]

        added = []
        skipped = []
        invalid = []

        for part in parts:
            if part.startswith('#'):
                continue
            norm = _normalize_domain(part)
            if not norm:
                invalid.append(part)
                continue
            if norm.lower() in current_domains or norm.lower() in [a.lower() for a in added]:
                skipped.append(norm)
                continue
            added.append(norm)

        if not added and not skipped and invalid:
            if InfoBar:
                InfoBar.warning(
                    title=self._tr("common.error.title", "Ошибка"),
                    content=self._tr("page.netrogat.error.parse_domains", "Не удалось распознать домены."),
                    parent=self.window(),
                )
            return

        if not added and skipped:
            if InfoBar:
                if len(skipped) == 1:
                    InfoBar.info(
                        title=self._tr("page.netrogat.infobar.info_title", "Информация"),
                        content=self._tr(
                            "page.netrogat.info.already_exists_one",
                            "Домен уже есть: {domain}",
                            domain=skipped[0],
                        ),
                        parent=self.window(),
                    )
                else:
                    InfoBar.info(
                        title=self._tr("page.netrogat.infobar.info_title", "Информация"),
                        content=self._tr(
                            "page.netrogat.info.already_exists_many",
                            "Все домены уже есть ({count})",
                            count=len(skipped),
                        ),
                        parent=self.window(),
                    )
            return

        # Добавляем в конец
        if current and not current.endswith('\n'):
            current += '\n'
        current += '\n'.join(added)

        self.text_edit.setPlainText(current)
        self.input.clear()

        # Показываем результат если были пропущенные
        if skipped:
            if InfoBar:
                InfoBar.success(
                    title=self._tr("page.netrogat.infobar.added_title", "Добавлено"),
                    content=self._tr(
                        "page.netrogat.info.added_with_skipped",
                        "Добавлено доменов. Пропущено уже существующих: {count}",
                        count=len(skipped),
                    ),
                    parent=self.window(),
                )

    def _clear_all(self):
        text = self.text_edit.toPlainText().strip()
        if not text:
            return
        if MessageBox:
            box = MessageBox(
                self._tr("page.netrogat.dialog.clear.title", "Очистить всё"),
                self._tr("page.netrogat.dialog.clear.body", "Удалить все домены?"),
                self.window(),
            )
            if box.exec():
                self.text_edit.clear()
                log("Очистили netrogat.user.txt", "INFO")
        else:
            self.text_edit.clear()
            log("Очистили netrogat.user.txt", "INFO")

    def _open_file(self):
        try:
            import subprocess

            # Сохраняем перед открытием
            self._save()
            ensure_netrogat_user_file()

            if NETROGAT_USER_PATH and os.path.exists(NETROGAT_USER_PATH):
                subprocess.run(["explorer", "/select,", NETROGAT_USER_PATH])
            else:
                from config import LISTS_FOLDER
                subprocess.run(["explorer", LISTS_FOLDER])
        except Exception as e:
            log(f"Ошибка открытия netrogat.user.txt: {e}", "ERROR")
            if InfoBar:
                InfoBar.warning(
                    title=self._tr("common.error.title", "Ошибка"),
                    content=self._tr("page.netrogat.error.open_file", "Не удалось открыть: {error}", error=e),
                    parent=self.window(),
                )

    def _open_final_file(self):
        try:
            import subprocess
            from config import LISTS_FOLDER, NETROGAT_PATH
            from utils.netrogat_manager import ensure_netrogat_exists

            # Сохраняем user и пересобираем итог перед открытием
            self._save()
            ensure_netrogat_exists()

            if NETROGAT_PATH and os.path.exists(NETROGAT_PATH):
                subprocess.run(["explorer", "/select,", NETROGAT_PATH])
            else:
                subprocess.run(["explorer", LISTS_FOLDER])
        except Exception as e:
            log(f"Ошибка открытия итогового netrogat.txt: {e}", "ERROR")
            if InfoBar:
                InfoBar.warning(
                    title=self._tr("common.error.title", "Ошибка"),
                    content=self._tr(
                        "page.netrogat.error.open_final_file",
                        "Не удалось открыть итоговый файл: {error}",
                        error=e,
                    ),
                    parent=self.window(),
                )

    def _add_missing_defaults(self):
        self._save()
        added = ensure_netrogat_base_defaults()
        self._base_domains_set_cache = None
        if added == 0:
            if InfoBar:
                InfoBar.success(
                    title=self._tr("page.netrogat.infobar.done_title", "Готово"),
                    content=self._tr(
                        "page.netrogat.info.defaults_already_present",
                        "Системная база уже содержит все домены по умолчанию.",
                    ),
                    parent=self.window(),
                )
            return

        self._update_status()
        if InfoBar:
            InfoBar.success(
                title=self._tr("page.netrogat.infobar.done_title", "Готово"),
                content=self._tr(
                    "page.netrogat.info.defaults_restored",
                    "Восстановлено доменов в системной базе: {count}",
                    count=added,
                ),
                parent=self.window(),
            )
