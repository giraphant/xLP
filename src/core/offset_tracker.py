#!/usr/bin/env python3
"""
Offset计算 - 纯函数

职责：
- 计算实际仓位与理想仓位的偏差
- 计算cost basis
- 简单明了的数学计算

特点：
- 纯函数（无副作用）
- 零依赖
- 100%可测试
"""


def calculate_offset_and_cost(
    ideal: float,
    actual: float,
    price: float
) -> tuple[float, float]:
    """
    计算offset和cost basis

    Args:
        ideal: 理想仓位
        actual: 实际仓位
        price: 当前价格

    Returns:
        (offset, cost_basis)
        - offset: actual - ideal (正数表示多头，负数表示空头)
        - cost_basis: 用于计算订单价格的基准价
    """
    offset = actual - ideal
    cost_basis = price  # 简化版本：直接使用当前价格

    return offset, cost_basis


def calculate_offset_usd(offset: float, price: float) -> float:
    """
    计算offset的USD价值

    Args:
        offset: 仓位偏差
        price: 当前价格

    Returns:
        offset的绝对USD价值
    """
    return abs(offset) * price


def calculate_ideal_position(
    pool_hedge: float,
    portfolio_multiplier: float = 1.0
) -> float:
    """
    计算理想仓位

    Args:
        pool_hedge: 池子计算的对冲数量
        portfolio_multiplier: 投资组合乘数（用于缩放）

    Returns:
        理想仓位
    """
    return pool_hedge * portfolio_multiplier
