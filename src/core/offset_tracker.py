#!/usr/bin/env python3
"""
偏移追踪原子模块
提供加权平均成本追踪的核心算法
"""

import math
from typing import Tuple


def calculate_offset_and_cost(
    ideal_position: float,
    actual_position: float,
    current_price: float,
    old_offset: float,
    old_cost: float
) -> Tuple[float, float]:
    """
    计算新的偏移量和加权平均成本（原子操作）

    这是整个对冲系统的核心算法，使用统一公式处理所有场景：
    新成本 = (旧偏移 × 旧成本 + delta偏移 × 当前价格) / 新偏移

    Args:
        ideal_position: 理想持仓（负数=做空）
        actual_position: 实际持仓（负数=做空）
        current_price: 当前市场价格
        old_offset: 旧的偏移量
        old_cost: 旧的成本基础

    Returns:
        (new_offset, new_cost_basis)

        new_offset:
            > 0: 多头敞口（少空了，相当于持有多头）
            < 0: 空头敞口（多空了，相当于持有额外空头）
            = 0: 完美对冲

        new_cost_basis:
            偏移敞口的加权平均成本
            用于计算盈亏和设置平仓价格

    Raises:
        ValueError: 输入参数无效（价格非正、包含NaN/Infinity、成本为负）
    """
    # 0. 输入验证
    if current_price <= 0:
        raise ValueError(f"Invalid current_price: {current_price} (must be positive)")

    if old_cost < 0:
        raise ValueError(f"Invalid old_cost: {old_cost} (must be non-negative)")

    # 检查所有输入是否为有限数值
    if not all(math.isfinite(x) for x in [ideal_position, actual_position, current_price, old_offset, old_cost]):
        raise ValueError(f"Non-finite input detected: ideal={ideal_position}, actual={actual_position}, "
                        f"price={current_price}, old_offset={old_offset}, old_cost={old_cost}")

    # 1. 计算新偏移
    new_offset = actual_position - ideal_position
    delta_offset = new_offset - old_offset

    # 2. 特殊情况处理

    # 情况A: 偏移没有变化
    if abs(delta_offset) < 1e-8:
        return new_offset, old_cost

    # 情况B: 偏移归零（完全平仓）
    if abs(new_offset) < 1e-8:
        return 0.0, 0.0

    # 情况C: 之前无偏移，首次建仓
    if abs(old_offset) < 1e-8:
        return new_offset, current_price

    # 3. 统一成本计算公式
    # 新成本 = (旧偏移 × 旧成本 + delta偏移 × 当前价格) / 新偏移
    #
    # 这个公式自动处理所有场景：
    #   - delta > 0 且同向：扩大敞口，加权平均推高/降成本
    #   - delta < 0 且同向：缩小敞口，成本不变（已实现盈亏分离）
    #   - 反向（越过零点）：delta和new_offset符号导致重新计价
    new_cost = (old_offset * old_cost + delta_offset * current_price) / new_offset

    # 4. 输出验证（可选但推荐）
    if new_cost < 0:
        raise ValueError(f"Calculated negative cost: {new_cost}. Inputs: old_offset={old_offset}, "
                        f"old_cost={old_cost}, delta_offset={delta_offset}, current_price={current_price}, "
                        f"new_offset={new_offset}")

    return new_offset, new_cost
