# launcher_common/builder_factory.py
"""
Factory module for strategy lists.
Выбирает между V1 и V2 реализациями в зависимости от режима.

For backwards compatibility, maintains the same API:
- combine_strategies(**kwargs) - main entry point
- calculate_required_filters(...)
- get_strategy_display_name(...)
- get_active_categories_count(...)
- validate_category_strategies(...)
"""

from log import log
from strategy_menu import get_strategy_launch_method

# Re-export common utilities for backwards compatibility
from .builder_common import (
    calculate_required_filters,
    _apply_settings,
    _clean_spaces,
    get_strategy_display_name,
    get_active_categories_count,
    validate_category_strategies
)

# Import both implementations
from zapret1_launcher.strategy_builder import combine_strategies_v1
from zapret2_launcher.strategy_builder import combine_strategies_v2


def combine_strategies(**kwargs) -> dict:
    """
    Объединяет стратегии всех категорий в единую командную строку.

    Автоматически выбирает V1 или V2 реализацию на основе текущего метода запуска.

    Returns:
        dict с ключами:
        - args: командная строка
        - name: отображаемое имя
        - category_count: количество категорий
        - _is_orchestra: флаг оркестратора (только V2)
    """
    launch_method = get_strategy_launch_method()

    if launch_method == "direct_zapret1":
        log(f"combine_strategies: using V1 (winws.exe)", "DEBUG")
        return combine_strategies_v1(**kwargs)
    else:
        # direct_zapret2, direct_zapret2_orchestra, orchestra
        is_orchestra = launch_method == "direct_zapret2_orchestra"
        log(f"combine_strategies: using V2 (winws2.exe), orchestra={is_orchestra}", "DEBUG")
        return combine_strategies_v2(is_orchestra=is_orchestra, **kwargs)
