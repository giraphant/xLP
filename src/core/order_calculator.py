#!/usr/bin/env python3
"""
订单计算器 - 纯函数

计算订单的价格和数量。
零依赖，100%可测试。
"""


def calculate_order_price(
    cost_basis: float,
    offset: float,
    price_offset_pct: float
) -> float:
    """
    计算挂单价格

    Args:
        cost_basis: 成本基础
        offset: 偏移量
            > 0: 多头敞口，需要卖出平仓
            < 0: 空头敞口，需要买入平仓
        price_offset_pct: 价格偏移百分比 (例如: 0.2 表示0.2%)

    Returns:
        挂单价格

    Logic:
        - 如果offset > 0 (多头敞口): 需要卖出，挂高价 = cost * (1 + pct/100)
        - 如果offset < 0 (空头敞口): 需要买入，挂低价 = cost * (1 - pct/100)

    Examples:
        >>> calculate_order_price(100.0, 10.5, 0.2)  # 多头，卖出
        100.2

        >>> calculate_order_price(100.0, -10.5, 0.2)  # 空头，买入
        99.8
    """
    if offset > 0:
        # 多头敞口：需要卖出平仓，挂高价
        return cost_basis * (1 + price_offset_pct / 100)
    else:
        # 空头敞口：需要买入平仓，挂低价
        return cost_basis * (1 - price_offset_pct / 100)


def calculate_order_size(
    offset: float,
    close_ratio: float
) -> float:
    """
    计算平仓数量

    Args:
        offset: 偏移量（正数或负数）
        close_ratio: 平仓比例 (例如: 40.0 表示40%)

    Returns:
        应平仓的数量（绝对值）

    Examples:
        >>> calculate_order_size(10.5, 40.0)
        4.2

        >>> calculate_order_size(-8.0, 50.0)
        4.0
    """
    return abs(offset) * (close_ratio / 100)


def calculate_order_side(offset: float) -> str:
    """
    根据偏移量计算订单方向

    Args:
        offset: 偏移量
            > 0: 多头敞口
            < 0: 空头敞口

    Returns:
        "sell" 或 "buy"

    Examples:
        >>> calculate_order_side(10.5)
        'sell'

        >>> calculate_order_side(-8.0)
        'buy'
    """
    return "sell" if offset > 0 else "buy"
