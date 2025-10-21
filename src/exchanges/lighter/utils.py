#!/usr/bin/env python3
"""
Utility functions for Lighter exchange
"""


def convert_1000x_size(symbol: str, size: float, to_lighter: bool) -> float:
    """
    Convert size for 1000X markets (e.g., 1000BONK)

    On Lighter: 1 unit of 1000BONK = 1000 actual BONK tokens

    Args:
        symbol: Market symbol
        size: Size to convert
        to_lighter: True to convert to Lighter format (divide by 1000),
                   False to convert from Lighter format (multiply by 1000)

    Returns:
        Converted size
    """
    if symbol.startswith("1000"):
        return size / 1000 if to_lighter else size * 1000
    return size
