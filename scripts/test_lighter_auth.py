#!/usr/bin/env python3
"""
测试 Lighter API 认证
"""
import asyncio
import os
import sys
import logging

# 添加 src 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

logging.basicConfig(level=logging.DEBUG)

async def main():
    import lighter

    print("="*60)
    print("Lighter API 认证测试")
    print("="*60)
    print()

    # 从环境变量读取
    private_key = os.getenv("EXCHANGE_PRIVATE_KEY", "")
    account_index = int(os.getenv("EXCHANGE_ACCOUNT_INDEX", "1"))
    api_key_index = int(os.getenv("EXCHANGE_API_KEY_INDEX", "2"))
    base_url = os.getenv("EXCHANGE_BASE_URL", "https://mainnet.zklighter.elliot.ai")

    if not private_key:
        print("❌ 请设置 EXCHANGE_PRIVATE_KEY 环境变量")
        return

    masked = private_key[:6] + "..." + private_key[-4:] if len(private_key) > 10 else "***"
    print(f"Private Key: {masked}")
    print(f"Account Index: {account_index}")
    print(f"API Key Index: {api_key_index}")
    print(f"Base URL: {base_url}")
    print()

    # 创建客户端
    print("1️⃣  创建 SignerClient...")
    try:
        client = lighter.SignerClient(
            url=base_url,
            private_key=private_key,
            account_index=account_index,
            api_key_index=api_key_index,
        )
        print("✅ SignerClient 创建成功")
    except Exception as e:
        print(f"❌ SignerClient 创建失败: {e}")
        return

    print()
    print("2️⃣  调用 check_client()...")
    try:
        err = client.check_client()
        if err is not None:
            print(f"❌ check_client() 失败: {err}")
            print()
            print("这意味着：")
            print("- API key 在服务器端未找到")
            print("- 或者 account_index/api_key_index 不匹配")
            print()
            print("请确认：")
            print(f"1. 你是否在 Lighter 网站上为 account_index={account_index}, api_key_index={api_key_index} 注册了 API key？")
            print(f"2. 你传入的 private key 对应的 public key 是否和网站上注册的一致？")
            return
        else:
            print("✅ check_client() 成功！API key 已验证")
    except Exception as e:
        print(f"❌ check_client() 异常: {e}")
        import traceback
        traceback.print_exc()
        return

    print()
    print("3️⃣  尝试获取账户信息...")
    try:
        api_client = lighter.ApiClient(configuration=lighter.Configuration(host=base_url))
        account_api = lighter.AccountApi(api_client)

        account = await account_api.account(
            by="index",
            value=str(account_index)
        )

        print(f"✅ 账户信息获取成功")
        print(f"   Account Index: {account_index}")
        if hasattr(account, 'l1_address'):
            print(f"   L1 Address: {account.l1_address}")

        await api_client.close()
    except Exception as e:
        print(f"❌ 获取账户信息失败: {e}")

    print()
    print("="*60)
    print("测试完成")
    print("="*60)

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
