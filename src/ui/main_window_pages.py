from __future__ import annotations

from importlib import import_module

from PyQt6.QtWidgets import QWidget

from log import log
from ui.page_names import PageName


def get_eager_page_names(window) -> tuple[PageName, ...]:
    method = window._get_launch_method()

    names: list[PageName] = [PageName.HOME]
    eager_mode_entry_page = getattr(window, "_eager_mode_entry_page", {}) or {}
    eager_page_names_base = getattr(window, "_eager_page_names_base", ()) or ()
    entry_page = eager_mode_entry_page.get(method)
    if entry_page is not None and entry_page not in names:
        names.append(entry_page)
    elif PageName.CONTROL not in names:
        # CONTROL нужен как стартовая страница только там, где нет
        # отдельной mode-specific entry page.
        names.append(PageName.CONTROL)

    for page_name in eager_page_names_base:
        if page_name not in names:
            names.append(page_name)

    return tuple(names)


def create_pages(window) -> None:
    """Create page registry and initialize critical pages eagerly."""
    import time as _time

    _t_pages_total = _time.perf_counter()

    for page_name in get_eager_page_names(window):
        ensure_page(window, page_name)
        window._pump_startup_ui()

    log(
        f"⏱ Startup: _create_pages core {(_time.perf_counter() - _t_pages_total) * 1000:.0f}ms",
        "DEBUG",
    )
    window._pump_startup_ui(force=True)


def resolve_page_name(window, name: PageName) -> PageName:
    return window._page_aliases.get(name, name)


def get_page_route_key(window, name: PageName) -> str | None:
    """Возвращает стабильный route key для Fluent-навигации без создания страницы."""
    resolved_name = resolve_page_name(window, name)

    # Эти страницы используют один и тот же класс, поэтому route key должен
    # быть уникальным и стабильным даже до фактического создания QWidget.
    if resolved_name == PageName.ZAPRET2_USER_PRESETS:
        return "Zapret2UserPresetsPage_Direct"
    if resolved_name == PageName.ZAPRET2_ORCHESTRA_USER_PRESETS:
        return "Zapret2UserPresetsPage_Orchestra"

    page_class_specs = getattr(window, "_page_class_specs", {}) or {}
    spec = page_class_specs.get(resolved_name)
    if spec is None:
        return None

    return str(spec[2] or "").strip() or None


def connect_signal_once(window, key: str, signal_obj, slot_obj) -> None:
    if key in window._lazy_signal_connections:
        return
    try:
        signal_obj.connect(slot_obj)
        window._lazy_signal_connections.add(key)
    except Exception:
        pass


def ensure_page_in_stacked_widget(window, page: QWidget | None) -> None:
    stack = getattr(window, "stackedWidget", None)
    if page is None or stack is None:
        return
    try:
        if stack.indexOf(page) < 0:
            stack.addWidget(page)
    except Exception:
        pass


def connect_lazy_page_signals(window, page_name: PageName, page: QWidget) -> None:
    if page_name in (
        PageName.ZAPRET1_DIRECT,
        PageName.ZAPRET2_DIRECT,
        PageName.ZAPRET2_ORCHESTRA,
    ):
        if hasattr(page, "strategy_selected"):
            connect_signal_once(
                window,
                f"strategy_selected.{page_name.name}",
                page.strategy_selected,
                window._on_strategy_selected_from_page,
            )

    if page_name == PageName.ZAPRET2_DIRECT and hasattr(page, "open_target_detail"):
        connect_signal_once(
            window,
            "z2_direct.open_target_detail",
            page.open_target_detail,
            window._on_open_target_detail,
        )

    if page_name in (PageName.ZAPRET2_DIRECT, PageName.ZAPRET2_USER_PRESETS, PageName.BLOBS) and hasattr(page, "back_clicked"):
        connect_signal_once(
            window,
            f"back_to_control.{page_name.name}",
            page.back_clicked,
            window._show_active_zapret2_control_page,
        )

    if page_name == PageName.ZAPRET2_ORCHESTRA_USER_PRESETS and hasattr(page, "back_clicked"):
        connect_signal_once(
            window,
            "back_to_orchestra_control.user_presets",
            page.back_clicked,
            lambda: window.show_page(PageName.ZAPRET2_ORCHESTRA_CONTROL),
        )

    if page_name in (PageName.ZAPRET1_DIRECT, PageName.ZAPRET1_USER_PRESETS) and hasattr(page, "back_clicked"):
        connect_signal_once(
            window,
            f"back_to_z1_control.{page_name.name}",
            page.back_clicked,
            lambda: window.show_page(PageName.ZAPRET1_DIRECT_CONTROL),
        )

    if page_name in (PageName.ZAPRET2_USER_PRESETS, PageName.ZAPRET2_ORCHESTRA_USER_PRESETS) and hasattr(page, "preset_open_requested"):
        connect_signal_once(
            window,
            f"{page_name.name}.preset_open_requested",
            page.preset_open_requested,
            window._open_zapret2_preset_detail,
        )
    if page_name in (PageName.ZAPRET2_USER_PRESETS, PageName.ZAPRET2_ORCHESTRA_USER_PRESETS) and hasattr(page, "folders_open_requested"):
        connect_signal_once(
            window,
            f"{page_name.name}.folders_open_requested",
            page.folders_open_requested,
            window._open_zapret2_preset_folders,
        )

    if page_name == PageName.ZAPRET1_USER_PRESETS and hasattr(page, "preset_open_requested"):
        connect_signal_once(
            window,
            "z1_user_presets.preset_open_requested",
            page.preset_open_requested,
            window._open_zapret1_preset_detail,
        )
    if page_name == PageName.ZAPRET1_USER_PRESETS and hasattr(page, "folders_open_requested"):
        connect_signal_once(
            window,
            "z1_user_presets.folders_open_requested",
            page.folders_open_requested,
            window._open_zapret1_preset_folders,
        )

    if page_name == PageName.ZAPRET2_PRESET_DETAIL and hasattr(page, "back_clicked"):
        connect_signal_once(
            window,
            "z2_preset_detail.back_clicked",
            page.back_clicked,
            window._show_active_zapret2_user_presets_page,
        )

    if page_name == PageName.ZAPRET1_PRESET_DETAIL and hasattr(page, "back_clicked"):
        connect_signal_once(
            window,
            "z1_preset_detail.back_clicked",
            page.back_clicked,
            lambda: window.show_page(PageName.ZAPRET1_USER_PRESETS),
        )
    if page_name == PageName.ZAPRET2_PRESET_FOLDERS and hasattr(page, "back_clicked"):
        connect_signal_once(
            window,
            "z2_preset_folders.back_clicked",
            page.back_clicked,
            window._show_active_zapret2_user_presets_page,
        )
    if page_name == PageName.ZAPRET1_PRESET_FOLDERS and hasattr(page, "back_clicked"):
        connect_signal_once(
            window,
            "z1_preset_folders.back_clicked",
            page.back_clicked,
            window._show_zapret1_user_presets_page,
        )
    if page_name == PageName.ZAPRET2_PRESET_FOLDERS and hasattr(page, "folders_changed"):
        connect_signal_once(
            window,
            "z2_preset_folders.folders_changed",
            page.folders_changed,
            window._refresh_active_zapret2_user_presets_page,
        )
    if page_name == PageName.ZAPRET1_PRESET_FOLDERS and hasattr(page, "folders_changed"):
        connect_signal_once(
            window,
            "z1_preset_folders.folders_changed",
            page.folders_changed,
            window._refresh_zapret1_user_presets_page,
        )

    if page_name in (PageName.ZAPRET2_DIRECT_CONTROL, PageName.ZAPRET2_ORCHESTRA_CONTROL):
        presets_target = (
            PageName.ZAPRET2_ORCHESTRA_USER_PRESETS
            if page_name == PageName.ZAPRET2_ORCHESTRA_CONTROL
            else PageName.ZAPRET2_USER_PRESETS
        )
        direct_launch_target = (
            PageName.ZAPRET2_ORCHESTRA
            if page_name == PageName.ZAPRET2_ORCHESTRA_CONTROL
            else PageName.ZAPRET2_DIRECT
        )

        for button_attr, handler in (
            ("start_btn", window._proxy_start_click),
            ("stop_winws_btn", window._proxy_stop_click),
            ("stop_and_exit_btn", window._proxy_stop_and_exit),
            ("test_btn", window._proxy_test_click),
            ("folder_btn", window._proxy_folder_click),
        ):
            button = getattr(page, button_attr, None)
            signal = getattr(button, "clicked", None)
            if signal is not None:
                connect_signal_once(
                    window,
                    f"{page_name.name}.{button_attr}.clicked",
                    signal,
                    handler,
                )

        if hasattr(page, "navigate_to_presets"):
            connect_signal_once(
                window,
                f"{page_name.name}.navigate_to_presets",
                page.navigate_to_presets,
                lambda target=presets_target: window.show_page(target),
            )

        if hasattr(page, "navigate_to_direct_launch"):
            connect_signal_once(
                window,
                f"{page_name.name}.navigate_to_direct_launch",
                page.navigate_to_direct_launch,
                lambda target=direct_launch_target: window.show_page(target),
            )

        if hasattr(page, "navigate_to_blobs"):
            connect_signal_once(
                window,
                f"{page_name.name}.navigate_to_blobs",
                page.navigate_to_blobs,
                lambda: window.show_page(PageName.BLOBS),
            )

        if page_name == PageName.ZAPRET2_DIRECT_CONTROL and hasattr(page, "direct_mode_changed"):
            connect_signal_once(
                window,
                f"{page_name.name}.direct_mode_changed",
                page.direct_mode_changed,
                window._on_direct_mode_changed,
            )

    if page_name == PageName.ZAPRET1_DIRECT and hasattr(page, "target_clicked"):
        connect_signal_once(
            window,
            "z1_direct.target_clicked",
            page.target_clicked,
            window._open_zapret1_target_detail,
        )

    if page_name == PageName.ZAPRET1_STRATEGY_DETAIL:
        if hasattr(page, "back_clicked"):
            connect_signal_once(
                window,
                "z1_strategy_detail.back_clicked",
                page.back_clicked,
                lambda: window.show_page(PageName.ZAPRET1_DIRECT),
            )
        if hasattr(page, "navigate_to_control"):
            connect_signal_once(
                window,
                "z1_strategy_detail.navigate_to_control",
                page.navigate_to_control,
                lambda: window.show_page(PageName.ZAPRET1_DIRECT_CONTROL),
            )
        if hasattr(page, "strategy_selected"):
            connect_signal_once(
                window,
                "z1_strategy_detail.strategy_selected",
                page.strategy_selected,
                window._on_z1_strategy_detail_selected,
            )

    if page_name == PageName.ZAPRET1_DIRECT_CONTROL:
        for button_attr, handler in (
            ("start_btn", window._proxy_start_click),
            ("stop_winws_btn", window._proxy_stop_click),
            ("stop_and_exit_btn", window._proxy_stop_and_exit),
            ("test_btn", window._proxy_test_click),
            ("folder_btn", window._proxy_folder_click),
        ):
            button = getattr(page, button_attr, None)
            signal = getattr(button, "clicked", None)
            if signal is not None:
                connect_signal_once(
                    window,
                    f"z1_control.{button_attr}.clicked",
                    signal,
                    handler,
                )

        if hasattr(page, "navigate_to_strategies"):
            connect_signal_once(
                window,
                "z1_control.navigate_to_strategies",
                page.navigate_to_strategies,
                lambda: window.show_page(PageName.ZAPRET1_DIRECT),
            )
        if hasattr(page, "navigate_to_presets"):
            connect_signal_once(
                window,
                "z1_control.navigate_to_presets",
                page.navigate_to_presets,
                lambda: window.show_page(PageName.ZAPRET1_USER_PRESETS),
            )

    if page_name == PageName.ZAPRET2_STRATEGY_DETAIL:
        if hasattr(page, "back_clicked"):
            connect_signal_once(
                window,
                "strategy_detail.back_clicked",
                page.back_clicked,
                window._on_strategy_detail_back,
            )
        if hasattr(page, "navigate_to_root"):
            connect_signal_once(
                window,
                "strategy_detail.navigate_to_root",
                page.navigate_to_root,
                lambda: window.show_page(PageName.ZAPRET2_DIRECT_CONTROL),
            )
        if hasattr(page, "strategy_selected"):
            connect_signal_once(
                window,
                "strategy_detail.strategy_selected",
                page.strategy_selected,
                window._on_strategy_detail_selected,
            )
        if hasattr(page, "filter_mode_changed"):
            connect_signal_once(
                window,
                "strategy_detail.filter_mode_changed",
                page.filter_mode_changed,
                window._on_strategy_detail_filter_mode_changed,
            )

    if page_name == PageName.ZAPRET2_ORCHESTRA_STRATEGY_DETAIL:
        if hasattr(page, "back_clicked"):
            connect_signal_once(
                window,
                "orchestra_strategy_detail.back_clicked",
                page.back_clicked,
                lambda: window.show_page(PageName.ZAPRET2_ORCHESTRA),
            )
        if hasattr(page, "navigate_to_root"):
            connect_signal_once(
                window,
                "orchestra_strategy_detail.navigate_to_root",
                page.navigate_to_root,
                lambda: window.show_page(PageName.ZAPRET2_ORCHESTRA_CONTROL),
            )

    if page_name == PageName.ORCHESTRA and hasattr(page, "clear_learned_requested"):
        connect_signal_once(
            window,
            "orchestra.clear_learned_requested",
            page.clear_learned_requested,
            window._on_clear_learned_requested,
        )


def ensure_page(window, name: PageName) -> QWidget | None:
    resolved_name = resolve_page_name(window, name)
    page = window.pages.get(resolved_name)
    if page is not None:
        window._apply_ui_language_to_page(page)
        if bool(getattr(window, "_page_signal_bootstrap_complete", False)):
            ensure_page_in_stacked_widget(window, page)
        return page

    page_class_specs = getattr(window, "_page_class_specs", {}) or {}
    spec = page_class_specs.get(resolved_name)
    if spec is None:
        return None

    attr_name, module_name, class_name = spec
    import time as _time
    _t_page = _time.perf_counter()
    try:
        module = import_module(module_name)
        page_cls = getattr(module, class_name)
        page = page_cls(window)
    except Exception as e:
        fallback_specs = {
            PageName.ZAPRET2_ORCHESTRA_CONTROL: (
                "ui.pages.zapret2.direct_control_page",
                "Zapret2DirectControlPage",
            ),
            PageName.ZAPRET2_ORCHESTRA_USER_PRESETS: (
                "ui.pages.orchestra_zapret2.user_presets_page",
                "OrchestraZapret2UserPresetsPage",
            ),
            PageName.ZAPRET2_ORCHESTRA_STRATEGY_DETAIL: (
                "ui.pages.zapret2.strategy_detail_page",
                "StrategyDetailPage",
            ),
        }
        fallback = fallback_specs.get(resolved_name)
        if not fallback:
            log(f"Ошибка lazy-инициализации страницы {resolved_name}: {e}", "ERROR")
            return None

        log(
            f"Lazy-инициализация страницы {resolved_name} не удалась: {e}. Пробуем fallback...",
            "WARNING",
        )
        try:
            fb_module = import_module(fallback[0])
            fb_cls = getattr(fb_module, fallback[1])
            page = fb_cls(window)
            log(f"Использован fallback для страницы {resolved_name}: {fallback[1]}", "WARNING")
        except Exception as fallback_error:
            log(
                f"Fallback lazy-инициализации страницы {resolved_name} тоже не удался: {fallback_error}",
                "ERROR",
            )
            return None

    route_key = get_page_route_key(window, resolved_name)
    if route_key:
        page.setObjectName(route_key)
    elif not page.objectName():
        page.setObjectName(page.__class__.__name__)

    window.pages[resolved_name] = page
    setattr(window, attr_name, page)
    window._apply_ui_language_to_page(page)

    # Legacy alias
    if resolved_name == PageName.HOSTLIST:
        window.ipset_page = page

    if bool(getattr(window, "_page_signal_bootstrap_complete", False)):
        connect_lazy_page_signals(window, resolved_name, page)
        ensure_page_in_stacked_widget(window, page)

    elapsed_ms = int((_time.perf_counter() - _t_page) * 1000)
    window._record_startup_page_init_metric(resolved_name, elapsed_ms)

    return page
