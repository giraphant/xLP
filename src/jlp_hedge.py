#!/usr/bin/env python3
"""
JLP对冲计算器
公式: hedge = (owned - locked + shortOI + fees×0.75) / totalSupply × jlpAmount
"""

import asyncio
import struct
import sys
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey


# 配置
JLP_MINT = "27G8MtK7VtTcCHkpASjSDdkWWYfoqT6ggEuKidVJidD4"
RPC_URL = "https://api.mainnet-beta.solana.com"
ASSETS_OFFSET = 214
FEES_USER_SHARE = 0.75

CUSTODY_ACCOUNTS = {
    "SOL": ("7xS2gz2bTp3fwCC7knJvUWTEU9Tycczu6VhJYKgi1wdz", 9),
    "ETH": ("AQCGyheWPLeo6Qp9WpYS9m3Qj479t7R636N9ey1rEjEn", 8),
    "WBTC": ("5Pv3gM9JrFFH883SWAhvJC9RPYmo8UNxuFtv5bMMALkm", 8),
    "USDC": ("G18jKKXQwBbrHeiK3C9MRXhkHsLHf7XgCSisykV46EZa", 6),
    "USDT": ("4vkNeXiYEUizLdrpdPS1eC2mccyM4NUPRtERrk6ZETkk", 6),
}

STABLECOINS = {"USDC", "USDT"}


def parse_u64(data: bytes, offset: int) -> int:
    """解析小端序u64"""
    return struct.unpack('<Q', data[offset:offset+8])[0]


async def get_jlp_supply(client: AsyncClient) -> float:
    """获取JLP总供应量"""
    mint = Pubkey.from_string(JLP_MINT)
    response = await client.get_token_supply(mint)
    if response.value:
        amount = float(response.value.amount)
        decimals = response.value.decimals
        return amount / (10 ** decimals)
    raise ValueError("Failed to get JLP supply")


async def get_custody_data(client: AsyncClient, custody_addr: str, decimals: int) -> dict:
    """读取custody账户的assets字段"""
    pubkey = Pubkey.from_string(custody_addr)
    response = await client.get_account_info(pubkey)

    if not response.value or not response.value.data:
        raise ValueError(f"Failed to get custody: {custody_addr}")

    data = bytes(response.value.data)

    if len(data) < ASSETS_OFFSET + 48:
        raise ValueError(f"Insufficient data length: {len(data)}")

    # 读取assets字段 (6个连续的u64)
    raw_fees = parse_u64(data, ASSETS_OFFSET)
    raw_owned = parse_u64(data, ASSETS_OFFSET + 8)
    raw_locked = parse_u64(data, ASSETS_OFFSET + 16)
    raw_short_sizes = parse_u64(data, ASSETS_OFFSET + 32)
    raw_short_prices = parse_u64(data, ASSETS_OFFSET + 40)

    if raw_locked > raw_owned:
        raise ValueError("Invalid data: locked > owned")

    # 转换为代币数量
    owned = raw_owned / (10 ** decimals)
    locked = raw_locked / (10 ** decimals)
    fees = (raw_fees / (10 ** decimals)) * FEES_USER_SHARE
    short_oi = raw_short_sizes / raw_short_prices if raw_short_prices > 0 else 0

    return {
        "owned": owned,
        "locked": locked,
        "fees": fees,
        "short_oi": short_oi,
    }


async def calculate_hedge(jlp_amount: float) -> dict:
    """计算对冲量"""
    client = AsyncClient(RPC_URL)

    try:
        total_supply = await get_jlp_supply(client)

        if total_supply <= 0:
            raise ValueError(f"Invalid total supply: {total_supply}")

        hedge_positions = {}

        for symbol, (custody_addr, decimals) in CUSTODY_ACCOUNTS.items():
            if symbol in STABLECOINS:
                continue

            data = await get_custody_data(client, custody_addr, decimals)
            net_exposure = data["owned"] - data["locked"] + data["short_oi"] + data["fees"]
            per_jlp = net_exposure / total_supply
            hedge_amount = per_jlp * jlp_amount

            hedge_positions[symbol] = {
                "amount": hedge_amount,
                "per_jlp": per_jlp,
            }

        return hedge_positions

    finally:
        await client.close()


async def main():
    if len(sys.argv) > 1:
        try:
            jlp_amount = float(sys.argv[1])
        except ValueError:
            print("Error: Invalid JLP amount", file=sys.stderr)
            sys.exit(1)
    else:
        jlp_amount = 1.0

    try:
        positions = await calculate_hedge(jlp_amount)

        print(f"JLP: {jlp_amount:,.2f}")
        print()

        for symbol, data in positions.items():
            exchange_symbol = "BTC" if symbol == "WBTC" else symbol
            print(f"{exchange_symbol:<8} {data['amount']:>14,.8f}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
