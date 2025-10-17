#!/usr/bin/env python3
"""
注册 Lighter API Key 到服务器
需要主钱包私钥来签名交易
"""
import asyncio
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

async def main():
    import lighter

    print("="*60)
    print("Lighter API Key 注册工具")
    print("="*60)
    print()

    # 获取配置
    eth_private_key = os.getenv("ETH_PRIVATE_KEY", "")
    api_key_private_key = os.getenv("EXCHANGE_PRIVATE_KEY", "")
    account_index = int(os.getenv("EXCHANGE_ACCOUNT_INDEX", "1"))
    api_key_index = int(os.getenv("EXCHANGE_API_KEY_INDEX", "2"))
    base_url = os.getenv("EXCHANGE_BASE_URL", "https://mainnet.zklighter.elliot.ai")

    if not eth_private_key:
        print("❌ 请设置 ETH_PRIVATE_KEY 环境变量（你的主钱包私钥）")
        print()
        print("这个私钥用于签名注册交易，不是 API key 的私钥！")
        return

    if not api_key_private_key:
        print("❌ 请设置 EXCHANGE_PRIVATE_KEY 环境变量")
        return

    print("配置信息:")
    print(f"  Account Index: {account_index}")
    print(f"  API Key Index: {api_key_index}")
    print(f"  Base URL: {base_url}")
    print()

    # 从 API key private key 派生 public key
    # 注意：Lighter SDK 没有直接的 private->public 方法
    # 我们需要创建一个 SignerClient 来让 SDK 内部处理

    print("1️⃣  创建 SignerClient...")
    try:
        client = lighter.SignerClient(
            url=base_url,
            private_key=api_key_private_key,
            account_index=account_index,
            api_key_index=api_key_index,
        )
        print("✅ SignerClient 创建成功")
    except Exception as e:
        print(f"❌ 创建失败: {e}")
        return

    print()
    print("2️⃣  调用 change_api_key() 注册 API key...")
    print("    这需要用你的主钱包签名交易...")

    try:
        # change_api_key 需要:
        # - eth_private_key: 主钱包私钥（用于签名交易）
        # - new_pubkey: 新的 API key 的 public key

        # 问题：SDK 没有直接方法从 private key 获取 public key
        # 我们需要用另一种方式

        print()
        print("⚠️  注意：")
        print("Lighter SDK 需要你提供 API key 的 public key 来注册。")
        print()
        print("如果你是在网站上生成的 key，public key 应该在网站上显示了。")
        print("请确认你的 public key 是:")
        print("  c203937c22d3dc784b8c73cb2ca782ffff1248b2a1f4c4f7e8a67383524838e342989bafd3ca6f48")
        print()

        # 尝试使用网站显示的 public key
        new_public_key = "c203937c22d3dc784b8c73cb2ca782ffff1248b2a1f4c4f7e8a67383524838e342989bafd3ca6f48"

        # 如果 public key 不带 0x，尝试加上
        if not new_public_key.startswith('0x'):
            new_public_key = '0x' + new_public_key

        print(f"使用 public key: {new_public_key}")
        print()

        response, err = await client.change_api_key(
            eth_private_key=eth_private_key,
            new_pubkey=new_public_key,
        )

        if err is not None:
            print(f"❌ 注册失败: {err}")
            return

        print("✅ 注册交易已提交！")
        print(f"   Response: {response}")
        print()
        print("3️⃣  等待交易确认（10秒）...")

        import time
        time.sleep(10)

        print()
        print("4️⃣  验证 API key 是否成功注册...")

        err = client.check_client()
        if err is None:
            print("✅✅✅ 成功！API key 已注册并验证通过！")
            print()
            print(f"你现在可以使用:")
            print(f"  EXCHANGE_PRIVATE_KEY={api_key_private_key[:6]}...{api_key_private_key[-4:]}")
            print(f"  EXCHANGE_ACCOUNT_INDEX={account_index}")
            print(f"  EXCHANGE_API_KEY_INDEX={api_key_index}")
        else:
            print(f"❌ 验证失败: {err}")
            print()
            print("可能需要等待更长时间让交易确认。")
            print("请等待1-2分钟后手动运行 check_client() 测试。")

        await client.close()

    except Exception as e:
        print(f"❌ 注册过程出错: {e}")
        import traceback
        traceback.print_exc()
        await client.close()
        return

if __name__ == "__main__":
    print()
    print("⚠️  重要提示：")
    print("此脚本需要两个私钥：")
    print("1. ETH_PRIVATE_KEY - 你的主钱包私钥（用于签名注册交易）")
    print("2. EXCHANGE_PRIVATE_KEY - API key 的私钥（要注册的 key）")
    print()
    print("如果不确定，请先咨询后再运行！")
    print()

    confirm = input("是否继续？(yes/no): ")
    if confirm.lower() not in ['yes', 'y']:
        print("已取消")
        sys.exit(0)

    asyncio.run(main())
