#!/usr/bin/env python3
"""
Lighter Exchange Adapter - 实现 ExchangeInterface
"""

from datetime import datetime, timedelta
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
        # Track detailed order info for query
        self.order_details = {}  # {order_id: order_info}

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

        # Store order details for query
        now = datetime.now()
        self.order_details[order_id] = {
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "size": size,
            "price": price,
            "filled_size": 0.0,
            "status": "open",
            "created_at": now,
            "updated_at": now
        }

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

        # Store order details - market orders are immediately filled
        now = datetime.now()
        current_price = await self.lighter_client.get_price(lighter_symbol)
        self.order_details[order_id] = {
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "size": size,
            "price": current_price,
            "filled_size": size,
            "status": "filled",
            "created_at": now,
            "updated_at": now,
            "filled_at": now
        }

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
            # Update order status
            if order_id in self.order_details:
                self.order_details[order_id]["status"] = "cancelled"
                self.order_details[order_id]["updated_at"] = datetime.now()

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
                    # Update order status
                    if order_id in self.order_details:
                        self.order_details[order_id]["status"] = "cancelled"
                        self.order_details[order_id]["updated_at"] = datetime.now()
                    canceled_count += 1
                    logger.info(f"[Lighter] Successfully canceled order {order_id}")
                else:
                    logger.warning(f"[Lighter] Failed to cancel order {order_id} (cancel returned False)")
            except Exception as e:
                # 继续取消其他订单
                logger.error(f"[Lighter] Exception canceling order {order_id}: {e}")

        logger.info(f"[Lighter] cancel_all_orders({symbol}): canceled {canceled_count}/{len(orders_to_cancel)} orders")
        return canceled_count

    async def get_open_orders(self, symbol: str = None) -> list:
        """
        获取活跃订单

        注：当前版本使用本地缓存的订单信息
        未来可以通过AccountApi查询真实订单状态
        """
        open_orders = []

        # 使用本地维护的订单详情
        # TODO: 未来可以使用self.lighter_client.account_api查询真实订单
        for order_id, details in self.order_details.items():
            if details["status"] == "open":
                if symbol is None or details["symbol"] == symbol:
                    open_orders.append(details.copy())

        return open_orders

    async def get_recent_fills(self, symbol: str = None, minutes_back: int = 10) -> list:
        """
        获取最近成交记录（从交易所真实查询）
        """
        try:
            # 计算时间范围（毫秒时间戳）
            cutoff_time = datetime.now() - timedelta(minutes=minutes_back)
            cutoff_timestamp_ms = int(cutoff_time.timestamp() * 1000)

            # 如果指定了symbol，获取market_id
            market_id = None
            if symbol:
                lighter_symbol = self.symbol_map.get(symbol)
                if lighter_symbol:
                    market_id = lighter_symbol.market_id

            # 调用 OrderApi.trades() 查询成交历史
            trades_response = self.lighter_client.order_api.trades(
                sort_by="block_number",
                sort_dir="desc",
                limit=100,  # 最多查100条
                account_index=self.lighter_client.account_index,
                market_id=market_id,
                var_from=cutoff_timestamp_ms
            )

            # 解析成交记录
            recent_fills = []
            if trades_response and hasattr(trades_response, 'data'):
                for trade in trades_response.data:
                    # 解析时间
                    filled_at = datetime.fromtimestamp(trade.block_number / 1000) if hasattr(trade, 'block_number') else None

                    # 获取symbol
                    trade_symbol = None
                    for sym, lighter_sym in self.symbol_map.items():
                        if lighter_sym.market_id == trade.market_id:
                            trade_symbol = sym
                            break

                    if trade_symbol:
                        recent_fills.append({
                            "order_id": str(trade.order_index) if hasattr(trade, 'order_index') else None,
                            "symbol": trade_symbol,
                            "side": "sell" if trade.ask_filter == 1 else "buy",
                            "filled_size": float(trade.base_amount) / 1000 if hasattr(trade, 'base_amount') else 0,
                            "filled_price": float(trade.price) if hasattr(trade, 'price') else 0,
                            "filled_at": filled_at
                        })

            return recent_fills

        except Exception as e:
            logger.error(f"Error fetching recent fills: {e}")
            return []
