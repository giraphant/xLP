#!/usr/bin/env python3
"""
交易所客户端 - 薄封装

职责：
- 封装exchange API调用
- 添加限流保护
- 添加熔断保护
- 订单确认（double-check）

特点：
- 薄封装，不包含业务逻辑
- 可选的限流和熔断
- 订单确认机制
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ExchangeClient:
    """
    交易所客户端封装

    替代原来的ActionExecutor（429行），只做交易所调用（~100行）
    """

    def __init__(
        self,
        exchange_impl,
        rate_limiter=None,
        circuit_breaker=None
    ):
        """
        Args:
            exchange_impl: 交易所实现（Lighter, Mock等）
            rate_limiter: 可选的速率限制器
            circuit_breaker: 可选的熔断器
        """
        self.exchange = exchange_impl
        self.rate_limiter = rate_limiter
        self.circuit_breaker = circuit_breaker

    async def get_price(self, symbol: str) -> float:
        """
        获取价格

        Args:
            symbol: 交易对符号

        Returns:
            当前价格
        """
        if self.rate_limiter:
            async with self.rate_limiter:
                return await self._get_price_impl(symbol)
        else:
            return await self._get_price_impl(symbol)

    async def _get_price_impl(self, symbol: str) -> float:
        """实际的价格获取实现"""
        if self.circuit_breaker:
            return await self.circuit_breaker.call(
                self.exchange.get_price,
                symbol
            )
        return await self.exchange.get_price(symbol)

    async def get_position(self, symbol: str) -> float:
        """
        获取持仓

        Args:
            symbol: 交易对符号

        Returns:
            当前持仓（负数表示空头）
        """
        if self.rate_limiter:
            async with self.rate_limiter:
                return await self._get_position_impl(symbol)
        else:
            return await self._get_position_impl(symbol)

    async def _get_position_impl(self, symbol: str) -> float:
        """实际的持仓获取实现"""
        if self.circuit_breaker:
            return await self.circuit_breaker.call(
                self.exchange.get_position,
                symbol
            )
        return await self.exchange.get_position(symbol)

    async def place_order(
        self,
        symbol: str,
        side: str,
        size: float,
        price: float
    ) -> str:
        """
        下限价单并确认

        包含double-check机制：
        1. 下单
        2. 等待100ms
        3. 查询订单状态
        4. 确认订单成功

        Args:
            symbol: 交易对符号
            side: "buy" 或 "sell"
            size: 数量
            price: 价格

        Returns:
            order_id

        Raises:
            Exception: 订单失败
        """
        if self.rate_limiter:
            async with self.rate_limiter:
                return await self._place_order_with_confirm(symbol, side, size, price)
        else:
            return await self._place_order_with_confirm(symbol, side, size, price)

    async def _place_order_with_confirm(
        self,
        symbol: str,
        side: str,
        size: float,
        price: float
    ) -> str:
        """下单 + 确认"""

        # 步骤1: 下单
        if self.circuit_breaker:
            order_id = await self.circuit_breaker.call(
                self.exchange.place_limit_order,
                symbol, side, size, price
            )
        else:
            order_id = await self.exchange.place_limit_order(symbol, side, size, price)

        logger.info(f"Order placed: {symbol} {side} {size:.4f} @ ${price:.2f} (ID: {order_id})")

        # 步骤2: 等待交易所处理
        await asyncio.sleep(0.1)

        # 步骤3: 确认订单状态
        try:
            status = await self.exchange.get_order_status(order_id)

            if status not in ["open", "filled", "partial"]:
                logger.error(f"Order {order_id} has invalid status: {status}")
                raise Exception(f"Order {order_id} failed with status: {status}")

            logger.debug(f"Order {order_id} confirmed: {status}")
            return order_id

        except Exception as e:
            logger.error(f"Failed to confirm order {order_id}: {e}")
            # 即使确认失败，也返回order_id（订单可能已下成功）
            # 由上层决定如何处理
            raise

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        size: float
    ) -> str:
        """
        下市价单

        Args:
            symbol: 交易对符号
            side: "buy" 或 "sell"
            size: 数量

        Returns:
            order_id
        """
        if self.rate_limiter:
            async with self.rate_limiter:
                return await self._place_market_order_impl(symbol, side, size)
        else:
            return await self._place_market_order_impl(symbol, side, size)

    async def _place_market_order_impl(
        self,
        symbol: str,
        side: str,
        size: float
    ) -> str:
        """实际的市价单下单"""
        if self.circuit_breaker:
            order_id = await self.circuit_breaker.call(
                self.exchange.place_market_order,
                symbol, side, size
            )
        else:
            order_id = await self.exchange.place_market_order(symbol, side, size)

        logger.info(f"Market order placed: {symbol} {side} {size:.4f} (ID: {order_id})")
        return order_id

    async def cancel_order(self, order_id: str) -> bool:
        """
        撤单

        Args:
            order_id: 订单ID

        Returns:
            是否成功
        """
        if self.rate_limiter:
            async with self.rate_limiter:
                return await self._cancel_order_impl(order_id)
        else:
            return await self._cancel_order_impl(order_id)

    async def _cancel_order_impl(self, order_id: str) -> bool:
        """实际的撤单实现"""
        if self.circuit_breaker:
            success = await self.circuit_breaker.call(
                self.exchange.cancel_order,
                order_id
            )
        else:
            success = await self.exchange.cancel_order(order_id)

        if success:
            logger.info(f"Order cancelled: {order_id}")
        else:
            logger.warning(f"Failed to cancel order: {order_id}")

        return success
