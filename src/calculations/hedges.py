"""
Hedge calculation functions

Pure functions for calculating ideal hedge positions from pool data.
"""
from typing import Dict, Any


def calculate_ideal_hedges(pool_data: Dict[str, Dict[str, Any]]) -> Dict[str, float]:
    """
    计算理想对冲量（合并所有池子）

    Pure function extracted from CalculateIdealHedgesStep

    策略：
    - 合并 JLP 和 ALP 池子的持仓
    - 符号规范化（WBTC → BTC）
    - 对冲方向为负（做空对冲多头敞口）

    Args:
        pool_data: 池子数据字典
            {
                "jlp": {"SOL": {"amount": 10.5}, "BTC": ...},
                "alp": {"SOL": {"amount": 5.2}, ...}
            }

    Returns:
        理想对冲量字典（负数表示做空）
            {
                "SOL": -15.7,  # 做空 15.7 SOL
                "BTC": -0.5,   # 做空 0.5 BTC
                ...
            }

    Examples:
        >>> pool_data = {
        ...     "jlp": {"SOL": {"amount": 10.0}, "WBTC": {"amount": 0.5}},
        ...     "alp": {"SOL": {"amount": 5.0}}
        ... }
        >>> calculate_ideal_hedges(pool_data)
        {'SOL': -15.0, 'BTC': -0.5}  # WBTC merged into BTC
    """
    merged_hedges = {}

    for pool_type, positions in pool_data.items():
        for symbol, data in positions.items():
            # 符号规范化：WBTC → BTC
            exchange_symbol = "BTC" if symbol == "WBTC" else symbol

            # 初始化
            if exchange_symbol not in merged_hedges:
                merged_hedges[exchange_symbol] = 0

            # 提取数量（兼容不同数据结构）
            amount = data["amount"] if isinstance(data, dict) else data

            # 对冲方向为负（做空）
            hedge_amount = -amount

            # 累加
            merged_hedges[exchange_symbol] += hedge_amount

    return merged_hedges
