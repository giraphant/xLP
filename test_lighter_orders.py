#!/usr/bin/env python3
"""
测试 Lighter API 订单数据结构

直接在 Docker 容器里运行，使用环境变量中的 API key
"""
import asyncio
import sys
sys.path.insert(0, '/app/src')

from exchanges.lighter.adapter import LighterExchangeAdapter


async def main():
    print("=" * 60)
    print("测试 Lighter API 订单数据结构")
    print("=" * 60)

    # 初始化 adapter
    adapter = LighterExchangeAdapter()
    await adapter.initialize()

    print("\n✅ Lighter client 初始化成功")
    print(f"Account index: {adapter.lighter_client.account_index}")

    # 获取 SOL 的活跃订单
    print("\n" + "=" * 60)
    print("获取 SOL 活跃订单...")
    print("=" * 60)

    orders = await adapter.get_open_orders("SOL")

    if not orders:
        print("❌ 没有找到活跃订单")
        return

    print(f"\n✅ 找到 {len(orders)} 个订单\n")

    for i, order in enumerate(orders, 1):
        print(f"订单 #{i}:")
        print(f"  order_id: {order.get('order_id')}")
        print(f"  symbol: {order.get('symbol')}")
        print(f"  side: {order.get('side')}")
        print(f"  size: {order.get('size')}")
        print(f"  price: {order.get('price')}")
        print(f"  created_at: {order.get('created_at')}")
        print()

    # 直接访问原始 API 看数据
    print("=" * 60)
    print("直接调用 Lighter API 查看原始数据")
    print("=" * 60)

    market_id = await adapter._get_market_id("SOL")
    auth_token, _ = adapter.lighter_client.client.create_auth_token_with_expiry()

    response = await adapter.lighter_client.client.order_api.account_active_orders(
        account_index=adapter.lighter_client.account_index,
        market_id=market_id,
        authorization=auth_token
    )

    if response and hasattr(response, 'orders') and response.orders:
        raw_order = response.orders[0]
        print(f"\n原始订单对象 (第一个):")
        print(f"  类型: {type(raw_order)}")
        print(f"  所有属性: {[attr for attr in dir(raw_order) if not attr.startswith('_')]}")
        print()

        # 打印关键字段
        print("关键字段值:")
        for attr in ['base_size', 'remaining_base_amount', 'price', 'order_index', 'is_ask', 'timestamp']:
            if hasattr(raw_order, attr):
                value = getattr(raw_order, attr)
                print(f"  {attr}: {value} (type: {type(value).__name__})")
        print()

        # 获取市场信息
        market_info = await adapter.lighter_client.get_market_info("SOL")
        print(f"SOL 市场信息:")
        print(f"  base_multiplier: {market_info['base_multiplier']}")
        print(f"  size_decimals: {market_info['size_decimals']}")
        print(f"  price_multiplier: {market_info['price_multiplier']}")
        print()

        # 手动计算正确的 size
        if hasattr(raw_order, 'remaining_base_amount'):
            raw_base_amount = raw_order.remaining_base_amount
            correct_size = raw_base_amount / market_info['base_multiplier']
            print(f"正确计算:")
            print(f"  remaining_base_amount: {raw_base_amount}")
            print(f"  正确 size = {raw_base_amount} / {market_info['base_multiplier']} = {correct_size:.4f} SOL")
            print()

        if hasattr(raw_order, 'base_size'):
            print(f"base_size 字段值: {raw_order.base_size}")
            print(f"  (如果这个值正确，就应该直接用这个)")
            print()


if __name__ == "__main__":
    asyncio.run(main())
