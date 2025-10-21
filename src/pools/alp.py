#!/usr/bin/env python3
"""
ALP对冲计算器
公式: hedge = (owned - locked + shortOI) / totalSupply × alpAmount
其中: shortOI = shortUSD / price
"""

import asyncio
import struct
import sys
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey


# 配置
ALP_MINT = "4yCLi5yWGzpTWMQ1iWHG5CrGYAdBkhyEdsuSugjDUqwj"
ORACLE_ADDR = "GEm9TZP7BL8rTz1JDy6X74PL595zr1putA9BXC8ehDmU"
RPC_URL = "https://api.mainnet-beta.solana.com"
ASSETS_OFFSET = 368
SHORT_POSITION_OFFSET = 600

CUSTODY_ACCOUNTS = {
    "BONK": ("8aJuzsgjxBnvRhDcfQBD7z4CUj7QoPEpaNwVd7KqsSk5", 5),
    "JITOSOL": ("GZ9XfWwgTRhkma2Y91Q9r1XKotNXYjBnKKabj19rhT71", 9),
    "WBTC": ("GFu3qS22mo6bAjg4Lr5R7L8pPgHq6GvbjJPKEHkbbs2c", 8),
}

ORACLE_SYMBOL_OFFSETS = {
    "SOL": 56,      # 需要SOL价格来换算JITOSOL
    "BONK": 312,
    "JITOSOL": 120,
    "WBTC": 248,
}


def parse_u64(data: bytes, offset: int) -> int:
    """解析小端序u64"""
    return struct.unpack('<Q', data[offset:offset+8])[0]


async def get_oracle_prices(client: AsyncClient) -> dict:
    """从Oracle获取价格 (符号-32字节, 除以1e10)"""
    pubkey = Pubkey.from_string(ORACLE_ADDR)
    response = await client.get_account_info(pubkey)

    if not response.value or not response.value.data:
        raise ValueError("Failed to get oracle data")

    data = bytes(response.value.data)

    max_offset = max(ORACLE_SYMBOL_OFFSETS.values())
    if len(data) < max_offset + 8:
        raise ValueError(f"Insufficient oracle data length: {len(data)}")

    prices = {}
    for symbol, symbol_offset in ORACLE_SYMBOL_OFFSETS.items():
        price_offset = symbol_offset - 32
        raw_price = parse_u64(data, price_offset)
        price = raw_price / 1e10

        if price <= 0:
            raise ValueError(f"Invalid price for {symbol}: {price}")

        prices[symbol] = price

    return prices


async def get_alp_supply(client: AsyncClient) -> float:
    """获取ALP总供应量"""
    mint = Pubkey.from_string(ALP_MINT)
    response = await client.get_token_supply(mint)
    if response.value:
        amount = float(response.value.amount)
        decimals = response.value.decimals
        return amount / (10 ** decimals)
    raise ValueError("Failed to get ALP supply")


async def get_custody_data(client: AsyncClient, custody_addr: str, decimals: int, price: float) -> dict:
    """读取custody账户的assets和SHORT Position字段"""
    pubkey = Pubkey.from_string(custody_addr)
    response = await client.get_account_info(pubkey)

    if not response.value or not response.value.data:
        raise ValueError(f"Failed to get custody: {custody_addr}")

    data = bytes(response.value.data)

    if len(data) < max(ASSETS_OFFSET + 24, SHORT_POSITION_OFFSET + 8):
        raise ValueError(f"Insufficient custody data length: {len(data)}")

    # 读取assets字段
    raw_owned = parse_u64(data, ASSETS_OFFSET + 8)
    raw_locked = parse_u64(data, ASSETS_OFFSET + 16)

    if raw_locked > raw_owned:
        raise ValueError("Invalid data: locked > owned")

    # 读取SHORT Position USD值
    raw_short_usd = parse_u64(data, SHORT_POSITION_OFFSET)

    # 转换为代币数量
    owned = raw_owned / (10 ** decimals)
    locked = raw_locked / (10 ** decimals)
    short_usd = raw_short_usd / 1e6
    short_oi = short_usd / price if price > 0 else 0

    return {
        "owned": owned,
        "locked": locked,
        "short_oi": short_oi,
    }


async def calculate_hedge(alp_amount: float) -> dict:
    """计算对冲量"""
    client = AsyncClient(RPC_URL)

    try:
        prices = await get_oracle_prices(client)
        total_supply = await get_alp_supply(client)

        if total_supply <= 0:
            raise ValueError(f"Invalid total supply: {total_supply}")

        hedge_positions = {}
        jitosol_to_sol_ratio = prices["JITOSOL"] / prices["SOL"]

        for symbol, (custody_addr, decimals) in CUSTODY_ACCOUNTS.items():
            price = prices.get(symbol)
            if not price:
                raise ValueError(f"No price for {symbol}")

            data = await get_custody_data(client, custody_addr, decimals, price)
            net_exposure = data["owned"] - data["locked"] + data["short_oi"]
            per_alp = net_exposure / total_supply
            hedge_amount = per_alp * alp_amount

            # JITOSOL转换为SOL
            if symbol == "JITOSOL":
                sol_amount = hedge_amount * jitosol_to_sol_ratio
                if "SOL" in hedge_positions:
                    hedge_positions["SOL"]["amount"] += sol_amount
                    hedge_positions["SOL"]["per_alp"] += per_alp * jitosol_to_sol_ratio
                else:
                    hedge_positions["SOL"] = {
                        "amount": sol_amount,
                        "per_alp": per_alp * jitosol_to_sol_ratio,
                    }
            else:
                # 符号映射：WBTC -> BTC（交易所不支持WBTC）
                exchange_symbol = "BTC" if symbol == "WBTC" else symbol
                hedge_positions[exchange_symbol] = {
                    "amount": hedge_amount,
                    "per_alp": per_alp,
                }

        return hedge_positions

    finally:
        await client.close()


async def main():
    if len(sys.argv) > 1:
        try:
            alp_amount = float(sys.argv[1])
        except ValueError:
            print("Error: Invalid ALP amount", file=sys.stderr)
            sys.exit(1)
    else:
        alp_amount = 1.0

    try:
        positions = await calculate_hedge(alp_amount)

        print(f"ALP: {alp_amount:,.2f}")
        print()

        for symbol, data in positions.items():
            exchange_symbol = "BTC" if symbol == "WBTC" else symbol
            print(f"{exchange_symbol:<8} {data['amount']:>14,.8f}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
