# launcher_common/builder_common.py

"""
Common utilities for strategy lists - shared between V1 and V2.
"""

import re
import os
from log import log
from .constants import LABEL_RECOMMENDED, LABEL_GAME, LABEL_CAUTION, LABEL_EXPERIMENTAL, LABEL_STABLE
from strategy_menu.strategies_registry import registry
from .blobs import build_args_with_deduped_blobs


def calculate_required_filters(category_strategies: dict) -> dict:
    """
    Автоматически вычисляет нужные фильтры портов на основе выбранных категорий.

    Использует filters_config.py для определения какие фильтры нужны.

    Args:
        category_strategies: dict {category_key: strategy_id}

    Returns:
        dict с флагами фильтров
    """
    from .port_filters import get_filter_for_category, FILTERS

    # Инициализируем все фильтры как False
    filters = {key: False for key in FILTERS.keys()}

    none_strategies = registry.get_none_strategies()

    for category_key, strategy_id in category_strategies.items():
        # Пропускаем неактивные категории
        if not strategy_id:
            continue
        none_id = none_strategies.get(category_key)
        if strategy_id == none_id or strategy_id == "none":
            continue

        # Получаем информацию о категории
        category_info = registry.get_category_info(category_key)
        if not category_info:
            continue

        # Получаем нужные фильтры через конфиг
        required_filters = get_filter_for_category(category_info)
        for filter_key in required_filters:
            filters[filter_key] = True

    log(f"Автоматически определены фильтры: TCP=[80={filters.get('tcp_80')}, 443={filters.get('tcp_443')}, 6568={filters.get('tcp_6568')}, warp={filters.get('tcp_warp')}, all={filters.get('tcp_all_ports')}], "
        f"UDP=[443={filters.get('udp_443')}, all={filters.get('udp_all_ports')}], "
        f"raw=[discord={filters.get('raw_discord')}, stun={filters.get('raw_stun')}, wg={filters.get('raw_wireguard')}]", "DEBUG")

    return filters


def _apply_settings(args: str) -> str:
    """
    Применяет все пользовательские настройки к командной строке.

    Обрабатывает:
    - Добавление --wssize 1:6
    """
    from strategy_menu import (
        get_wssize_enabled,
    )

    result = args

    # ==================== ДОБАВЛЕНИЕ WSSIZE ====================
    if get_wssize_enabled():
        # Добавляем --wssize 1:6 для TCP 443
        # Ищем место после базовых аргументов
        if "--wssize" not in result:
            # Вставляем после --wf-* аргументов
            if "--wf-" in result:
                # Находим конец wf аргументов
                wf_end = 0
                for match in re.finditer(r'--wf-[^\s]+=[^\s]+', result):
                    wf_end = max(wf_end, match.end())

                if wf_end > 0:
                    result = result[:wf_end] + " --wssize 1:6" + result[wf_end:]
                else:
                    result = "--wssize 1:6 " + result
            else:
                result = "--wssize 1:6 " + result

            log("Добавлен параметр --wssize 1:6", "DEBUG")

    # ==================== ФИНАЛЬНАЯ ОЧИСТКА ====================
    result = _clean_spaces(result)

    # Удаляем пустые --new (если вдруг после модификаций остались)
    result = re.sub(r'--new\s+--new', '--new', result)
    result = re.sub(r'\s+--new\s*$', '', result)  # Trailing --new
    result = re.sub(r'^--new\s+', '', result)  # Leading --new

    return result.strip()


def _clean_spaces(text: str) -> str:
    """Очищает множественные пробелы"""
    return ' '.join(text.split())


def get_strategy_display_name(category_key: str, strategy_id: str) -> str:
    """Получает отображаемое имя стратегии"""
    if strategy_id == "none":
        return "Отключено"

    return registry.get_strategy_name_safe(category_key, strategy_id)


def get_active_categories_count(category_strategies: dict) -> int:
    """Подсчитывает количество активных категорий"""
    none_strategies = registry.get_none_strategies()
    count = 0

    for category_key, strategy_id in category_strategies.items():
        if strategy_id and strategy_id != none_strategies.get(category_key):
            count += 1

    return count


def validate_category_strategies(category_strategies: dict) -> list:
    """
    Проверяет корректность выбранных стратегий.
    Возвращает список ошибок (пустой если всё ок).
    """
    errors = []

    for category_key, strategy_id in category_strategies.items():
        if not strategy_id:
            continue

        if strategy_id == "none":
            continue

        # Проверяем существование категории
        category_info = registry.get_category_info(category_key)
        if not category_info:
            errors.append(f"Неизвестная категория: {category_key}")
            continue

        # Проверяем существование стратегии
        args = registry.get_strategy_args_safe(category_key, strategy_id)
        if args is None:
            errors.append(f"Стратегия '{strategy_id}' не найдена в категории '{category_key}'")

    return errors
