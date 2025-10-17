#!/usr/bin/env python3
"""
详细的成本追踪测试案例
手动验证每个计算步骤
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from offset_tracker import calculate_offset_and_cost


def verify_calculation(old_offset, old_cost, new_offset, delta_offset, price, expected_cost):
    """手动验证计算"""
    if abs(new_offset) < 1e-8:
        calculated = 0.0
    else:
        calculated = (old_offset * old_cost + delta_offset * price) / new_offset

    print(f"  公式: ({old_offset} × {old_cost} + {delta_offset} × {price}) / {new_offset}")
    print(f"  计算: ({old_offset * old_cost} + {delta_offset * price}) / {new_offset} = {calculated:.2f}")
    print(f"  预期: {expected_cost:.2f}")

    if abs(calculated - expected_cost) < 0.01:
        print(f"  ✓ 验证通过")
    else:
        print(f"  ✗ 验证失败！差异: {abs(calculated - expected_cost):.2f}")

    return calculated


def test_case_1():
    """案例1: 多头敞口从无到有，逐步扩大，然后缩小"""
    print("="*80)
    print("案例1: 多头敞口（少空）从建立到平仓")
    print("="*80)
    print()

    scenarios = [
        # (ideal, actual, price, description)
        (-100, -50, 200, "初始：理想空100，实际空50 → 少空50"),
        (-100, -50, 210, "价格涨到210，持仓不变 → 成本不变"),
        (-110, -50, 220, "理想变110，实际不变 → 少空60（新增10个敞口）"),
        (-110, -70, 215, "做空20个 → 少空40（平掉20个敞口）"),
        (-110, -90, 205, "再做空20个 → 少空20（再平20个）"),
        (-110, -110, 200, "完全平仓 → 偏移归零"),
    ]

    old_offset = 0.0
    old_cost = 0.0

    for i, (ideal, actual, price, desc) in enumerate(scenarios, 1):
        print(f"\n轮{i}: {desc}")
        print(f"  理想持仓: {ideal}, 实际持仓: {actual}, 价格: ${price}")

        offset, cost = calculate_offset_and_cost(ideal, actual, price, old_offset, old_cost)
        delta = offset - old_offset

        print(f"  偏移: {old_offset:.1f} → {offset:.1f} (delta: {delta:+.1f})")
        print(f"  成本: ${old_cost:.2f} → ${cost:.2f}")

        # 手动验证
        if i == 1:
            print(f"  首次建仓，成本 = 当前价 = {price}")
        elif abs(offset) < 1e-8:
            print(f"  偏移归零，成本 = 0")
        elif abs(delta) < 1e-8:
            print(f"  偏移不变，成本不变 = {old_cost}")
        else:
            verify_calculation(old_offset, old_cost, offset, delta, price, cost)

        old_offset = offset
        old_cost = cost


def test_case_2():
    """案例2: 空头敞口（多空了）"""
    print("\n\n")
    print("="*80)
    print("案例2: 空头敞口（多空）从建立到平仓")
    print("="*80)
    print()

    scenarios = [
        (-100, -120, 200, "初始：理想空100，实际空120 → 多空20"),
        (-100, -125, 190, "价格跌到190，继续多空 → 多空25（新增5个敞口）"),
        (-100, -130, 180, "价格继续跌到180 → 多空30（新增5个）"),
        (-100, -120, 185, "买入平空10个 → 多空20（平掉10个）"),
        (-100, -110, 195, "再买入10个 → 多空10（再平10个）"),
        (-100, -100, 200, "完全平掉 → 偏移归零"),
    ]

    old_offset = 0.0
    old_cost = 0.0

    for i, (ideal, actual, price, desc) in enumerate(scenarios, 1):
        print(f"\n轮{i}: {desc}")
        print(f"  理想持仓: {ideal}, 实际持仓: {actual}, 价格: ${price}")

        offset, cost = calculate_offset_and_cost(ideal, actual, price, old_offset, old_cost)
        delta = offset - old_offset

        print(f"  偏移: {old_offset:.1f} → {offset:.1f} (delta: {delta:+.1f})")
        print(f"  成本: ${old_cost:.2f} → ${cost:.2f}")

        if i == 1:
            print(f"  首次建仓，成本 = 当前价 = {price}")
        elif abs(offset) < 1e-8:
            print(f"  偏移归零，成本 = 0")
        elif abs(delta) < 1e-8:
            print(f"  偏移不变，成本不变 = {old_cost}")
        else:
            verify_calculation(old_offset, old_cost, offset, delta, price, cost)

        old_offset = offset
        old_cost = cost


def test_case_3():
    """案例3: 你提出的极端案例"""
    print("\n\n")
    print("="*80)
    print("案例3: 价格快速下跌，多头敞口被动平仓（你的例子）")
    print("="*80)
    print()

    print("场景：价格200 → 100 → 50，多头敞口从100收缩到50")
    print()

    # 第1轮：在100美金发现100个多头敞口
    print("轮1: 价格100，出现100个多头敞口")
    offset1, cost1 = calculate_offset_and_cost(-100, 0, 100, 0, 0)
    print(f"  偏移: 0 → {offset1:.1f}")
    print(f"  成本: $0 → ${cost1:.2f}")
    print(f"  ✓ 首次建仓，成本 = 当前价 = 100")
    print()

    # 第2轮：价格跌到50，敞口缩小到50
    print("轮2: 价格跌到50，多头敞口缩小到50")
    print("  说明：理想持仓可能也变了，但最终结果是敞口从100缩小到50")
    print("  这意味着在50的价格被动平掉了50个敞口")
    offset2, cost2 = calculate_offset_and_cost(-100, -50, 50, offset1, cost1)
    delta = offset2 - offset1
    print(f"  偏移: {offset1:.1f} → {offset2:.1f} (delta: {delta:+.1f})")
    print(f"  成本: ${cost1:.2f} → ${cost2:.2f}")
    print()
    verify_calculation(offset1, cost1, offset2, delta, 50, 150)
    print()

    print("含义解析：")
    print("  - 原本100个敞口在100建立，总成本 = 100 × 100 = 10,000")
    print("  - 在50平掉了50个，回收 = 50 × 50 = 2,500")
    print("  - 剩余50个，剩余成本 = (10,000 - 2,500) / 50 = 150")
    print("  - 需要价格涨到150才能回本！")
    print()
    print("  如果价格回到100：")
    print("    - 剩余50个在100平掉，损失 = 50 × (150 - 100) = 2,500")
    print("    - 前面已经损失 = 50 × (100 - 50) = 2,500")
    print("    - 总损失 = 5,000（正好是100个敞口从100跌到50的损失）✓")


def test_case_4():
    """案例4: 多空反转"""
    print("\n\n")
    print("="*80)
    print("案例4: 多头敞口反转为空头敞口")
    print("="*80)
    print()

    scenarios = [
        (-100, -50, 200, "开始：少空50（多头敞口）"),
        (-100, -80, 210, "做空30个，少空20"),
        (-100, -110, 220, "继续做空，变成多空10（反转）"),
        (-100, -120, 215, "继续多空，多空20"),
        (-100, -90, 205, "买回平空，又变回少空10（再次反转）"),
    ]

    old_offset = 0.0
    old_cost = 0.0

    for i, (ideal, actual, price, desc) in enumerate(scenarios, 1):
        print(f"\n轮{i}: {desc}")
        print(f"  理想: {ideal}, 实际: {actual}, 价格: ${price}")

        offset, cost = calculate_offset_and_cost(ideal, actual, price, old_offset, old_cost)
        delta = offset - old_offset

        direction = "多头敞口(少空)" if offset > 0 else "空头敞口(多空)" if offset < 0 else "平衡"
        print(f"  偏移: {old_offset:+.1f} → {offset:+.1f} (delta: {delta:+.1f}) [{direction}]")
        print(f"  成本: ${old_cost:.2f} → ${cost:.2f}")

        # 判断是否反转
        if old_offset * offset < 0:
            print(f"  ⚠️ 发生反转！从{('多头' if old_offset > 0 else '空头')}变为{('多头' if offset > 0 else '空头')}")

        if i == 1:
            print(f"  首次建仓")
        elif abs(delta) < 1e-8:
            print(f"  偏移不变")
        else:
            verify_calculation(old_offset, old_cost, offset, delta, price, cost)

        old_offset = offset
        old_cost = cost


def test_case_5():
    """案例5: 价格剧烈波动下的成本变化"""
    print("\n\n")
    print("="*80)
    print("案例5: 价格剧烈波动，分批平仓的成本变化")
    print("="*80)
    print()

    print("场景：持有100个多头敞口（成本200），价格大幅波动，分批平仓")
    print()

    # 初始状态
    offset = 100.0
    cost = 200.0

    print(f"初始: 偏移={offset:.1f}, 成本=${cost:.2f}")
    print()

    close_scenarios = [
        (250, 20, "价格涨到250，平掉20个（赚了）"),
        (180, 30, "价格跌到180，平掉30个（亏了）"),
        (220, 40, "价格回到220，平掉40个"),
        (200, 10, "价格回到200，平掉最后10个"),
    ]

    for i, (price, close_amount, desc) in enumerate(close_scenarios, 1):
        print(f"轮{i}: {desc}")

        old_offset = offset
        old_cost = cost

        # 计算新的偏移（这里理想持仓不变，只是实际平仓）
        new_offset = old_offset - close_amount
        delta = -close_amount

        if abs(new_offset) < 1e-8:
            new_cost = 0.0
        else:
            new_cost = (old_offset * old_cost + delta * price) / new_offset

        print(f"  价格: ${price}, 平掉: {close_amount}个")
        print(f"  偏移: {old_offset:.1f} → {new_offset:.1f}")
        print(f"  成本: ${old_cost:.2f} → ${new_cost:.2f}")

        # 计算这次平仓的盈亏
        pnl = close_amount * (price - old_cost)
        print(f"  本次盈亏: {close_amount} × (${price} - ${old_cost:.2f}) = ${pnl:+.2f}")

        if new_offset > 0:
            print(f"  剩余{new_offset:.0f}个需要在${new_cost:.2f}才能回本")

        verify_calculation(old_offset, old_cost, new_offset, delta, price, new_cost)

        offset = new_offset
        cost = new_cost
        print()


if __name__ == "__main__":
    test_case_1()
    test_case_2()
    test_case_3()
    test_case_4()
    test_case_5()

    print("\n" + "="*80)
    print("所有测试完成")
    print("="*80)
