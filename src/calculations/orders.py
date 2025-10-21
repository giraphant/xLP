"""
Order calculation functions

Pure functions for calculating order sizes and prices.
"""


def calculate_close_size(offset: float, close_ratio: float) -> float:
    """
    计算平仓数量

    Pure function extracted from DecisionEngine.calculate_close_size()

    Args:
        offset: 偏移量（正数或负数）
        close_ratio: 平仓比例（百分比，如 40.0 表示 40%）

    Returns:
        应平仓的数量（绝对值）

    Examples:
        >>> calculate_close_size(10.0, 40.0)
        4.0  # 10 * 0.4 = 4

        >>> calculate_close_size(-5.0, 100.0)
        5.0  # 全部平仓
    """
    return abs(offset) * (close_ratio / 100.0)


def calculate_limit_price(
    offset: float,
    cost_basis: float,
    price_offset_percent: float
) -> float:
    """
    计算限价单价格

    Pure function extracted from DecisionEngine.calculate_order_price()

    策略：
    - LONG敞口（offset > 0）：需要卖出平仓，挂高于成本的价格
    - SHORT敞口（offset < 0）：需要买入平仓，挂低于成本的价格

    Args:
        offset: 偏移量（正=多头敞口，负=空头敞口）
        cost_basis: 成本基础价格
        price_offset_percent: 价格偏移百分比（如 0.2 表示 0.2%）

    Returns:
        挂单价格

    Examples:
        >>> calculate_limit_price(10.0, 100.0, 0.2)
        100.2  # 多头敞口，挂高价: 100 * (1 + 0.002)

        >>> calculate_limit_price(-5.0, 100.0, 0.2)
        99.8  # 空头敞口，挂低价: 100 * (1 - 0.002)
    """
    if offset > 0:
        # 多头敞口：需要卖出平仓，挂高价
        return cost_basis * (1 + price_offset_percent / 100)
    else:
        # 空头敞口：需要买入平仓，挂低价
        return cost_basis * (1 - price_offset_percent / 100)
