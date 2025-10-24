#!/usr/bin/env python3
"""
Zone 计算器独立测试脚本

用法：
    python test_zone_calculator.py
"""
import sys
sys.path.insert(0, 'src')

from utils.calculators.zone import (
    calculate_zone,
    calculate_previous_zone_from_order,
    calculate_previous_zone_from_fill,
    calculate_previous_zone
)
from datetime import datetime, timedelta


def test_calculate_zone():
    """测试基础 zone 计算"""
    print("=" * 60)
    print("测试1: calculate_zone()")
    print("=" * 60)

    # 测试用例（threshold_min=200, threshold_max=4000, step=100）
    test_cases = [
        (150, None, "低于阈值"),
        (200, 0, "刚好达到阈值"),
        (250, 0, "第0个区间"),
        (300, 1, "第1个区间"),
        (350, 1, "第1个区间"),
        (400, 2, "第2个区间"),
        (4000, 38, "最高阈值"),
        (4500, -1, "超过阈值")
    ]

    for offset_usd, expected, desc in test_cases:
        result = calculate_zone(offset_usd, 200, 4000, 100)
        status = "✅" if result == expected else "❌"
        print(f"{status} offset_usd=${offset_usd} → zone={result} (expected={expected}) - {desc}")

    print()


def test_calculate_previous_zone_from_order():
    """测试从订单计算 previous_zone"""
    print("=" * 60)
    print("测试2: calculate_previous_zone_from_order()")
    print("=" * 60)

    # 测试用例
    # case 1: 你提供的真实案例
    # 0.314 SOL @ $191, close_ratio=20%
    # offset = 0.314 / 0.2 = 1.57
    # offset_usd = 1.57 * 191 = 299.87
    # zone = (299.87 - 200) / 100 = 0

    order_size = 0.314
    order_price = 191
    close_ratio = 20.0
    result = calculate_previous_zone_from_order(
        order_size, order_price, close_ratio,
        200, 4000, 100
    )
    print(f"案例1: order_size={order_size}, order_price=${order_price}, close_ratio={close_ratio}%")
    print(f"  计算: offset={order_size/0.2:.4f}, offset_usd={order_size/0.2*order_price:.2f}")
    print(f"  结果: zone={result} (expected=0 or 1)")
    print()

    # case 2: 更大的订单
    order_size = 1.0
    order_price = 200
    result = calculate_previous_zone_from_order(
        order_size, order_price, close_ratio,
        200, 4000, 100
    )
    print(f"案例2: order_size={order_size}, order_price=${order_price}, close_ratio={close_ratio}%")
    print(f"  计算: offset={order_size/0.2:.4f}, offset_usd={order_size/0.2*order_price:.2f}")
    print(f"  结果: zone={result} (expected=8)")
    print()


def test_calculate_previous_zone_from_fill():
    """测试从成交计算 previous_zone"""
    print("=" * 60)
    print("测试3: calculate_previous_zone_from_fill()")
    print("=" * 60)

    fill_size = 0.5
    fill_price = 180
    close_ratio = 20.0
    result = calculate_previous_zone_from_fill(
        fill_size, fill_price, close_ratio,
        200, 4000, 100
    )
    print(f"案例: fill_size={fill_size}, fill_price=${fill_price}, close_ratio={close_ratio}%")
    print(f"  计算: offset={fill_size/0.2:.4f}, offset_usd={fill_size/0.2*fill_price:.2f}")
    print(f"  结果: zone={result} (expected=2)")
    print()


def test_calculate_previous_zone_integration():
    """测试统一接口（三优先级）"""
    print("=" * 60)
    print("测试4: calculate_previous_zone() - 统一接口")
    print("=" * 60)

    # 案例1: 有活跃订单
    print("案例1: 有活跃订单")
    active_orders = [{"size": 0.314, "price": 191}]
    recent_fills = []
    result = calculate_previous_zone(
        active_orders, recent_fills,
        close_ratio=20.0,
        threshold_min=200, threshold_max=4000, threshold_step=100,
        cooldown_minutes=5
    )
    print(f"  有订单: {active_orders[0]}")
    print(f"  结果: zone={result}")
    print()

    # 案例2: 有冷却期内成交
    print("案例2: 冷却期内有成交（无订单）")
    active_orders = []
    recent_fills = [{
        "filled_size": 0.5,
        "filled_price": 180,
        "filled_at": datetime.now() - timedelta(minutes=3)  # 3分钟前
    }]
    result = calculate_previous_zone(
        active_orders, recent_fills,
        close_ratio=20.0,
        threshold_min=200, threshold_max=4000, threshold_step=100,
        cooldown_minutes=5
    )
    print(f"  有成交（3分钟前）: filled_size={recent_fills[0]['filled_size']}, filled_price={recent_fills[0]['filled_price']}")
    print(f"  结果: zone={result}")
    print()

    # 案例3: 成交已过冷却期
    print("案例3: 成交已过冷却期（无订单）")
    active_orders = []
    recent_fills = [{
        "filled_size": 0.5,
        "filled_price": 180,
        "filled_at": datetime.now() - timedelta(minutes=10)  # 10分钟前
    }]
    result = calculate_previous_zone(
        active_orders, recent_fills,
        close_ratio=20.0,
        threshold_min=200, threshold_max=4000, threshold_step=100,
        cooldown_minutes=5
    )
    print(f"  有成交（10分钟前，已过冷却期）")
    print(f"  结果: zone={result} (expected=0)")
    print()

    # 案例4: 都没有
    print("案例4: 无订单无成交")
    active_orders = []
    recent_fills = []
    result = calculate_previous_zone(
        active_orders, recent_fills,
        close_ratio=20.0,
        threshold_min=200, threshold_max=4000, threshold_step=100,
        cooldown_minutes=5
    )
    print(f"  结果: zone={result} (expected=0)")
    print()


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("ZONE 计算器测试套件")
    print("配置: threshold_min=200, threshold_max=4000, step=100, close_ratio=20%")
    print("=" * 60 + "\n")

    test_calculate_zone()
    test_calculate_previous_zone_from_order()
    test_calculate_previous_zone_from_fill()
    test_calculate_previous_zone_integration()

    print("=" * 60)
    print("测试完成")
    print("=" * 60)
