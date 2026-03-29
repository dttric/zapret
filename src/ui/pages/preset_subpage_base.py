from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget, QFileDialog

from ui.pages.base_page import BasePage

try:
    from qfluentwidgets import (
        Action,
        BodyLabel,
        CaptionLabel,
        FluentIcon,
        InfoBar,
        LineEdit,
        MessageBox,
        MessageBoxBase,
        PlainTextEdit,
        PushButton,
        RoundMenu,
        SimpleCardWidget,
        StrongBodyLabel,
        TransparentPushButton,
        TransparentToolButton,
    )
except ImportError:
    from PyQt6.QtWidgets import (
        QLabel as BodyLabel,
        QLabel as CaptionLabel,
        QLabel as StrongBodyLabel,
        QLineEdit as LineEdit,
        QPlainTextEdit as PlainTextEdit,
        QPushButton as PushButton,
        QPushButton as TransparentPushButton,
        QPushButton as TransparentToolButton,
        QFrame as SimpleCardWidget,
    )

    MessageBox = None
    MessageBoxBase = object
    RoundMenu = None
    Action = None
    FluentIcon = None
    InfoBar = None


def _fluent_icon(name: str):
    if FluentIcon is None:
        return None
    return getattr(FluentIcon, name, None)


def _make_menu_action(text: str, *, icon=None, parent=None):
    if Action is not None:
        if icon is not None:
            try:
                return Action(icon, text, parent)
            except TypeError:
                pass
        try:
            action = Action(text, parent)
        except TypeError:
            try:
                action = Action(text)
            except TypeError:
                action = None
        if action is not None:
            try:
                if icon is not None and hasattr(action, "setIcon"):
                    action.setIcon(icon)
            except Exception:
                pass
            return action

    action = QAction(text, parent)
    try:
        if icon is not None:
            action.setIcon(icon)
    except Exception:
        pass
    return action


class _RenameDialog(MessageBoxBase):
    def __init__(self, current_name: str, existing_names: list[str], parent=None):
        if parent is not None and not parent.isWindow():
            parent = parent.window()
        super().__init__(parent)
        self._current_name = str(current_name or "")
        self._existing_names = [n for n in existing_names if n != self._current_name]

        self.titleLabel = StrongBodyLabel("Переименовать", self.widget)
        self.subtitleLabel = BodyLabel(
            "Имя пресета отображается в списке и используется для переключения.",
            self.widget,
        )
        self.subtitleLabel.setWordWrap(True)

        self.nameEdit = LineEdit(self.widget)
        self.nameEdit.setText(self._current_name)
        self.nameEdit.selectAll()
        self.nameEdit.setClearButtonEnabled(True)

        self.warningLabel = CaptionLabel("", self.widget)
        self.warningLabel.hide()

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.subtitleLabel)
        self.viewLayout.addWidget(self.nameEdit)
        self.viewLayout.addWidget(self.warningLabel)

        self.yesButton.setText("Переименовать")
        self.cancelButton.setText("Отмена")
        self.widget.setMinimumWidth(420)

    def validate(self) -> bool:
        name = self.nameEdit.text().strip()
        if not name:
            self.warningLabel.setText("Введите название.")
            self.warningLabel.show()
            return False
        self.warningLabel.hide()
        return True


class PresetSubpageBase(BasePage):
    back_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(self._default_title(), "", parent)
        self._preset_name = ""
        self._preset_file_name = ""
        self._preset_path: Path | None = None
        self._is_loading = False
        self._direct_facade = None

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_file)

        self._build_ui()

    def _default_title(self) -> str:
        raise NotImplementedError

    def _get_preset_path(self, name: str) -> Path:
        raise NotImplementedError

    def _direct_launch_method(self) -> str | None:
        return None

    def _preset_hierarchy_scope_key(self) -> str | None:
        method = self._direct_launch_method()
        if method == "direct_zapret2":
            return "preset_zapret2"
        if method == "direct_zapret1":
            return "preset_zapret1"
        return None

    def _get_direct_facade(self):
        method = self._direct_launch_method()
        if not method:
            return None
        if self._direct_facade is None:
            from core.presets.direct_facade import DirectPresetFacade

            self._direct_facade = DirectPresetFacade.from_launch_method(method)
        return self._direct_facade

    def _is_orchestra_preset_backend(self) -> bool:
        return self._direct_launch_method() is None and self._preset_hierarchy_scope_key() == "preset_orchestra_zapret2"

    def _get_orchestra_preset_name(self) -> str:
        candidate = str(self._preset_name or "").strip()
        if candidate:
            return candidate
        return Path(str(self._preset_file_name or "").strip()).stem

    def _show_success(self, text: str) -> None:
        if InfoBar is not None:
            try:
                InfoBar.success(title="Успех", content=text, parent=self.window())
                return
            except Exception:
                pass

    def _show_error(self, text: str) -> None:
        if InfoBar is not None:
            try:
                InfoBar.error(title="Ошибка", content=text, parent=self.window())
                return
            except Exception:
                pass

    def _is_current_builtin(self) -> bool:
        if self._is_orchestra_preset_backend():
            return False
        facade = self._get_direct_facade()
        if facade is None:
            return False
        try:
            if not self._preset_file_name:
                return False
            manifest = facade.get_manifest_by_file_name(self._preset_file_name)
            return bool(manifest is not None and str(manifest.kind or "").strip().lower() == "builtin")
        except Exception:
            return False

    def _build_ui(self) -> None:
        top_row = QWidget(self)
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        self.backButton = TransparentPushButton(self)
        self.backButton.setText("Назад к списку")
        self.backButton.setIcon(_fluent_icon("LEFT_ARROW"))
        self.backButton.clicked.connect(self.back_clicked.emit)
        top_layout.addWidget(self.backButton, 0)
        top_layout.addStretch(1)

        self.menuButton = TransparentToolButton(_fluent_icon("MENU"), self)
        self.menuButton.clicked.connect(self._open_menu)
        top_layout.addWidget(self.menuButton, 0)
        self.add_widget(top_row)

        self.summaryCard = SimpleCardWidget(self)
        summary_layout = QVBoxLayout(self.summaryCard)
        summary_layout.setContentsMargins(16, 16, 16, 16)
        summary_layout.setSpacing(8)

        self.statusLabel = StrongBodyLabel("Пресет", self.summaryCard)
        self.metaLabel = CaptionLabel("", self.summaryCard)
        self.metaLabel.setWordWrap(True)
        self.pathLabel = CaptionLabel("", self.summaryCard)
        self.pathLabel.setWordWrap(True)

        summary_layout.addWidget(self.statusLabel)
        summary_layout.addWidget(self.metaLabel)
        summary_layout.addWidget(self.pathLabel)
        self.add_widget(self.summaryCard)

        actions = QWidget(self)
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)

        self.activateButton = PushButton("Сделать активным", self)
        self.activateButton.setIcon(_fluent_icon("ACCEPT"))
        self.activateButton.clicked.connect(self._activate_preset)
        actions_layout.addWidget(self.activateButton)

        self.openExternalButton = PushButton("Открыть в редакторе", self)
        self.openExternalButton.setIcon(_fluent_icon("FOLDER"))
        self.openExternalButton.clicked.connect(self._open_external)
        actions_layout.addWidget(self.openExternalButton)
        actions_layout.addStretch(1)
        self.add_widget(actions)

        self.editor = PlainTextEdit(self)
        self.editor.textChanged.connect(self._on_text_changed)
        self.add_widget(self.editor, 1)

        self.footerLabel = CaptionLabel("", self)
        self.add_widget(self.footerLabel)

    def set_preset_file_name(self, file_name: str) -> None:
        self._flush_pending_save()
        self._preset_file_name = str(file_name or "").strip()
        self._preset_name = Path(self._preset_file_name).stem if self._preset_file_name else ""
        facade = self._get_direct_facade()
        if facade is not None and self._preset_file_name:
            try:
                manifest = facade.get_manifest_by_file_name(self._preset_file_name)
                if manifest is not None:
                    self._preset_name = manifest.name
                    self._preset_file_name = manifest.file_name
                self._preset_path = facade.get_source_path_by_file_name(self._preset_file_name)
            except Exception:
                self._preset_path = self._get_preset_path(self._preset_name)
        else:
            self._preset_path = self._get_preset_path(self._preset_name)
        self._load_file()
        self._refresh_header()

    def _flush_pending_save(self) -> None:
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save_file()

    def _refresh_header(self) -> None:
        self.title_label.setText(self._preset_name or self._default_title())
        active_name = self._current_selected_name()
        active_file_name = self._current_selected_file_name()
        is_active = False
        if self._preset_file_name:
            is_active = active_file_name.lower() == self._preset_file_name.lower()
        elif self._preset_name:
            is_active = active_name.lower() == self._preset_name.lower()
        facade = self._get_direct_facade()
        origin = "builtin" if self._is_current_builtin() else "user"
        if facade is not None and self._preset_file_name:
            try:
                manifest = facade.get_manifest_by_file_name(self._preset_file_name)
                if manifest is not None:
                    kind = str(manifest.kind or "").strip().lower()
                    if kind in {"builtin", "imported", "user"}:
                        origin = kind
            except Exception:
                pass

        if is_active and origin == "builtin":
            status = "Активный встроенный пресет"
        elif is_active and origin == "imported":
            status = "Активный импортированный пресет"
        elif is_active:
            status = "Активный пресет"
        elif origin == "builtin":
            status = "Встроенный пресет"
        elif origin == "imported":
            status = "Импортированный пресет"
        else:
            status = "Пользовательский пресет"
        self.statusLabel.setText(status)
        self.activateButton.setVisible(not is_active)
        self.metaLabel.setText(f"Имя: {self._preset_name}")
        self.pathLabel.setText(str(self._preset_path or ""))

    def _load_file(self) -> None:
        self._is_loading = True
        try:
            if self._preset_path is None or not self._preset_path.exists():
                self.editor.setPlainText("")
                self._set_footer("Файл не найден")
                return
            self.editor.setPlainText(self._preset_path.read_text(encoding="utf-8", errors="replace"))
            self._set_footer("Загружено")
        except Exception as e:
            self._set_footer(f"Ошибка загрузки: {e}")
        finally:
            self._is_loading = False

    def _on_text_changed(self) -> None:
        if self._is_loading:
            return
        self._save_timer.stop()
        self._save_timer.start(900)
        self._set_footer("Изменения...")

    def _save_file(self) -> None:
        if self._preset_path is None:
            return
        try:
            if self._is_orchestra_preset_backend():
                from preset_orchestra_zapret2 import _atomic_write_text, get_active_preset_name, get_active_preset_path, set_active_preset_name

                preset_name = self._get_orchestra_preset_name()
                if not preset_name:
                    raise ValueError("Preset name is required for orchestra preset saving")

                source_text = self.editor.toPlainText()
                _atomic_write_text(self._preset_path, source_text)

                active_name = str(get_active_preset_name() or "").strip()
                if active_name.lower() == preset_name.lower():
                    set_active_preset_name(preset_name)
                    _atomic_write_text(get_active_preset_path(), source_text)
                    self._notify_preset_switched()

                self._notify_preset_saved(f"{preset_name}.txt")
                self._set_footer(f"Сохранено {datetime.now().strftime('%H:%M:%S')}")
                return

            facade = self._get_direct_facade()
            if facade is None:
                raise ValueError("Direct preset facade is required")
            if not self._preset_file_name:
                raise ValueError("Preset file name is required for direct preset saving")
            updated = facade.save_source_text_by_file_name(self._preset_file_name, self.editor.toPlainText())
            self._preset_name = updated.name
            self._preset_file_name = updated.file_name
            self._preset_path = facade.get_source_path_by_file_name(self._preset_file_name)
            active_name = self._current_selected_name()
            active_file_name = self._current_selected_file_name()
            if (
                self._preset_file_name and active_file_name.lower() == self._preset_file_name.lower()
            ) or (
                not self._preset_file_name and active_name.lower() == self._preset_name.lower()
            ):
                self._notify_preset_switched()
            if self._preset_file_name:
                self._notify_preset_saved(self._preset_file_name)
            self._set_footer(f"Сохранено {datetime.now().strftime('%H:%M:%S')}")
        except Exception as e:
            self._set_footer(f"Ошибка сохранения: {e}")
            self._show_error(str(e))

    def _set_footer(self, text: str) -> None:
        self.footerLabel.setText(text)

    def _activate_preset(self) -> None:
        self._flush_pending_save()
        try:
            if self._activate_selected_preset():
                self._refresh_header()
                self._show_success(f"Пресет «{self._preset_name}» активирован")
            else:
                self._show_error(f"Не удалось активировать пресет «{self._preset_name}»")
        except Exception as e:
            self._show_error(str(e))

    def _open_external(self) -> None:
        try:
            self._flush_pending_save()
            if self._preset_path is None:
                return
            if os.name == "nt":
                os.startfile(str(self._preset_path))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(self._preset_path)])
        except Exception as e:
            self._show_error(str(e))

    def _open_menu(self) -> None:
        if RoundMenu is not None and Action is not None:
            menu = RoundMenu(parent=self)
            duplicate_action = _make_menu_action("Дублировать", icon=_fluent_icon("COPY"), parent=menu)
            export_action = _make_menu_action("Экспорт", icon=_fluent_icon("SHARE"), parent=menu)
            reset_action = _make_menu_action("Сбросить", icon=_fluent_icon("SYNC"), parent=menu)
            rename_action = None
            delete_action = None
            if not self._is_current_builtin():
                rename_action = _make_menu_action("Переименовать", icon=_fluent_icon("RENAME"), parent=menu)
                delete_action = _make_menu_action("Удалить", icon=_fluent_icon("DELETE"), parent=menu)
                rename_action.triggered.connect(self._rename_preset)
                delete_action.triggered.connect(self._delete_preset)
            duplicate_action.triggered.connect(self._duplicate_preset)
            export_action.triggered.connect(self._export_preset)
            reset_action.triggered.connect(self._reset_preset)
            if rename_action is not None:
                menu.addAction(rename_action)
            menu.addAction(duplicate_action)
            menu.addAction(export_action)
            menu.addAction(reset_action)
            if delete_action is not None:
                menu.addAction(delete_action)
            menu.exec(self.menuButton.mapToGlobal(self.menuButton.rect().bottomLeft()))

    def _rename_preset(self) -> None:
        if self._is_current_builtin():
            self._show_error("Встроенный пресет нельзя переименовать. Создайте копию и работайте уже с ней.")
            return
        self._flush_pending_save()
        dialog = _RenameDialog(self._preset_name, [], self.window())
        if not dialog.exec():
            return
        new_name = dialog.nameEdit.text().strip()
        if not new_name or new_name == self._preset_name:
            return
        try:
            if self._is_orchestra_preset_backend():
                from preset_orchestra_zapret2 import get_active_preset_name, rename_preset

                old_name = self._get_orchestra_preset_name()
                if not old_name:
                    raise ValueError("Preset name is required for orchestra preset rename")
                if not rename_preset(old_name, new_name):
                    raise ValueError("Не удалось переименовать orchestra preset")
                self._notify_presets_changed()
                self.set_preset_file_name(f"{new_name}.txt")
                active_name = str(get_active_preset_name() or "").strip()
                if active_name.lower() == new_name.lower():
                    self._notify_preset_switched()
                self._show_success(f"Пресет переименован: {new_name}")
                return

            facade = self._get_direct_facade()
            if facade is None:
                raise ValueError("Direct preset facade is required")
            if not self._preset_file_name:
                raise ValueError("Preset file name is required for direct preset rename")
            updated = facade.rename_by_file_name(self._preset_file_name, new_name)
            self._notify_presets_changed()
            self.set_preset_file_name(updated.file_name)
            if self._preset_file_name and facade.is_selected_file_name(self._preset_file_name):
                self._notify_preset_switched()
            self._show_success(f"Пресет переименован: {new_name}")
        except Exception as e:
            self._show_error(str(e))

    def _duplicate_preset(self) -> None:
        self._flush_pending_save()
        try:
            new_name = f"{self._preset_name} (копия)"
            if self._is_orchestra_preset_backend():
                from preset_orchestra_zapret2 import duplicate_preset

                source_name = self._get_orchestra_preset_name()
                if not source_name:
                    raise ValueError("Preset name is required for orchestra preset duplicate")
                if not duplicate_preset(source_name, new_name):
                    raise ValueError("Не удалось создать копию orchestra preset")
                self._notify_presets_changed()
                self.set_preset_file_name(f"{new_name}.txt")
                self._show_success(f"Создан дубликат: {new_name}")
                return

            facade = self._get_direct_facade()
            if facade is None:
                raise ValueError("Direct preset facade is required")
            if not self._preset_file_name:
                raise ValueError("Preset file name is required for direct preset duplicate")
            duplicated = facade.duplicate_by_file_name(self._preset_file_name, new_name)
            self._notify_presets_changed()
            self.set_preset_file_name(duplicated.file_name)
            self._show_success(f"Создан дубликат: {new_name}")
        except Exception as e:
            self._show_error(str(e))

    def _export_preset(self) -> None:
        self._flush_pending_save()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Экспортировать пресет",
            f"{self._preset_name}.txt",
            "Preset files (*.txt);;All files (*.*)",
        )
        if not file_path:
            return
        try:
            if self._is_orchestra_preset_backend():
                from preset_orchestra_zapret2 import export_preset

                preset_name = self._get_orchestra_preset_name()
                if not preset_name:
                    raise ValueError("Preset name is required for orchestra preset export")
                if not export_preset(preset_name, Path(file_path)):
                    raise ValueError("Не удалось экспортировать orchestra preset")
                self._show_success(f"Пресет экспортирован: {file_path}")
                return

            facade = self._get_direct_facade()
            if facade is None:
                raise ValueError("Direct preset facade is required")
            if not self._preset_file_name:
                raise ValueError("Preset file name is required for direct preset export")
            facade.export_plain_text_by_file_name(self._preset_file_name, Path(file_path))
            self._show_success(f"Пресет экспортирован: {file_path}")
        except Exception as e:
            self._show_error(str(e))

    def _reset_preset(self) -> None:
        self._flush_pending_save()
        if MessageBox is not None:
            box = MessageBox(
                "Сбросить пресет?",
                f"Пресет «{self._preset_name}» будет перезаписан данными из шаблона.",
                self.window(),
            )
            box.yesButton.setText("Сбросить")
            box.cancelButton.setText("Отмена")
            if not box.exec():
                return
        try:
            if self._is_orchestra_preset_backend():
                from preset_orchestra_zapret2 import PresetManager, get_active_preset_name

                preset_name = self._get_orchestra_preset_name()
                if not preset_name:
                    raise ValueError("Preset name is required for orchestra preset reset")
                is_active = str(get_active_preset_name() or "").strip().lower() == preset_name.lower()
                manager = PresetManager()
                if not manager.reset_preset_to_default_template(
                    preset_name,
                    make_active=is_active,
                    sync_active_file=is_active,
                    emit_switched=is_active,
                ):
                    raise ValueError("Не удалось сбросить orchestra preset")
                self.set_preset_file_name(f"{preset_name}.txt")
                self._notify_preset_saved(f"{preset_name}.txt")
                self._show_success(f"Пресет «{self._preset_name}» сброшен")
                return

            facade = self._get_direct_facade()
            if facade is None:
                raise ValueError("Direct preset facade is required")
            if not self._preset_file_name:
                raise ValueError("Preset file name is required for direct preset reset")
            updated = facade.reset_to_template_by_file_name(self._preset_file_name)
            self._preset_name = updated.name
            self._preset_file_name = updated.file_name
            self._preset_path = facade.get_source_path_by_file_name(self._preset_file_name)
            self._load_file()
            self._refresh_header()
            if self._preset_file_name:
                self._notify_preset_saved(self._preset_file_name)
            if self._preset_file_name and facade.is_selected_file_name(self._preset_file_name):
                self._notify_preset_switched()
            self._show_success(f"Пресет «{self._preset_name}» сброшен")
        except Exception as e:
            self._show_error(str(e))

    def _delete_preset(self) -> None:
        if self._is_current_builtin():
            self._show_error("Встроенный пресет нельзя удалить.")
            return
        self._flush_pending_save()
        if MessageBox is not None:
            box = MessageBox(
                "Удалить пресет?",
                f"Пресет «{self._preset_name}» будет удалён.",
                self.window(),
            )
            box.yesButton.setText("Удалить")
            box.cancelButton.setText("Отмена")
            if not box.exec():
                return
        try:
            name = self._preset_name
            if self._is_orchestra_preset_backend():
                from preset_orchestra_zapret2 import delete_preset

                preset_name = self._get_orchestra_preset_name()
                if not preset_name:
                    raise ValueError("Preset name is required for orchestra preset delete")
                if not delete_preset(preset_name):
                    raise ValueError("Не удалось удалить orchestra preset")
                self._notify_presets_changed()
                self.back_clicked.emit()
                self._show_success(f"Пресет «{name}» удалён")
                return

            facade = self._get_direct_facade()
            if facade is None:
                raise ValueError("Direct preset facade is required")
            if not self._preset_file_name:
                raise ValueError("Preset file name is required for direct preset delete")
            facade.delete_by_file_name(self._preset_file_name)
            self._notify_presets_changed()
            self.back_clicked.emit()
            self._show_success(f"Пресет «{name}» удалён")
        except Exception as e:
            self._show_error(str(e))

    def _current_selected_name(self) -> str:
        try:
            if self._is_orchestra_preset_backend():
                from preset_orchestra_zapret2 import get_active_preset_name

                return str(get_active_preset_name() or "").strip()

            from core.services import get_direct_flow_coordinator

            method = self._direct_launch_method()
            selected = get_direct_flow_coordinator().get_selected_source_manifest(method)
            return (selected.name if selected is not None else "").strip()
        except Exception:
            return ""

    def _current_selected_file_name(self) -> str:
        try:
            if self._is_orchestra_preset_backend():
                active_name = self._current_selected_name()
                return f"{active_name}.txt" if active_name else ""

            from core.services import get_direct_flow_coordinator

            method = self._direct_launch_method()
            return (get_direct_flow_coordinator().get_selected_source_file_name(method) or "").strip()
        except Exception:
            return ""

    def _activate_selected_preset(self) -> bool:
        try:
            if self._is_orchestra_preset_backend():
                from preset_orchestra_zapret2 import PresetManager

                preset_name = self._get_orchestra_preset_name()
                if not preset_name:
                    return False
                return bool(PresetManager().switch_preset(preset_name, reload_dpi=False))

            from core.services import get_direct_flow_coordinator

            method = self._direct_launch_method()
            if not self._preset_file_name:
                return False
            get_direct_flow_coordinator().select_preset_file_name(method, self._preset_file_name)
            self._notify_preset_switched()
            return True
        except Exception:
            return False

    def _notify_preset_switched(self) -> None:
        method = self._direct_launch_method()
        if not self._preset_file_name and not self._is_orchestra_preset_backend():
            return
        try:
            if method == "direct_zapret2":
                from core.services import get_preset_store

                get_preset_store().notify_preset_switched(self._preset_file_name)
            elif method == "direct_zapret1":
                from core.services import get_preset_store_v1

                get_preset_store_v1().notify_preset_switched(self._preset_file_name)
            elif self._is_orchestra_preset_backend():
                from preset_orchestra_zapret2 import get_preset_store

                get_preset_store().notify_preset_switched(self._get_orchestra_preset_name())
        except Exception:
            pass

    def _notify_preset_saved(self, file_name: str) -> None:
        try:
            method = self._direct_launch_method()
            if method == "direct_zapret2":
                from core.services import get_preset_store

                get_preset_store().notify_preset_saved(file_name)
            elif method == "direct_zapret1":
                from core.services import get_preset_store_v1

                get_preset_store_v1().notify_preset_saved(file_name)
            elif self._is_orchestra_preset_backend():
                from preset_orchestra_zapret2 import get_preset_store

                get_preset_store().notify_preset_saved(self._get_orchestra_preset_name())
        except Exception:
            pass

    def _notify_presets_changed(self) -> None:
        try:
            method = self._direct_launch_method()
            if method == "direct_zapret2":
                from core.services import get_preset_store

                get_preset_store().notify_presets_changed()
            elif method == "direct_zapret1":
                from core.services import get_preset_store_v1

                get_preset_store_v1().notify_presets_changed()
            elif self._is_orchestra_preset_backend():
                from preset_orchestra_zapret2 import get_preset_store

                get_preset_store().notify_presets_changed()
        except Exception:
            pass
