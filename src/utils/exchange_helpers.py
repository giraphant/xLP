#!/usr/bin/env python3
"""
交易所辅助函数 - 替代 ExchangeClient

职责：
- 订单确认装饰器（双重确认逻辑）
- 辅助函数（批量获取等）

特点：
- 无状态（纯函数/装饰器）
- 直接操作 exchange，无间接层
"""

import asyncio
import logging
from typing import Dict, List
from functools import wraps

logger = logging.getLogger(__name__)


def with_order_confirmation(delay_ms: float = 100):
    """
    订单确认装饰器 - 双重确认机制

    使用示例：
        @with_order_confirmation(delay_ms=100)
        async def place_limit_order(exchange, symbol, side, size, price):
            return await exchange.place_limit_order(...)

    Args:
        delay_ms: 确认延迟（毫秒）
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(exchange, symbol, *args, **kwargs):
            # 1. 下单
            order_id = await func(exchange, symbol, *args, **kwargs)

            # 2. 双重确认：等待后验证订单状态
            await asyncio.sleep(delay_ms / 1000)
            status = await exchange.get_order_status(symbol, order_id)

            if status not in ["open", "filled", "partial"]:
                raise Exception(f"Order {order_id} failed with status: {status}")

            logger.debug(f"Order confirmed: {order_id} ({status})")
            return order_id

        return wrapper
    return decorator


# 批量获取辅助函数（无状态）

async def get_prices(exchange, symbols: List[str]) -> Dict[str, float]:
    """
    批量获取价格

    Args:
        exchange: 交易所实例
        symbols: 币种列表

    Returns:
        {symbol: price} 字典
    """
    prices = {}
    for symbol in symbols:
        prices[symbol] = await exchange.get_price(symbol)
    return prices


# 订单确认版本的下单函数

@with_order_confirmation(delay_ms=100)
async def place_limit_order_confirmed(
    exchange,
    symbol: str,
    side: str,
    size: float,
    price: float
) -> str:
    """
    下限价单（带确认）

    Args:
        exchange: 交易所实例
        symbol: 交易对
        side: "buy" 或 "sell"
        size: 数量
        price: 限价

    Returns:
        order_id
    """
    logger.info(f"Placing {side} order: {size} {symbol} @ {price}")
    return await exchange.place_limit_order(symbol, side, size, price)


async def place_market_order(
    exchange,
    symbol: str,
    side: str,
    size: float
) -> str:
    """
    下市价单

    Args:
        exchange: 交易所实例
        symbol: 交易对
        side: "buy" 或 "sell"
        size: 数量

    Returns:
        order_id
    """
    logger.info(f"Placing market {side} order: {size} {symbol}")
    order_id = await exchange.place_market_order(symbol, side, size)
    logger.info(f"Market order executed: {order_id}")
    return order_id


async def cancel_order(exchange, symbol: str, order_id: str):
    """
    撤单

    Args:
        exchange: 交易所实例
        symbol: 交易对
        order_id: 订单ID
    """
    logger.info(f"Cancelling order: {order_id}")
    await exchange.cancel_order(symbol, order_id)
