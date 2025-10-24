#!/usr/bin/env python3
"""
Lighter API 诊断脚本 - 独立测试所有 API 调用

用法：
1. 创建 .env.test 文件，填入测试账户的 API 信息
2. 运行：python3 test_lighter_api.py

这个脚本会：
- 测试所有 API 调用（价格、持仓、订单、成交）
- 打印原始返回数据
- 验证字段解析是否正确
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from exchanges.lighter.adapter import LighterExchange


async def test_api():
    """测试所有 Lighter API 调用"""

    print("=" * 80)
    print("Lighter API 诊断测试")
    print("=" * 80)

    # 从环境变量读取配置
    import os
    from dotenv import load_dotenv

    # 尝试加载 .env.test（本地测试），否则使用环境变量（Docker）
    env_file = Path(__file__).parent / '.env.test'
    if env_file.exists():
        print(f"加载本地配置: {env_file}")
        load_dotenv(env_file)
    else:
        # Docker 环境，从环境变量读取
        print("使用 Docker 环境变量")

    config = {
        "private_key": os.getenv("EXCHANGE_PRIVATE_KEY"),
        "account_index": int(os.getenv("EXCHANGE_ACCOUNT_INDEX", "0")),
        "api_key_index": int(os.getenv("EXCHANGE_API_KEY_INDEX", "0")),
        "base_url": os.getenv("EXCHANGE_BASE_URL", "https://mainnet.zklighter.elliot.ai")
    }

    if not config["private_key"]:
        print("❌ 错误：EXCHANGE_PRIVATE_KEY 未设置")
        print("\nDocker 运行方式：")
        print("  docker exec -it xlp-prod python3 test_lighter_api.py")
        print("\n本地运行方式：")
        print("  1. cp .env.test.example .env.test")
        print("  2. 编辑 .env.test 填入测试账户信息")
        print("  3. python3 test_lighter_api.py")
        return

    print(f"\n配置：")
    print(f"  - Account Index: {config['account_index']}")
    print(f"  - API Key Index: {config['api_key_index']}")
    print(f"  - Base URL: {config['base_url']}")

    # 创建 adapter
    exchange = LighterExchange(config)

    # 测试币种
    test_symbols = ["SOL", "BTC", "ETH", "BONK"]

    print("\n" + "=" * 80)
    print("测试 1: 获取价格和持仓")
    print("=" * 80)

    for symbol in test_symbols:
        try:
            print(f"\n{symbol}:")
            price = await exchange.get_price(symbol)
            position = await exchange.get_position(symbol)
            print(f"  ✅ Price: ${price:,.2f}")
            print(f"  ✅ Position: {position:+.4f}")
        except Exception as e:
            print(f"  ❌ Error: {e}")

    print("\n" + "=" * 80)
    print("测试 2: 获取活跃订单（单个币种）")
    print("=" * 80)

    for symbol in test_symbols:
        try:
            print(f"\n{symbol}:")
            orders = await exchange.get_open_orders(symbol)
            print(f"  ✅ 返回 {len(orders)} 个订单")

            if orders:
                print("\n  订单详情：")
                for i, order in enumerate(orders[:3], 1):  # 只显示前3个
                    print(f"\n  订单 {i}:")
                    print(f"    - order_id: {order.get('order_id')}")
                    print(f"    - symbol: {order.get('symbol')}")
                    print(f"    - side: {order.get('side')}")
                    print(f"    - size: {order.get('size')}")
                    print(f"    - price: {order.get('price')}")
                    print(f"    - created_at: {order.get('created_at')}")
                    print(f"    - status: {order.get('status')}")

                    # 验证关键字段
                    assert order.get('symbol') == symbol, f"Symbol 不匹配：{order.get('symbol')} != {symbol}"
                    assert isinstance(order.get('created_at'), datetime), f"created_at 不是 datetime: {type(order.get('created_at'))}"
                    assert isinstance(order.get('size'), (int, float)), f"size 不是数字: {type(order.get('size'))}"

                if len(orders) > 3:
                    print(f"\n  ... 还有 {len(orders) - 3} 个订单")
        except Exception as e:
            print(f"  ❌ Error: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 80)
    print("测试 3: 获取所有活跃订单（无参数）")
    print("=" * 80)

    try:
        all_orders = await exchange.get_open_orders()
        print(f"\n✅ 返回 {len(all_orders)} 个订单（所有币种）")

        # 按币种统计
        symbol_counts = {}
        for order in all_orders:
            symbol = order.get('symbol')
            symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1

        print("\n按币种统计：")
        for symbol, count in sorted(symbol_counts.items()):
            print(f"  - {symbol}: {count} 个订单")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 80)
    print("测试 4: 获取最近成交（单个币种）")
    print("=" * 80)

    for symbol in test_symbols:
        try:
            print(f"\n{symbol}:")
            fills = await exchange.get_recent_fills(symbol, minutes_back=60)
            print(f"  ✅ 返回 {len(fills)} 笔成交（最近60分钟）")

            if fills:
                print("\n  成交详情：")
                for i, fill in enumerate(fills[:3], 1):  # 只显示前3笔
                    print(f"\n  成交 {i}:")
                    print(f"    - order_id: {fill.get('order_id')}")
                    print(f"    - symbol: {fill.get('symbol')}")
                    print(f"    - side: {fill.get('side')}")
                    print(f"    - filled_size: {fill.get('filled_size')}")
                    print(f"    - filled_price: {fill.get('filled_price')}")
                    print(f"    - filled_at: {fill.get('filled_at')}")

                    # 验证关键字段
                    assert fill.get('symbol') == symbol, f"Symbol 不匹配：{fill.get('symbol')} != {symbol}"
                    assert isinstance(fill.get('filled_at'), datetime), f"filled_at 不是 datetime: {type(fill.get('filled_at'))}"
                    assert isinstance(fill.get('filled_size'), (int, float)), f"filled_size 不是数字: {type(fill.get('filled_size'))}"

                if len(fills) > 3:
                    print(f"\n  ... 还有 {len(fills) - 3} 笔成交")
        except Exception as e:
            print(f"  ❌ Error: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 80)
    print("测试 5: 获取所有成交（无参数）")
    print("=" * 80)

    try:
        all_fills = await exchange.get_recent_fills(minutes_back=60)
        print(f"\n✅ 返回 {len(all_fills)} 笔成交（所有币种，最近60分钟）")

        # 按币种统计
        symbol_counts = {}
        for fill in all_fills:
            symbol = fill.get('symbol')
            symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1

        print("\n按币种统计：")
        for symbol, count in sorted(symbol_counts.items()):
            print(f"  - {symbol}: {count} 笔成交")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 80)
    print("测试完成！")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_api())
