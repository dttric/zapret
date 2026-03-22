# ui/pages/support_page.py
"""Страница Поддержка - ZapretHub и каналы связи"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import webbrowser

import qtawesome as qta
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

try:
    from qfluentwidgets import StrongBodyLabel, CaptionLabel, BodyLabel, InfoBar
    _HAS_FLUENT_LABELS = True
except ImportError:
    StrongBodyLabel = QLabel
    CaptionLabel = QLabel
    BodyLabel = QLabel
    InfoBar = None
    _HAS_FLUENT_LABELS = False

from .base_page import BasePage
from log import log
from ui.compat_widgets import ActionButton, SettingsCard, SettingsRow
from ui.theme_semantic import get_semantic_palette
from ui.theme import get_theme_tokens
from ui.text_catalog import tr as tr_catalog


class SupportPage(BasePage):
    """Страница поддержки (внутри группы "О программе")"""

    _POLL_INTERVAL_MS = 1500
    _POLL_TIMEOUT_S = 120

    def __init__(self, parent=None):
        super().__init__(
            "Поддержка",
            "ZapretHub и каналы связи",
            parent,
            title_key="page.support.title",
            subtitle_key="page.support.subtitle",
        )

        self._zaphub_exe: str | None = None
        self._zaphub_installing: bool = False
        self._poll_timer: QTimer | None = None
        self._poll_deadline_ts: float | None = None

        # UI refs
        self._zaphub_status_label: QLabel | None = None
        self._zaphub_action_btn: ActionButton | None = None
        self._hub_icon_label: QLabel | None = None

        self._hub_title_label: QLabel | None = None
        self._hub_desc_label: QLabel | None = None
        self._tg_row: SettingsRow | None = None
        self._tg_btn: ActionButton | None = None
        self._dc_row: SettingsRow | None = None
        self._dc_btn: ActionButton | None = None

        from qfluentwidgets import qconfig
        qconfig.themeChanged.connect(lambda _: self._apply_theme())
        qconfig.themeColorChanged.connect(lambda _: self._apply_theme())

        self._build_ui()

    def _tr(self, key: str, default: str) -> str:
        return tr_catalog(key, language=self._ui_language, default=default)

    # ---------------------------------------------------------------------
    # UI
    # ---------------------------------------------------------------------
    def _build_ui(self) -> None:
        tokens = get_theme_tokens()
        # ZapretHub block
        self.add_section_title(text_key="page.support.section.zaprethub")

        hub_card = SettingsCard()

        hub_layout = QHBoxLayout()
        hub_layout.setSpacing(16)

        icon_label = QLabel()
        icon_label.setPixmap(qta.icon("fa5s.users", color=tokens.accent_hex).pixmap(36, 36))
        icon_label.setFixedSize(44, 44)
        self._hub_icon_label = icon_label
        hub_layout.addWidget(icon_label)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        self._hub_title_label = StrongBodyLabel(self._tr("page.support.zaphub.title", "ZapretHub"))
        self._hub_title_label.setProperty("tone", "primary")
        text_layout.addWidget(self._hub_title_label)

        self._hub_desc_label = CaptionLabel(
            self._tr("page.support.zaphub.description", "Центр сообщества Zapret: стратегии, пресеты и форум.")
        )
        self._hub_desc_label.setWordWrap(True)
        self._hub_desc_label.setProperty("tone", "muted")
        text_layout.addWidget(self._hub_desc_label)

        self._zaphub_status_label = CaptionLabel(
            self._tr("page.support.zaphub.status.checking", "Статус: проверяю…")
        )
        self._zaphub_status_label.setStyleSheet(f"color: {tokens.fg_muted};")
        text_layout.addWidget(self._zaphub_status_label)

        hub_layout.addLayout(text_layout, 1)

        self._zaphub_action_btn = ActionButton(
            self._tr("page.support.zaphub.action.placeholder", "…"),
            "fa5s.download",
            accent=True,
        )
        self._zaphub_action_btn.setProperty("noDrag", True)
        self._zaphub_action_btn.setFixedHeight(36)
        self._zaphub_action_btn.clicked.connect(self._on_zaphub_action_clicked)
        hub_layout.addWidget(self._zaphub_action_btn)

        hub_card.add_layout(hub_layout)
        self.add_widget(hub_card)

        self.add_spacing(16)

        # Support channels
        self.add_section_title(text_key="page.support.section.channels")
        channels_card = SettingsCard()

        # Telegram
        self._tg_row = SettingsRow(
            "fa5b.telegram",
            self._tr("page.support.channel.telegram.title", "Telegram поддержка"),
            self._tr("page.support.channel.telegram.desc", "Помощь и вопросы по использованию"),
        )
        self._tg_btn = ActionButton(
            self._tr("page.support.channel.open", "Открыть"),
            "fa5s.external-link-alt",
            accent=False,
        )
        self._tg_btn.setProperty("noDrag", True)
        self._tg_btn.clicked.connect(self._open_telegram_support)
        self._tg_row.set_control(self._tg_btn)
        channels_card.add_widget(self._tg_row)

        # Discord
        self._dc_row = SettingsRow(
            "fa5b.discord",
            self._tr("page.support.channel.discord.title", "Discord сервер"),
            self._tr("page.support.channel.discord.desc", "Сообщество и живое общение"),
        )
        self._dc_btn = ActionButton(
            self._tr("page.support.channel.open", "Открыть"),
            "fa5s.external-link-alt",
            accent=False,
        )
        self._dc_btn.setProperty("noDrag", True)
        self._dc_btn.clicked.connect(self._open_discord)
        self._dc_row.set_control(self._dc_btn)
        channels_card.add_widget(self._dc_row)

        self.add_widget(channels_card)

        # Initial state refresh
        self._refresh_zaphub_state()

    def _apply_theme(self) -> None:
        tokens = get_theme_tokens()

        if self._hub_icon_label is not None:
            try:
                self._hub_icon_label.setPixmap(qta.icon("fa5s.users", color=tokens.accent_hex).pixmap(36, 36))
            except Exception:
                pass

        # Refresh status styles for the current theme.
        try:
            self._refresh_zaphub_state()
        except Exception:
            pass

    def set_ui_language(self, language: str) -> None:
        super().set_ui_language(language)

        if self._hub_title_label is not None:
            self._hub_title_label.setText(self._tr("page.support.zaphub.title", "ZapretHub"))
        if self._hub_desc_label is not None:
            self._hub_desc_label.setText(
                self._tr("page.support.zaphub.description", "Центр сообщества Zapret: стратегии, пресеты и форум.")
            )

        if self._tg_row is not None:
            self._tg_row.set_title(self._tr("page.support.channel.telegram.title", "Telegram поддержка"))
            self._tg_row.set_description(
                self._tr("page.support.channel.telegram.desc", "Помощь и вопросы по использованию")
            )
        if self._tg_btn is not None:
            self._tg_btn.setText(self._tr("page.support.channel.open", "Открыть"))

        if self._dc_row is not None:
            self._dc_row.set_title(self._tr("page.support.channel.discord.title", "Discord сервер"))
            self._dc_row.set_description(self._tr("page.support.channel.discord.desc", "Сообщество и живое общение"))
        if self._dc_btn is not None:
            self._dc_btn.setText(self._tr("page.support.channel.open", "Открыть"))

        self._refresh_zaphub_state()

    def showEvent(self, event):  # noqa: N802 (Qt naming)
        super().showEvent(event)
        # Обновляем статус при каждом показе страницы (после установки/обновления ZapretHub)
        try:
            self._refresh_zaphub_state()
        except Exception:
            pass

    # ---------------------------------------------------------------------
    # ZapretHub logic
    # ---------------------------------------------------------------------
    def _on_zaphub_action_clicked(self) -> None:
        try:
            self._refresh_zaphub_state()
        except Exception:
            pass

        if self._zaphub_exe and os.path.exists(self._zaphub_exe):
            self._open_zaphub()
            return

        self._install_zaphub()

    def _refresh_zaphub_state(self) -> None:
        exe = self._detect_zaphub_exe()
        self._zaphub_exe = exe

        status_label = self._zaphub_status_label
        action_btn = self._zaphub_action_btn
        if status_label is None or action_btn is None:
            return

        if exe and os.path.exists(exe):
            self._zaphub_installing = False
            status_label.setText(self._tr("page.support.zaphub.status.installed", "Статус: установлен"))
            semantic = get_semantic_palette()
            status_label.setStyleSheet(f"color: {semantic.success};")
            action_btn.setText(self._tr("page.support.zaphub.action.open", "Открыть"))
            action_btn.setIcon(qta.icon("fa5s.play", color=get_theme_tokens().fg))
            action_btn.setEnabled(True)
        elif self._zaphub_installing:
            # Do not override the in-progress UI state.
            action_btn.setEnabled(False)
        else:
            status_label.setText(self._tr("page.support.zaphub.status.not_installed", "Статус: не установлен"))
            tokens = get_theme_tokens()
            status_label.setStyleSheet(f"color: {tokens.fg_muted};")
            action_btn.setText(self._tr("page.support.zaphub.action.install", "Установить"))
            action_btn.setIcon(qta.icon("fa5s.download", color=tokens.fg))
            action_btn.setEnabled(True)

    def _open_zaphub(self) -> None:
        try:
            if not self._zaphub_exe:
                raise FileNotFoundError(self._tr("page.support.zaphub.error.not_found", "ZapretHub не найден"))

            os.startfile(self._zaphub_exe)  # noqa: S606 - Windows only
            log(f"Открыт ZapretHub: {self._zaphub_exe}", "INFO")
        except Exception as e:
            if InfoBar:
                InfoBar.warning(
                    title=self._tr("page.support.zaphub.title", "ZapretHub"),
                    content=self._tr(
                        "page.support.zaphub.error.open_failed",
                        "Не удалось открыть ZapretHub:\n{error}",
                    ).format(error=e),
                    parent=self.window(),
                )

    def _install_zaphub(self) -> None:
        installer = self._find_zaphub_installer()
        if not installer:
            if InfoBar:
                InfoBar.warning(
                    title=self._tr("page.support.zaphub.title", "ZapretHub"),
                    content=self._tr(
                        "page.support.zaphub.error.installer_not_found",
                        "Установщик ZapretHub не найден.\n\nПереустановите Zapret2 или установите ZapretHub через основной установщик.",
                    ),
                    parent=self.window(),
                )
            return

        action_btn = self._zaphub_action_btn
        status_label = self._zaphub_status_label
        if action_btn is not None:
            action_btn.setEnabled(False)
            action_btn.setText(self._tr("page.support.zaphub.action.installing", "Установка…"))
            action_btn.setIcon(qta.icon("fa5s.spinner", color=get_theme_tokens().fg))
        if status_label is not None:
            status_label.setText(
                self._tr("page.support.zaphub.status.install_started", "Статус: установка запущена…")
            )
            semantic = get_semantic_palette()
            status_label.setStyleSheet(f"color: {semantic.warning};")

        self._zaphub_installing = True

        args = [
            installer,
            "/S",
            "/SP-",
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
        ]

        try:
            try:
                subprocess.Popen(args)  # noqa: S603 - user-triggered installer
            except OSError as e:
                # Some installers require elevation; try RunAs fallback.
                if getattr(e, "winerror", None) == 740 and sys.platform == "win32":
                    try:
                        from updater.update import launch_installer_winapi

                        ok = launch_installer_winapi(installer, " ".join(args[1:]), os.path.dirname(installer))
                        if not ok:
                            raise
                    except Exception:
                        raise
                else:
                    raise

            log(f"Запущен установщик ZapretHub: {installer}", "INFO")
            self._start_polling_zaphub_install()
        except Exception as e:
            self._zaphub_installing = False
            if action_btn is not None:
                action_btn.setEnabled(True)
            if InfoBar:
                InfoBar.warning(
                    title=self._tr("page.support.zaphub.title", "ZapretHub"),
                    content=self._tr(
                        "page.support.zaphub.error.install_start_failed",
                        "Не удалось запустить установку:\n{error}",
                    ).format(error=e),
                    parent=self.window(),
                )
            try:
                self._refresh_zaphub_state()
            except Exception:
                pass

    def _start_polling_zaphub_install(self) -> None:
        now = time.time()
        self._poll_deadline_ts = now + self._POLL_TIMEOUT_S

        if self._poll_timer is None:
            self._poll_timer = QTimer(self)
            self._poll_timer.timeout.connect(self._poll_zaphub_install)

        self._poll_timer.start(self._POLL_INTERVAL_MS)

    def _poll_zaphub_install(self) -> None:
        try:
            self._refresh_zaphub_state()
        except Exception:
            pass

        # Stop polling when installed.
        if self._zaphub_exe and os.path.exists(self._zaphub_exe):
            if self._poll_timer is not None:
                self._poll_timer.stop()
            return

        # Stop polling on timeout.
        if self._poll_deadline_ts is not None and time.time() >= self._poll_deadline_ts:
            if self._poll_timer is not None:
                self._poll_timer.stop()
            self._zaphub_installing = False
            try:
                self._refresh_zaphub_state()
            except Exception:
                pass

    def _find_zaphub_installer(self) -> str | None:
        """Ищет установщик ZapretHub (должен быть внешним файлом в %APPDATA%)."""
        try:
            appdata = os.environ.get("APPDATA", "")
            if appdata:
                p = os.path.join(appdata, "zaprettracker", "ZapretHub-Setup.exe")
                if os.path.exists(p):
                    return p
        except Exception:
            pass

        # Dev fallback (repo checkout)
        try:
            repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            p = os.path.join(repo_root, "tracker", "ZapretHub-Setup-1.0.0.exe")
            if os.path.exists(p):
                return p
        except Exception:
            pass

        return None

    def _detect_zaphub_exe(self) -> str | None:
        """Best-effort detection of installed ZapretHub executable."""

        # Fast path: common install locations
        try:
            local_appdata = os.environ.get("LOCALAPPDATA", "")
            appdata = os.environ.get("APPDATA", "")
            candidates: list[str] = []
            for base in (local_appdata, appdata):
                if not base:
                    continue
                candidates.extend(
                    [
                        os.path.join(base, "Programs", "ZapretHub", "ZapretHub.exe"),
                        os.path.join(base, "ZapretHub", "ZapretHub.exe"),
                        os.path.join(base, "zaprethub", "ZapretHub.exe"),
                        os.path.join(base, "zaprettracker", "ZapretHub.exe"),
                        os.path.join(base, "zaprettracker", "ZapretTracker.exe"),
                    ]
                )

            for p in candidates:
                if p and os.path.exists(p):
                    return p
        except Exception:
            pass

        # Registry scan (Inno Setup uninstall keys)
        if sys.platform != "win32":
            return None

        try:
            import winreg  # stdlib on Windows
        except Exception:
            return None

        hints = ("zaprethub", "zapret hub", "zapret-hub")
        exe_names = ("zaprethub.exe", "zaprettracker.exe", "zapret hub.exe")

        def _parse_display_icon(raw: str) -> str:
            raw = (raw or "").strip().strip('"')
            if not raw:
                return ""
            # Inno sometimes stores: "C:\\Path\\app.exe",0
            if "," in raw:
                raw = raw.split(",", 1)[0].strip().strip('"')
            return raw

        def _safe_get_value(hkey, name: str) -> str:
            try:
                v, _t = winreg.QueryValueEx(hkey, name)
                return str(v)
            except Exception:
                return ""

        def _has_hint(s: str) -> bool:
            s = (s or "").lower()
            if not s:
                return False
            s_compact = s.replace(" ", "").replace("-", "")
            for h in hints:
                h_l = h.lower()
                if h_l in s:
                    return True
                if h_l.replace(" ", "").replace("-", "") in s_compact:
                    return True
            return False

        roots = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        views: list[int] = []
        try:
            views.append(winreg.KEY_WOW64_64KEY)
            views.append(winreg.KEY_WOW64_32KEY)
        except Exception:
            views.append(0)

        matches: list[tuple[int, str]] = []

        for hive, root_path in roots:
            for view in views:
                try:
                    root = winreg.OpenKey(hive, root_path, 0, winreg.KEY_READ | view)
                except Exception:
                    continue

                try:
                    i = 0
                    while True:
                        try:
                            subkey_name = winreg.EnumKey(root, i)
                        except OSError:
                            break
                        i += 1

                        try:
                            h = winreg.OpenKey(root, subkey_name, 0, winreg.KEY_READ | view)
                        except Exception:
                            continue

                        try:
                            display_name = _safe_get_value(h, "DisplayName")
                            if not (_has_hint(display_name) or _has_hint(subkey_name)):
                                continue

                            install_location = _safe_get_value(h, "InstallLocation")
                            app_path = _safe_get_value(h, "Inno Setup: App Path")
                            display_icon = _parse_display_icon(_safe_get_value(h, "DisplayIcon"))

                            candidate: str | None = None
                            if display_icon.lower().endswith(".exe"):
                                candidate = display_icon
                            elif install_location:
                                candidate = os.path.join(install_location, "ZapretHub.exe")
                            elif app_path:
                                candidate = os.path.join(app_path, "ZapretHub.exe")

                            if not candidate:
                                continue

                            cand_l = candidate.lower().replace("/", "\\")
                            score = 0
                            dn_l = (display_name or "").lower()
                            sk_l = (subkey_name or "").lower()

                            if "zaprethub" in dn_l:
                                score += 120
                            if "zaprethub" in sk_l:
                                score += 120
                            if ("zapret" in dn_l and "hub" in dn_l) or ("zapret" in sk_l and "hub" in sk_l):
                                score += 60
                            if any(cand_l.endswith("\\" + n) for n in exe_names):
                                score += 25
                            if cand_l.endswith("\\zaprethub.exe"):
                                score += 10

                            if score > 0:
                                matches.append((score, candidate))
                        finally:
                            try:
                                winreg.CloseKey(h)
                            except Exception:
                                pass
                finally:
                    try:
                        winreg.CloseKey(root)
                    except Exception:
                        pass

        if not matches:
            return None

        matches.sort(key=lambda t: t[0], reverse=True)
        for _score, path in matches:
            try:
                if os.path.exists(path):
                    return path
            except Exception:
                continue

        return matches[0][1]

    # ---------------------------------------------------------------------
    # Support channels
    # ---------------------------------------------------------------------
    def _open_telegram_support(self) -> None:
        try:
            from config.telegram_links import open_telegram_link

            open_telegram_link("zaprethelp")
            log("Открыт Telegram: zaprethelp", "INFO")
        except Exception as e:
            if InfoBar:
                InfoBar.warning(
                    title=self._tr("page.support.error.title", "Ошибка"),
                    content=self._tr(
                        "page.support.error.open_telegram",
                        "Не удалось открыть Telegram:\n{error}",
                    ).format(error=e),
                    parent=self.window(),
                )

    def _open_discord(self) -> None:
        try:
            url = "https://discord.gg/kkcBDG2uws"
            webbrowser.open(url)
            log(f"Открыт Discord: {url}", "INFO")
        except Exception as e:
            if InfoBar:
                InfoBar.warning(
                    title=self._tr("page.support.error.title", "Ошибка"),
                    content=self._tr(
                        "page.support.error.open_discord",
                        "Не удалось открыть Discord:\n{error}",
                    ).format(error=e),
                    parent=self.window(),
                )
