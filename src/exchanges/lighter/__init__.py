#!/usr/bin/env python3
"""
Lighter Exchange Integration
Based on: https://github.com/your-quantguy/perp-dex-tools

This module provides a clean interface to interact with Lighter exchange.
"""

from .orders import LighterOrderManager
from .types import MarketInfo, REQUIRED_MARKETS, MIN_ORDER_VALUE_USD
from .utils import convert_1000x_size


class LighterClient(LighterOrderManager):
    """
    Lighter Exchange Client

    Unified interface combining:
    - Client initialization (LighterBaseClient)
    - Market data management (LighterMarketManager)
    - Order operations (LighterOrderManager)
    """
    pass


# Public API
__all__ = [
    'LighterClient',
    'MarketInfo',
    'REQUIRED_MARKETS',
    'MIN_ORDER_VALUE_USD',
    'convert_1000x_size',
]
