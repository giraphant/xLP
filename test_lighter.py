#!/usr/bin/env python3
"""
Lighter Exchange Integration Test
测试 Lighter 集成是否正常工作
"""

import asyncio
import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from exchange_interface import create_exchange


async def test_lighter():
    """测试 Lighter 集成"""

    print("="*60)
    print("Lighter Exchange Integration Test")
    print("="*60)
    print()

    # 配置（从环境变量或配置文件读取）
    config = {
        "name": "lighter",
        "private_key": os.getenv("EXCHANGE_PRIVATE_KEY", ""),
        "account_index": int(os.getenv("EXCHANGE_ACCOUNT_INDEX", "0")),
        "api_key_index": int(os.getenv("EXCHANGE_API_KEY_INDEX", "0")),
        "base_url": os.getenv("EXCHANGE_BASE_URL", "https://mainnet.zklighter.elliot.ai"),
    }

    if not config["private_key"]:
        print("❌ Error: EXCHANGE_PRIVATE_KEY not set")
        print()
        print("Please set environment variable:")
        print("  export EXCHANGE_PRIVATE_KEY=your_lighter_private_key")
        print()
        print("Or create .env file with:")
        print("  EXCHANGE_PRIVATE_KEY=your_lighter_private_key")
        return

    try:
        # 创建交易所实例
        print("1. Creating Lighter exchange instance...")
        exchange = create_exchange(config)
        print("✅ Exchange instance created")
        print()

        # 测试获取价格
        print("2. Testing get_price() for SOL...")
        sol_price = await exchange.get_price("SOL")
        print(f"✅ SOL Price: ${sol_price:.2f}")
        print()

        # 测试获取持仓
        print("3. Testing get_position() for SOL...")
        sol_position = await exchange.get_position("SOL")
        print(f"✅ SOL Position: {sol_position:.4f}")
        print()

        # 测试其他币种
        for symbol in ["ETH", "BTC"]:
            print(f"4. Testing {symbol}...")
            price = await exchange.get_price(symbol)
            position = await exchange.get_position(symbol)
            print(f"✅ {symbol} Price: ${price:.2f}, Position: {position:.4f}")
            print()

        print("="*60)
        print("✅ All tests passed!")
        print("="*60)
        print()
        print("Lighter integration is working correctly.")
        print()
        print("Next steps:")
        print("  1. Update config.json with exchange: { 'name': 'lighter', ... }")
        print("  2. Set private_key in config or environment")
        print("  3. Run: docker-compose up -d")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        print()
        print("Common issues:")
        print("  - Invalid private key")
        print("  - Network connection issues")
        print("  - Lighter SDK not installed (run: pip install -r requirements.txt)")


if __name__ == "__main__":
    print()
    print("Make sure you have:")
    print("  1. Installed dependencies: pip install -r requirements.txt")
    print("  2. Set EXCHANGE_PRIVATE_KEY environment variable")
    print()
    input("Press Enter to continue...")
    print()

    asyncio.run(test_lighter())
