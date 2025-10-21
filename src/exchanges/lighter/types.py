#!/usr/bin/env python3
"""
Type definitions and constants for Lighter exchange
"""

from typing import Dict, TypedDict


class MarketInfo(TypedDict):
    """Market information structure"""
    symbol: str
    size_decimals: int
    price_decimals: int
    base_multiplier: int
    price_multiplier: int


# Required markets to load
REQUIRED_MARKETS = {"BTC", "ETH", "SOL", "1000BONK"}

# Minimum order value in USD (L2 sequencer requirement)
MIN_ORDER_VALUE_USD = 10.0
