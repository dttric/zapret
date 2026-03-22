"""
SearchQuery re-export for backward compatibility.

The SearchQuery class is defined in filter_engine.py but imported here
to maintain the import path used in strategy_info.py.
"""

from strategy_menu.filter_engine import SearchQuery

__all__ = ["SearchQuery"]
