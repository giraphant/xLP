#!/usr/bin/env python3
"""
交易所客户端 - 极简薄封装

职责：
- 封装exchange API调用
- 订单双重确认（double-check）

特点：
- 极简薄封装，不包含业务逻辑
- 订单确认机制（防止静默失败）
"""

import asyncio
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class ExchangeClient:
    """
    交易所客户端极简封装

    替代原来的ActionExecutor（429行），只做必要的交易所调用（~80行）
    """

    def __init__(self, exchange_impl):
        """
        Args:
            exchange_impl: 交易所实现（Lighter, Mock等）
        """
        self.exchange = exchange_impl

    async def get_price(self, symbol: str) -> float:
        """获取价格"""
        return await self.exchange.get_price(symbol)

    async def get_prices(self, symbols: List[str]) -> Dict[str, float]:
        """批量获取价格"""
        prices = {}
        for symbol in symbols:
            prices[symbol] = await self.get_price(symbol)
        return prices

    async def get_position(self, symbol: str) -> float:
        """获取持仓"""
        return await self.exchange.get_position(symbol)

    async def get_positions(self) -> Dict[str, float]:
        """获取所有持仓"""
        return await self.exchange.get_positions()

    async def place_order(
        self,
        symbol: str,
        side: str,
        size: float,
        price: float
    ) -> str:
        """
        下限价单（带双重确认）

        Args:
            symbol: 交易对
            side: "buy" 或 "sell"
            size: 数量
            price: 限价

        Returns:
            order_id

        Raises:
            Exception: 订单失败
        """
        logger.info(f"Placing {side} order: {size} {symbol} @ {price}")

        # 1. 下单
        order_id = await self.exchange.place_limit_order(
            symbol=symbol,
            side=side,
            size=size,
            price=price
        )

        # 2. 双重确认：等待100ms后验证订单状态
        await asyncio.sleep(0.1)
        status = await self.exchange.get_order_status(symbol, order_id)

        if status not in ["open", "filled", "partial"]:
            raise Exception(f"Order {order_id} failed with status: {status}")

        logger.info(f"Order confirmed: {order_id} ({status})")
        return order_id

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        size: float
    ) -> str:
        """
        下市价单

        Args:
            symbol: 交易对
            side: "buy" 或 "sell"
            size: 数量

        Returns:
            order_id
        """
        logger.info(f"Placing market {side} order: {size} {symbol}")

        order_id = await self.exchange.place_market_order(
            symbol=symbol,
            side=side,
            size=size
        )

        logger.info(f"Market order executed: {order_id}")
        return order_id

    async def cancel_order(self, symbol: str, order_id: str):
        """撤单"""
        logger.info(f"Cancelling order: {order_id}")
        await self.exchange.cancel_order(symbol, order_id)
