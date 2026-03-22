"""Orchestra Zapret2 pages.

Thin wrappers over Zapret2 pages to keep a dedicated namespace for
direct_zapret2_orchestra preset flow.
"""

from .direct_control_page import OrchestraZapret2DirectControlPage
from .strategy_detail_page import OrchestraZapret2StrategyDetailPage

__all__ = [
    "OrchestraZapret2DirectControlPage",
    "OrchestraZapret2StrategyDetailPage",
]
