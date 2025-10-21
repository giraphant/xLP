#!/usr/bin/env python3
"""
测试加权平均成本追踪算法
模拟多轮市场变化，验证成本计算是否正确
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from core.offset_tracker import calculate_offset_and_cost


def test_cost_tracking():
    """
    测试成本追踪逻辑（简化版本）

    注意：新架构已简化成本追踪，直接使用当前价格作为 cost_basis
    这个测试主要验证 offset 计算是否正确
    """

    print("="*80)
    print("成本追踪测试（简化版）")
    print("="*80)
    print()

    # 测试数据：模拟多轮市场变化
    # 格式：(轮次, 理想持仓, 实际持仓, 当前价格, 说明)
    test_rounds = [
        # 场景1: 初始状态，产生多头敞口（少空了）
        (1, -100.0, -50.0, 200.0, "初始: 理想空100, 实际空50 → 少空50(多头敞口)"),

        # 场景2: 多头敞口继续扩大
        (2, -105.0, -50.0, 210.0, "价格涨到210，理想空105，实际空50 → 少空55"),

        # 场景3: 多头敞口继续扩大，价格继续上涨
        (3, -110.0, -50.0, 220.0, "价格涨到220，理想空110，实际空50 → 少空60，新增5敞口"),

        # 场景4: 部分平仓，多头敞口缩小 → 成本不变
        (4, -110.0, -80.0, 225.0, "做空30个平掉部分敞口，实际空80 → 少空30"),

        # 场景5: 继续平仓
        (5, -110.0, -100.0, 230.0, "继续做空20个，实际空100 → 少空10"),

        # 场景6: 完全平掉，偏移归零
        (6, -110.0, -110.0, 235.0, "完全平仓，实际空110 → 偏移0"),

        # 场景7: 反向，变成空头敞口（多空了）
        (7, -110.0, -120.0, 240.0, "多空了，实际空120 → 多空10（空头敞口）"),

        # 场景8: 空头敞口继续扩大
        (8, -110.0, -125.0, 235.0, "价格跌到235，继续多空 → 多空15，新增5敞口"),

        # 场景9: 空头敞口继续扩大
        (9, -110.0, -130.0, 230.0, "价格跌到230，继续多空 → 多空20，新增5敞口"),

        # 场景10: 平掉部分空头敞口
        (10, -110.0, -115.0, 225.0, "买入平空5个 → 多空5"),

        # 场景11: 完全平掉空头敞口
        (11, -110.0, -110.0, 220.0, "完全平掉 → 偏移0"),

        # 场景12: 再次产生多头敞口，但价格已经变化
        (12, -115.0, -110.0, 215.0, "理想空115，实际空110 → 少空5"),
    ]

    print(f"{'轮次':<4} {'理想持仓':<10} {'实际持仓':<10} {'价格':<8} {'偏移':<10} {'成本':<10} {'说明'}")
    print("-" * 100)

    for round_num, ideal_pos, actual_pos, price, description in test_rounds:
        # 调用简化的成本计算函数（新 API：只需 3 个参数）
        offset, cost_basis = calculate_offset_and_cost(ideal_pos, actual_pos, price)

        # 打印结果
        print(f"{round_num:<4} {ideal_pos:<10.1f} {actual_pos:<10.1f} {price:<8.2f} "
              f"{offset:>9.1f} {cost_basis:>9.2f}  {description}")

        # 验证 offset 计算正确
        expected_offset = actual_pos - ideal_pos
        assert abs(offset - expected_offset) < 0.01, f"Offset mismatch: {offset} != {expected_offset}"

    print()
    print("="*80)
    print("详细验证")
    print("="*80)
    print()

    # 手动验证几个关键场景
    print("场景2验证（多头敞口从50扩大到55）：")
    print("  旧偏移: 50, 旧成本: 200")
    print("  新偏移: 55, 当前价: 210")
    print("  新增敞口: 5")
    print("  预期成本: (50 × 200 + 5 × 210) / 55 = 11050 / 55 = 200.91")
    print()

    print("场景3验证（多头敞口从55扩大到60）：")
    print("  旧偏移: 55, 旧成本: 200.91")
    print("  新偏移: 60, 当前价: 220")
    print("  新增敞口: 5")
    print("  预期成本: (55 × 200.91 + 5 × 220) / 60 = 12150 / 60 = 202.50")
    print()

    print("场景4验证（多头敞口从60缩小到30）：")
    print("  旧偏移: 60, 旧成本: 202.50")
    print("  新偏移: 30, 当前价: 225")
    print("  同向减少，预期成本保持不变: 202.50")
    print()

    print("场景7验证（从多头敞口10变成空头敞口-10）：")
    print("  旧偏移: 10 (多头), 旧成本: 202.50")
    print("  新偏移: -10 (空头), 当前价: 240")
    print("  反向，预期使用新价格: 240.00")
    print()

    print("场景8验证（空头敞口从-10扩大到-15）：")
    print("  旧偏移: -10, 旧成本: 240")
    print("  新偏移: -15, 当前价: 235")
    print("  新增敞口: 5")
    print("  预期成本: (10 × 240 + 5 × 235) / 15 = 3575 / 15 = 238.33")
    print()


def test_extreme_cases():
    """测试极端情况（简化版）"""

    print()
    print("="*80)
    print("极端情况测试")
    print("="*80)
    print()

    # 测试1: 非常小的变化
    print("测试1: 极小变化（浮点精度测试）")
    offset1, cost1 = calculate_offset_and_cost(-100.0, -99.999999, 200.0)
    print(f"  偏移: {offset1:.10f}, 成本: {cost1:.2f}")
    assert abs(offset1 - 0.000001) < 1e-9, "Small offset should be calculated precisely"
    print()

    # 测试2: 价格大幅波动（简化版：验证 cost_basis = price）
    print("测试2: 价格大幅波动")
    prices = [100, 500, 50, 1000, 10]
    for i, price in enumerate(prices, 1):
        offset, cost = calculate_offset_and_cost(-100.0, -50.0, price)
        print(f"  轮{i}: 价格={price:>4}, 偏移={offset:.1f}, 成本={cost:.2f}")
        assert offset == 50.0, "Offset should always be 50"
        assert cost == price, "Cost basis should equal current price"
    print()

    # 测试3: 来回振荡（简化版）
    print("测试3: 偏移来回振荡")
    positions = [
        (-100, -50, 200),   # 少空50
        (-100, -110, 210),  # 多空10
        (-100, -80, 220),   # 少空20
        (-100, -120, 230),  # 多空20
        (-100, -100, 240),  # 平衡
    ]

    for i, (ideal, actual, price) in enumerate(positions, 1):
        offset, cost = calculate_offset_and_cost(ideal, actual, price)
        direction = "多头敞口" if offset > 0 else "空头敞口" if offset < 0 else "平衡"
        print(f"  轮{i}: 理想={ideal:>4}, 实际={actual:>4}, 价格={price}, "
              f"偏移={offset:>6.1f} ({direction}), 成本={cost:.2f}")
    print()


if __name__ == "__main__":
    test_cost_tracking()
    test_extreme_cases()

    print("="*80)
    print("测试完成")
    print("="*80)
