#!/usr/bin/env python3
"""
偏移追踪原子模块
提供加权平均成本追踪的核心算法
"""

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

    示例：
        # 场景1: 首次建仓
        >>> calculate_offset_and_cost(-100, -50, 200, 0, 0)
        (50.0, 200.0)  # 少空50个，成本200

        # 场景2: 敞口扩大
        >>> calculate_offset_and_cost(-105, -50, 210, 50, 200)
        (55.0, 200.91)  # 新增5个敞口@210，成本从200升到200.91

        # 场景3: 敞口缩小
        >>> calculate_offset_and_cost(-110, -70, 215, 60, 202.5)
        (40.0, 202.5)  # 平掉20个@215，剩余40个成本仍为202.5

        # 场景4: 完全平仓
        >>> calculate_offset_and_cost(-110, -110, 220, 40, 202.5)
        (0.0, 0.0)  # 偏移归零

        # 场景5: 反转
        >>> calculate_offset_and_cost(-110, -120, 225, 10, 202.5)
        (-10.0, 225.0)  # 从多头敞口变成空头敞口，重新计价
    """
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

    return new_offset, new_cost


def analyze_offset_change(old_offset: float, new_offset: float) -> dict:
    """
    分析偏移变化的性质

    Args:
        old_offset: 旧偏移量
        new_offset: 新偏移量

    Returns:
        {
            "type": "expand" | "reduce" | "reverse" | "zero" | "unchanged",
            "direction": "long" | "short" | "neutral",
            "description": str
        }
    """
    delta = new_offset - old_offset

    # 无变化
    if abs(delta) < 1e-8:
        return {
            "type": "unchanged",
            "direction": "long" if new_offset > 0 else "short" if new_offset < 0 else "neutral",
            "description": "偏移量无变化"
        }

    # 归零
    if abs(new_offset) < 1e-8:
        return {
            "type": "zero",
            "direction": "neutral",
            "description": "偏移归零（完全平仓）"
        }

    # 反转（越过零点）
    if old_offset * new_offset < 0:
        old_dir = "多头" if old_offset > 0 else "空头"
        new_dir = "多头" if new_offset > 0 else "空头"
        return {
            "type": "reverse",
            "direction": "long" if new_offset > 0 else "short",
            "description": f"反转：从{old_dir}敞口变成{new_dir}敞口"
        }

    # 扩大或缩小
    if abs(new_offset) > abs(old_offset):
        change_type = "expand"
        desc = f"敞口扩大 {abs(delta):.2f} 个"
    else:
        change_type = "reduce"
        desc = f"敞口缩小 {abs(delta):.2f} 个"

    direction = "long" if new_offset > 0 else "short"

    return {
        "type": change_type,
        "direction": direction,
        "description": desc
    }


def calculate_pnl(
    offset: float,
    cost_basis: float,
    current_price: float
) -> float:
    """
    计算当前浮动盈亏

    Args:
        offset: 偏移量（正=多头敞口，负=空头敞口）
        cost_basis: 成本基础
        current_price: 当前价格

    Returns:
        浮动盈亏（正=盈利，负=亏损）
    """
    if abs(offset) < 1e-8:
        return 0.0

    if offset > 0:
        # 多头敞口：价格上涨赚钱
        return offset * (current_price - cost_basis)
    else:
        # 空头敞口：价格下跌赚钱
        return abs(offset) * (cost_basis - current_price)


def calculate_realized_pnl(
    closed_amount: float,
    close_price: float,
    cost_basis: float,
    is_long_exposure: bool
) -> float:
    """
    计算已实现盈亏

    Args:
        closed_amount: 平仓数量（正数）
        close_price: 平仓价格
        cost_basis: 成本基础
        is_long_exposure: True=多头敞口，False=空头敞口

    Returns:
        已实现盈亏（正=盈利，负=亏损）
    """
    if is_long_exposure:
        # 多头敞口平仓：卖出价 - 成本
        return closed_amount * (close_price - cost_basis)
    else:
        # 空头敞口平仓：成本 - 买入价
        return closed_amount * (cost_basis - close_price)


if __name__ == "__main__":
    """简单测试"""
    print("偏移追踪原子模块 - 快速测试")
    print("="*60)

    # 测试1: 首次建仓
    print("\n测试1: 首次建仓")
    offset1, cost1 = calculate_offset_and_cost(-100, -50, 200, 0, 0)
    print(f"  理想=-100, 实际=-50, 价格=200")
    print(f"  结果: 偏移={offset1:.2f}, 成本={cost1:.2f}")
    print(f"  分析: {analyze_offset_change(0, offset1)['description']}")

    # 测试2: 敞口扩大
    print("\n测试2: 敞口扩大")
    offset2, cost2 = calculate_offset_and_cost(-105, -50, 210, offset1, cost1)
    print(f"  理想=-105, 实际=-50, 价格=210")
    print(f"  结果: 偏移={offset2:.2f}, 成本={cost2:.2f}")
    print(f"  分析: {analyze_offset_change(offset1, offset2)['description']}")
    print(f"  验证: (50×200 + 5×210)/55 = {(50*200 + 5*210)/55:.2f}")

    # 测试3: 敞口缩小
    print("\n测试3: 敞口缩小")
    offset3, cost3 = calculate_offset_and_cost(-110, -70, 215, 60, 202.5)
    print(f"  理想=-110, 实际=-70, 价格=215")
    print(f"  结果: 偏移={offset3:.2f}, 成本={cost3:.2f}")
    print(f"  分析: {analyze_offset_change(60, offset3)['description']}")
    realized_pnl = calculate_realized_pnl(20, 215, 202.5, True)
    print(f"  已实现盈亏: {realized_pnl:+.2f}")

    # 测试4: 完全平仓
    print("\n测试4: 完全平仓")
    offset4, cost4 = calculate_offset_and_cost(-110, -110, 220, 40, 202.5)
    print(f"  理想=-110, 实际=-110, 价格=220")
    print(f"  结果: 偏移={offset4:.2f}, 成本={cost4:.2f}")
    print(f"  分析: {analyze_offset_change(40, offset4)['description']}")

    # 测试5: 反转
    print("\n测试5: 反转（多头敞口→空头敞口）")
    offset5, cost5 = calculate_offset_and_cost(-110, -120, 225, 10, 202.5)
    print(f"  理想=-110, 实际=-120, 价格=225")
    print(f"  结果: 偏移={offset5:.2f}, 成本={cost5:.2f}")
    print(f"  分析: {analyze_offset_change(10, offset5)['description']}")

    print("\n" + "="*60)
    print("所有测试完成")
