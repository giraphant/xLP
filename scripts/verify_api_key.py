#!/usr/bin/env python3
"""
验证 Lighter API key 的 private key 和 public key 是否匹配
"""
import sys
import lighter

def verify_api_key(private_key: str, expected_public_key: str):
    """
    验证 private key 是否能生成预期的 public key

    Args:
        private_key: API key private key
        expected_public_key: 你在 Lighter 网站看到的 public key
    """
    print("="*60)
    print("Lighter API Key 验证工具")
    print("="*60)
    print()

    # 屏蔽私钥显示
    masked_private = private_key[:6] + "..." + private_key[-4:] if len(private_key) > 10 else "***"
    print(f"Private Key: {masked_private}")
    print(f"Expected Public Key: {expected_public_key}")
    print()

    # 使用 Lighter SDK 从 private key 生成 public key
    try:
        # Lighter SDK 没有直接的 private -> public 方法
        # 我们需要创建一个 SignerClient 然后检查
        # 或者使用 create_api_key 生成新的

        # 尝试使用提供的 private key 创建 client
        client = lighter.SignerClient(
            url="https://mainnet.zklighter.elliot.ai",
            private_key=private_key,
            account_index=0,  # 临时值
            api_key_index=0,  # 临时值
        )

        # 获取 public key（如果 SDK 支持）
        if hasattr(client, 'api_public_key'):
            derived_public_key = client.api_public_key
            print(f"Derived Public Key: {derived_public_key}")
            print()

            if derived_public_key.lower() == expected_public_key.lower():
                print("✅ 匹配成功！Private key 和 Public key 对应")
                return True
            else:
                print("❌ 不匹配！Private key 无法生成预期的 Public key")
                print()
                print("可能原因：")
                print("1. 你传入的 Private key 不是这个 API key 的")
                print("2. 你在 Lighter 网站上看到的 Public key 是错误的")
                print("3. 账户或子账户配置错误")
                return False
        else:
            print("⚠️  SDK 没有提供 public key 属性，无法直接验证")
            print()
            print("建议：使用 Lighter 网站上的「验证 API key」功能")
            return None

    except Exception as e:
        print(f"❌ 验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print()
    print("请提供以下信息进行验证：")
    print()

    # 从环境变量或命令行获取
    import os

    private_key = os.getenv("EXCHANGE_PRIVATE_KEY") or input("API Private Key: ").strip()
    expected_public_key = input("Expected Public Key (from Lighter website): ").strip()

    if not private_key or not expected_public_key:
        print("❌ 请提供 private key 和 public key")
        sys.exit(1)

    result = verify_api_key(private_key, expected_public_key)

    if result is True:
        print()
        print("✅ 验证通过！你的配置应该是正确的。")
        print()
        print("如果仍然报错 'api key not found'，请检查：")
        print("1. EXCHANGE_ACCOUNT_INDEX 是否正确（你用的是 1）")
        print("2. EXCHANGE_API_KEY_INDEX 是否正确（你用的是 2）")
        print("3. 是否在正确的 account 和 api_key_index 上注册了这个 public key")
    elif result is False:
        print()
        print("❌ 验证失败！请重新检查你的 API key 配置。")
    else:
        print()
        print("⚠️  无法自动验证，请手动确认。")


if __name__ == "__main__":
    main()
