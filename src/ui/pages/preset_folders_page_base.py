from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QListWidget, QListWidgetItem, QWidget

from core.presets.library_hierarchy import ROOT_FOLDER_ID, PresetHierarchyStore
from ui.compat_widgets import ActionButton, LineEdit, SettingsCard
from ui.pages.base_page import BasePage

try:
    from qfluentwidgets import BodyLabel, BreadcrumbBar, CaptionLabel, SubtitleLabel
except ImportError:
    from PyQt6.QtWidgets import QLabel as BodyLabel, QLabel as CaptionLabel, QLabel as SubtitleLabel

    BreadcrumbBar = None  # type: ignore


class PresetFoldersPageBase(BasePage):
    back_clicked = pyqtSignal()
    folders_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(self._default_title(), "", parent)
        self.parent_app = parent
        self._breadcrumb = None
        self._back_btn = None
        self._store = None
        self._selected_folder_id = ""
        self._build_ui()

    def _default_title(self) -> str:
        return "Папки пресетов"

    def _scope_key(self) -> str:
        raise NotImplementedError

    def _breadcrumb_root_label(self) -> str:
        return "Мои пресеты"

    def _get_store(self) -> PresetHierarchyStore:
        if self._store is None:
            self._store = PresetHierarchyStore(self._scope_key())
        return self._store

    def _build_ui(self) -> None:
        if BreadcrumbBar is not None:
            try:
                self._breadcrumb = BreadcrumbBar(self)
                self._rebuild_breadcrumb()
                self._breadcrumb.currentItemChanged.connect(self._on_breadcrumb_changed)
                self.layout.insertWidget(0, self._breadcrumb)
            except Exception:
                self._breadcrumb = None

        intro = SettingsCard()
        intro_layout = QHBoxLayout()
        intro_layout.setContentsMargins(0, 0, 0, 0)
        intro_layout.setSpacing(12)
        title = SubtitleLabel("Папки пресетов", self)
        subtitle = BodyLabel(
            "Здесь можно создавать свои папки, менять вложенность и порядок их показа без всплывающих окон.",
            self,
        )
        subtitle.setWordWrap(True)
        text_col = QWidget(self)
        text_layout = QHBoxLayout(text_col)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)
        inner = QWidget(self)
        from PyQt6.QtWidgets import QVBoxLayout

        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(6)
        inner_layout.addWidget(title)
        inner_layout.addWidget(subtitle)
        text_layout.addWidget(inner)
        intro_layout.addWidget(text_col, 1)
        intro.add_layout(intro_layout)
        self.add_widget(intro)

        editor_card = SettingsCard()
        editor_layout = QVBoxLayout(editor_card)
        editor_layout.setContentsMargins(16, 16, 16, 16)
        editor_layout.setSpacing(10)

        self.listWidget = QListWidget(self)
        editor_layout.addWidget(self.listWidget)

        self.nameEdit = LineEdit(self)
        self.nameEdit.setPlaceholderText("Название папки")
        editor_layout.addWidget(self.nameEdit)

        self.parentCombo = QComboBox(self)
        editor_layout.addWidget(self.parentCombo)

        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(8)

        self.newButton = ActionButton("Новая папка", "fa5s.folder-plus")
        self.saveButton = ActionButton("Сохранить", "fa5s.save")
        self.deleteButton = ActionButton("Удалить", "fa5s.trash-alt")
        self.upButton = ActionButton("Выше", "fa5s.arrow-up")
        self.downButton = ActionButton("Ниже", "fa5s.arrow-down")

        for button in (self.newButton, self.saveButton, self.deleteButton, self.upButton, self.downButton):
            actions_row.addWidget(button)
        actions_row.addStretch(1)
        editor_layout.addLayout(actions_row)

        self.infoLabel = CaptionLabel("", self)
        editor_layout.addWidget(self.infoLabel)
        self.add_widget(editor_card)

        self.listWidget.currentItemChanged.connect(self._on_current_item_changed)
        self.newButton.clicked.connect(self._on_new_folder)
        self.saveButton.clicked.connect(self._on_save_folder)
        self.deleteButton.clicked.connect(self._on_delete_folder)
        self.upButton.clicked.connect(lambda: self._on_move_folder(-1))
        self.downButton.clicked.connect(lambda: self._on_move_folder(1))

    def showEvent(self, event):
        super().showEvent(event)
        self._reload()

    def _rebuild_breadcrumb(self):
        if self._breadcrumb is None:
            return
        self._breadcrumb.blockSignals(True)
        try:
            self._breadcrumb.clear()
            self._breadcrumb.addItem("presets", self._breadcrumb_root_label())
            self._breadcrumb.addItem("folders", "Папки пресетов")
        finally:
            self._breadcrumb.blockSignals(False)

    def _on_breadcrumb_changed(self, key: str):
        self._rebuild_breadcrumb()
        if key == "presets":
            self.back_clicked.emit()

    def _reload(self):
        store = self._get_store()
        current = self._selected_folder_id
        self.listWidget.clear()
        for item in store.get_folder_choices(include_root=True):
            folder_id = str(item.get("id") or "")
            meta = store.get_folder_meta(folder_id) or item
            indent = "    " * int(meta.get("depth", 0) or 0)
            text = f"{indent}{meta.get('name', '')}"
            if bool(meta.get("builtin", False)):
                text += " [системная]"
            row = QListWidgetItem(text)
            row.setData(32, folder_id)
            row.setData(33, bool(meta.get("builtin", False)))
            self.listWidget.addItem(row)

        target_row = 0
        if current:
            for idx in range(self.listWidget.count()):
                if str(self.listWidget.item(idx).data(32) or "") == current:
                    target_row = idx
                    break
        if self.listWidget.count():
            self.listWidget.setCurrentRow(target_row)
        self._reload_parent_combo()
        self._sync_buttons()

    def _reload_parent_combo(self, *, exclude_folder_id: str | None = None):
        choices = self._get_store().get_folder_choices(include_root=True, exclude_folder_id=exclude_folder_id)
        self.parentCombo.clear()
        for item in choices:
            indent = "    " * int(item.get("depth", 0) or 0)
            self.parentCombo.addItem(f"{indent}{item.get('name', '')}", item.get("id", ROOT_FOLDER_ID))

    def _sync_buttons(self):
        folder_id = self._selected_folder_id
        meta = self._get_store().get_folder_meta(folder_id) if folder_id else None
        is_builtin = bool(meta.get("builtin", False)) if meta else False
        editable = bool(folder_id) and not is_builtin and folder_id != ROOT_FOLDER_ID
        movable = bool(folder_id)

        self.deleteButton.setEnabled(editable)
        self.upButton.setEnabled(movable)
        self.downButton.setEnabled(movable)
        self.saveButton.setEnabled(True)

    def _on_current_item_changed(self, current, _previous):
        if current is None:
            self._selected_folder_id = ""
            self.nameEdit.clear()
            self._reload_parent_combo()
            self._sync_buttons()
            return

        folder_id = str(current.data(32) or "")
        self._selected_folder_id = folder_id
        meta = self._get_store().get_folder_meta(folder_id) or {}
        self.nameEdit.setText(str(meta.get("name") or ""))
        self._reload_parent_combo(exclude_folder_id=folder_id if folder_id not in (ROOT_FOLDER_ID, "") else None)
        parent_id = str(meta.get("parent_id") or ROOT_FOLDER_ID)
        for idx in range(self.parentCombo.count()):
            if str(self.parentCombo.itemData(idx) or "") == parent_id:
                self.parentCombo.setCurrentIndex(idx)
                break
        self.infoLabel.setText("Системную папку нельзя удалить или переименовать." if bool(meta.get("builtin", False)) else "")
        self._sync_buttons()

    def _on_new_folder(self):
        self._selected_folder_id = ""
        self.nameEdit.clear()
        self._reload_parent_combo()
        for idx in range(self.parentCombo.count()):
            if str(self.parentCombo.itemData(idx) or "") == ROOT_FOLDER_ID:
                self.parentCombo.setCurrentIndex(idx)
                break
        self.infoLabel.setText("Создание новой пользовательской папки.")
        self.listWidget.clearSelection()
        self._sync_buttons()

    def _on_save_folder(self):
        name = self.nameEdit.text().strip()
        if not name:
            self.infoLabel.setText("Введите название папки.")
            return
        parent_id = str(self.parentCombo.currentData() or ROOT_FOLDER_ID)
        store = self._get_store()

        try:
            if self._selected_folder_id and self._selected_folder_id not in (ROOT_FOLDER_ID,) and not bool((store.get_folder_meta(self._selected_folder_id) or {}).get("builtin", False)):
                store.update_folder(
                    self._selected_folder_id,
                    name=name,
                    parent_id=None if parent_id == ROOT_FOLDER_ID else parent_id,
                )
            else:
                created = store.create_folder(name, None if parent_id == ROOT_FOLDER_ID else parent_id)
                self._selected_folder_id = created["id"]
            self.infoLabel.setText("Папка сохранена.")
            self.folders_changed.emit()
            self._reload()
        except Exception as e:
            self.infoLabel.setText(f"Ошибка сохранения папки: {e}")

    def _on_delete_folder(self):
        folder_id = self._selected_folder_id
        if not folder_id or folder_id == ROOT_FOLDER_ID:
            return
        meta = self._get_store().get_folder_meta(folder_id) or {}
        if bool(meta.get("builtin", False)):
            self.infoLabel.setText("Системную папку удалить нельзя.")
            return
        try:
            self._get_store().delete_folder(folder_id)
            self._selected_folder_id = ""
            self.infoLabel.setText("Папка удалена.")
            self.folders_changed.emit()
            self._reload()
        except Exception as e:
            self.infoLabel.setText(f"Ошибка удаления папки: {e}")

    def _on_move_folder(self, direction: int):
        folder_id = self._selected_folder_id
        if not folder_id:
            return
        moved = self._get_store().move_folder_up(folder_id) if direction < 0 else self._get_store().move_folder_down(folder_id)
        if moved:
            self.infoLabel.setText("Порядок папок изменён.")
            self.folders_changed.emit()
            self._reload()
