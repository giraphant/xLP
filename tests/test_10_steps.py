#!/usr/bin/env python3
"""
完整的10步案例
详细展示每一步的计算过程
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from utils.calculators import calculate_offset_and_cost


def print_step_header(step_num, title):
    """打印步骤标题"""
    print("\n" + "="*80)
    print(f"步骤 {step_num}: {title}")
    print("="*80)


def print_calculation(old_offset, old_cost, new_offset, delta_offset, price, new_cost):
    """详细打印计算过程"""
    print(f"\n【计算过程】")
    print(f"  旧偏移: {old_offset:+.2f}")
    print(f"  旧成本: ${old_cost:.2f}")
    print(f"  当前价格: ${price:.2f}")
    print(f"  新偏移: {new_offset:+.2f}")
    print(f"  delta偏移: {delta_offset:+.2f}")
    print()

    if abs(old_offset) < 1e-8:
        print(f"  公式: 首次建仓，成本 = 当前价格")
        print(f"  结果: 成本 = ${price:.2f}")
    elif abs(new_offset) < 1e-8:
        print(f"  公式: 偏移归零")
        print(f"  结果: 成本 = $0.00")
    elif abs(delta_offset) < 1e-8:
        print(f"  公式: 偏移不变，成本不变")
        print(f"  结果: 成本 = ${old_cost:.2f}")
    else:
        print(f"  公式: 新成本 = (旧偏移 × 旧成本 + delta偏移 × 当前价格) / 新偏移")
        print(f"  代入: 新成本 = ({old_offset:+.2f} × {old_cost:.2f} + {delta_offset:+.2f} × {price:.2f}) / {new_offset:+.2f}")

        numerator = old_offset * old_cost + delta_offset * price
        print(f"  计算分子: {old_offset:+.2f} × {old_cost:.2f} = {old_offset * old_cost:.2f}")
        print(f"           {delta_offset:+.2f} × {price:.2f} = {delta_offset * price:.2f}")
        print(f"           分子 = {old_offset * old_cost:.2f} + {delta_offset * price:.2f} = {numerator:.2f}")
        print(f"  计算分母: {new_offset:+.2f}")
        print(f"  结果: {numerator:.2f} / {new_offset:+.2f} = ${new_cost:.2f}")


def main():
    print("="*80)
    print("完整的10步成本追踪案例")
    print("="*80)
    print()
    print("场景说明：")
    print("  - 跟踪SOL的对冲，理想持仓从-100变化到不同水平")
    print("  - 实际持仓根据操作变化")
    print("  - 价格随市场波动")
    print("  - 观察偏移和成本如何变化")
    print()

    # 定义10步场景
    steps = [
        # (ideal, actual, price, description)
        (-100, -50, 200.00, "市场开盘，理想空100，实际空50 → 少空50（多头敞口50）"),
        (-105, -50, 205.00, "理想增加到空105，实际不变 → 少空55（多头敞口扩大5个）"),
        (-110, -50, 210.00, "理想继续增加到110，实际不变 → 少空60（多头敞口再扩5个）"),
        (-110, -70, 208.00, "执行做空20个 → 少空40（多头敞口缩小20个）"),
        (-110, -85, 215.00, "继续做空15个 → 少空25（多头敞口再缩15个）"),
        (-110, -110, 220.00, "完全平掉多头敞口 → 偏移归零"),
        (-110, -115, 218.00, "过度做空5个 → 多空5（变成空头敞口）"),
        (-110, -120, 212.00, "继续多空 → 多空10（空头敞口扩大5个）"),
        (-110, -115, 215.00, "买入平空5个 → 多空5（空头敞口缩小5个）"),
        (-110, -110, 210.00, "完全平掉空头敞口 → 偏移归零"),
    ]

    old_offset = 0.0
    old_cost = 0.0

    for step_num, (ideal, actual, price, description) in enumerate(steps, 1):
        print_step_header(step_num, description)

        print(f"\n【市场状态】")
        print(f"  理想持仓: {ideal:.2f} (应该空{abs(ideal):.0f}个)")
        print(f"  实际持仓: {actual:.2f} (实际空{abs(actual):.0f}个)")
        print(f"  当前价格: ${price:.2f}")

        # 计算偏移
        new_offset, new_cost = calculate_offset_and_cost(
            ideal, actual, price, old_offset, old_cost
        )
        delta_offset = new_offset - old_offset

        print(f"\n【偏移分析】")
        if new_offset > 0:
            print(f"  偏移类型: 多头敞口（少空了）")
            print(f"  偏移量: {new_offset:+.2f} (少空{abs(new_offset):.0f}个)")
            print(f"  含义: 相当于持有{abs(new_offset):.0f}个多头仓位")
        elif new_offset < 0:
            print(f"  偏移类型: 空头敞口（多空了）")
            print(f"  偏移量: {new_offset:+.2f} (多空{abs(new_offset):.0f}个)")
            print(f"  含义: 相当于持有{abs(new_offset):.0f}个额外空头仓位")
        else:
            print(f"  偏移类型: 完美对冲（无偏移）")
            print(f"  偏移量: 0")
            print(f"  含义: 实际持仓等于理想持仓")

        if delta_offset != 0:
            if abs(delta_offset) > 0:
                if (old_offset > 0 and delta_offset > 0) or (old_offset < 0 and delta_offset < 0):
                    print(f"  变化: 敞口扩大了{abs(delta_offset):.0f}个")
                elif (old_offset > 0 and delta_offset < 0) or (old_offset < 0 and delta_offset > 0):
                    if old_offset * new_offset > 0:
                        print(f"  变化: 敞口缩小了{abs(delta_offset):.0f}个")
                    else:
                        print(f"  变化: 反转！从{'多头' if old_offset > 0 else '空头'}敞口变成{'多头' if new_offset > 0 else '空头'}敞口")

        # 详细计算过程
        print_calculation(old_offset, old_cost, new_offset, delta_offset, price, new_cost)

        print(f"\n【成本解读】")
        if new_cost > 0 and new_offset > 0:
            print(f"  多头敞口成本: ${new_cost:.2f}")
            print(f"  需要价格涨到: ${new_cost:.2f} 才能回本")
            print(f"  当前价格: ${price:.2f}")
            pnl_per_unit = price - new_cost
            total_pnl = pnl_per_unit * abs(new_offset)
            print(f"  当前浮动盈亏: {abs(new_offset):.0f} × ({price:.2f} - {new_cost:.2f}) = ${total_pnl:+.2f}")
        elif new_cost > 0 and new_offset < 0:
            print(f"  空头敞口成本: ${new_cost:.2f}")
            print(f"  需要价格跌到: ${new_cost:.2f} 才能回本")
            print(f"  当前价格: ${price:.2f}")
            pnl_per_unit = new_cost - price
            total_pnl = pnl_per_unit * abs(new_offset)
            print(f"  当前浮动盈亏: {abs(new_offset):.0f} × ({new_cost:.2f} - {price:.2f}) = ${total_pnl:+.2f}")
        elif abs(new_offset) < 1e-8:
            print(f"  无偏移，无需关注成本")
            if old_cost > 0:
                final_pnl = old_offset * (price - old_cost) if old_offset > 0 else old_offset * (old_cost - price)
                print(f"  上一轮偏移已完全平仓，最终盈亏: ${final_pnl:+.2f}")

        print(f"\n【总结】")
        print(f"  偏移: {old_offset:+.2f} → {new_offset:+.2f}")
        print(f"  成本: ${old_cost:.2f} → ${new_cost:.2f}")
        if delta_offset > 0:
            print(f"  操作: 新增{abs(delta_offset):.0f}个敞口 @ ${price:.2f}")
        elif delta_offset < 0:
            print(f"  操作: 平掉{abs(delta_offset):.0f}个敞口 @ ${price:.2f}")
            if old_cost > 0:
                realized_pnl = abs(delta_offset) * (price - old_cost) if old_offset > 0 else abs(delta_offset) * (old_cost - price)
                print(f"  实现盈亏: {abs(delta_offset):.0f} × ({'$' + str(price) + ' - $' + str(old_cost) if old_offset > 0 else '$' + str(old_cost) + ' - $' + str(price)}) = ${realized_pnl:+.2f}")

        # 更新状态
        old_offset = new_offset
        old_cost = new_cost

    print("\n\n")
    print("="*80)
    print("10步完整案例结束")
    print("="*80)
    print()
    print("关键观察：")
    print("  1. 扩大敞口时，成本是加权平均")
    print("  2. 缩小敞口时，高价平→成本降低，低价平→成本升高")
    print("  3. 反转时（越过零点），成本会重新计算")
    print("  4. 公式统一：新成本 = (旧偏移 × 旧成本 + delta × 价格) / 新偏移")


if __name__ == "__main__":
    main()
