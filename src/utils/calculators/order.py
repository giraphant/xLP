"""
订单参数计算工具

纯函数，用于计算订单的数量和价格参数
"""


def calculate_close_size(offset: float, close_ratio: float) -> float:
    """
    计算平仓数量（纯函数）

    Args:
        offset: 敞口数量
        close_ratio: 平仓比例（百分比）

    Returns:
        平仓数量
    """
    return abs(offset) * (close_ratio / 100.0)


def calculate_limit_price(offset: float, cost_basis: float, price_offset_percent: float) -> float:
    """
    计算限价单价格（纯函数）

    Args:
        offset: 敞口（正数=多头，负数=空头）
        cost_basis: 成本价
        price_offset_percent: 价格偏移百分比

    Returns:
        限价单价格
    """
    if offset > 0:
        # 多头敞口：需要卖出平仓，挂高价
        return cost_basis * (1 + price_offset_percent / 100)
    else:
        # 空头敞口：需要买入平仓，挂低价
        return cost_basis * (1 - price_offset_percent / 100)
