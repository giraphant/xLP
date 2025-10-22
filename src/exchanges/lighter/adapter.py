#!/usr/bin/env python3
"""
Lighter Exchange Adapter - 实现 ExchangeInterface
"""

from ..interface import ExchangeInterface
from .orders import LighterOrderManager


class LighterExchange(ExchangeInterface):
    """
    Lighter 交易所适配器
    将 LighterClient 适配到统一的 ExchangeInterface
    """

    # Symbol to Lighter market symbol mapping
    # Note: Lighter uses direct symbols (e.g., "BTC", "SOL"), not "BTC_USDC"
    SYMBOL_MAP = {
        "SOL": "SOL",
        "ETH": "ETH",
        "BTC": "BTC",
        "BONK": "1000BONK",  # Lighter uses 1000BONK, not BONK
    }

    def __init__(self, config: dict):
        super().__init__(config)

        # Initialize Lighter client (using LighterOrderManager which includes all functionality)
        self.lighter_client = LighterOrderManager(
            private_key=config.get("private_key"),
            account_index=config.get("account_index", 0),
            api_key_index=config.get("api_key_index", 0),
            base_url=config.get("base_url", "https://mainnet.zklighter.elliot.ai")
        )

        # Track order IDs per symbol for cancellation
        self.order_map = {}  # {order_id: (symbol, market_id)}

    def _get_market_id(self, symbol: str) -> str:
        """Convert symbol to Lighter market symbol"""
        return self.SYMBOL_MAP.get(symbol.upper(), symbol.upper())

    async def get_position(self, symbol: str) -> float:
        """获取当前持仓数量"""
        lighter_symbol = self._get_market_id(symbol)
        position = await self.lighter_client.get_position(lighter_symbol)
        return position

    async def get_price(self, symbol: str) -> float:
        """获取当前市场价格"""
        lighter_symbol = self._get_market_id(symbol)
        price = await self.lighter_client.get_price(lighter_symbol)
        return price

    async def place_limit_order(
        self,
        symbol: str,
        side: str,
        size: float,
        price: float
    ) -> str:
        """下限价单"""
        lighter_symbol = self._get_market_id(symbol)
        order_id = await self.lighter_client.place_limit_order(
            symbol=lighter_symbol,
            side=side,
            size=size,
            price=price,
            reduce_only=False
        )

        # Store mapping for cancellation
        self.order_map[order_id] = (symbol, lighter_symbol)
        return order_id

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        size: float
    ) -> str:
        """下市价单"""
        lighter_symbol = self._get_market_id(symbol)
        order_id = await self.lighter_client.place_market_order(
            symbol=lighter_symbol,
            side=side,
            size=size
        )

        # Store mapping for cancellation
        self.order_map[order_id] = (symbol, lighter_symbol)
        return order_id

    async def cancel_order(self, order_id: str) -> bool:
        """撤销订单"""
        if order_id not in self.order_map:
            # Try to extract market ID from order ID or use default
            # This is a fallback - ideally we should always have the mapping
            return False

        symbol, lighter_symbol = self.order_map[order_id]
        success = await self.lighter_client.cancel_order(lighter_symbol, order_id)

        if success:
            del self.order_map[order_id]

        return success

    async def cancel_all_orders(self, symbol: str) -> int:
        """取消该币种的所有活跃订单"""
        import logging
        logger = logging.getLogger(__name__)

        lighter_symbol = self._get_market_id(symbol)

        # 找出该 symbol 的所有订单
        orders_to_cancel = [
            order_id for order_id, (sym, _) in self.order_map.items()
            if sym == symbol
        ]

        logger.info(f"[Lighter] cancel_all_orders({symbol}): order_map has {len(self.order_map)} total orders")
        logger.info(f"[Lighter] cancel_all_orders({symbol}): found {len(orders_to_cancel)} orders for {symbol}: {orders_to_cancel}")

        canceled_count = 0
        for order_id in orders_to_cancel:
            try:
                logger.info(f"[Lighter] Attempting to cancel order {order_id}")
                success = await self.lighter_client.cancel_order(lighter_symbol, order_id)
                if success:
                    del self.order_map[order_id]
                    canceled_count += 1
                    logger.info(f"[Lighter] Successfully canceled order {order_id}")
                else:
                    logger.warning(f"[Lighter] Failed to cancel order {order_id} (cancel returned False)")
            except Exception as e:
                # 继续取消其他订单
                logger.error(f"[Lighter] Exception canceling order {order_id}: {e}")

        logger.info(f"[Lighter] cancel_all_orders({symbol}): canceled {canceled_count}/{len(orders_to_cancel)} orders")
        return canceled_count
