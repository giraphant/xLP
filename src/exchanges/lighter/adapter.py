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

        # 双向市场映射（初始为空，首次使用时加载）
        self.symbol_to_market_id = {}  # {"SOL": 123, "BTC": 456, ...}
        self.market_id_to_symbol = {}  # {123: "SOL", 456: "BTC", ...}

        # Lighter symbol → 用户 symbol 的反向映射
        self.lighter_to_user_symbol = {v: k for k, v in self.SYMBOL_MAP.items()}  # {"1000BONK": "BONK", ...}

        # 完全无状态 - 所有数据从交易所查询

    def _get_market_id(self, symbol: str) -> str:
        """Convert symbol to Lighter market symbol"""
        return self.SYMBOL_MAP.get(symbol.upper(), symbol.upper())

    async def _ensure_market_map(self):
        """确保市场映射已加载（懒加载）"""
        if self.symbol_to_market_id:
            return  # 已加载

        # 触发 lighter_client 加载市场信息
        await self.lighter_client._load_markets()

        # 复制正向映射
        self.symbol_to_market_id = self.lighter_client.symbol_to_market_id.copy()

        # 构建反向映射
        self.market_id_to_symbol = {
            market_id: symbol
            for symbol, market_id in self.symbol_to_market_id.items()
        }

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

        return order_id

    async def cancel_order(self, order_id: str) -> bool:
        """
        取消单个订单（不使用，保留以满足接口要求）
        实际使用 cancel_all_orders()
        """
        raise NotImplementedError("Use cancel_all_orders() instead")

    async def cancel_all_orders(self, symbol: str) -> int:
        """取消该币种的所有活跃订单（从交易所查询）"""
        import logging
        logger = logging.getLogger(__name__)

        # 查询该币种的所有活跃订单（真实查询）
        open_orders = await self.get_open_orders(symbol)

        logger.info(f"[Lighter] cancel_all_orders({symbol}): found {len(open_orders)} active orders")

        if not open_orders:
            return 0

        lighter_symbol = self._get_market_id(symbol)
        canceled_count = 0

        for order in open_orders:
            order_id = order.get("order_id")
            if not order_id:
                continue

            try:
                logger.info(f"[Lighter] Attempting to cancel order {order_id}")
                success = await self.lighter_client.cancel_order(lighter_symbol, order_id)
                if success:
                    canceled_count += 1
                    logger.info(f"[Lighter] Successfully canceled order {order_id}")
                else:
                    logger.warning(f"[Lighter] Failed to cancel order {order_id} (cancel returned False)")
            except Exception as e:
                # 继续取消其他订单
                logger.error(f"[Lighter] Exception canceling order {order_id}: {e}")

        logger.info(f"[Lighter] cancel_all_orders({symbol}): canceled {canceled_count}/{len(open_orders)} orders")
        return canceled_count

    async def get_open_orders(self, symbol: str = None) -> list:
        """
        获取活跃订单（从交易所真实查询）
        """
        import logging
        logger = logging.getLogger(__name__)

        try:
            # 确保市场映射已加载
            await self._ensure_market_map()

            open_orders = []

            # 如果指定了symbol，只查询该市场
            if symbol:
                # 转换成 Lighter symbol（"BONK" → "1000BONK"）
                lighter_symbol = self._get_market_id(symbol)
                market_id = self.symbol_to_market_id.get(lighter_symbol)
                if not market_id:
                    logger.warning(f"Symbol {symbol} (lighter: {lighter_symbol}) not found in market map")
                    return []

                # 查询该市场的活跃订单
                orders_response = await self.lighter_client.order_api.account_active_orders(
                    account_index=self.lighter_client.account_index,
                    market_id=market_id
                )

                if orders_response and hasattr(orders_response, 'orders'):
                    # 返回订单时使用用户 symbol（保持输入参数一致）
                    for order in orders_response.orders:
                        open_orders.append(self._parse_order(order, symbol))

            else:
                # 查询所有市场的活跃订单
                for lighter_symbol, market_id in self.symbol_to_market_id.items():
                    orders_response = await self.lighter_client.order_api.account_active_orders(
                        account_index=self.lighter_client.account_index,
                        market_id=market_id
                    )

                    if orders_response and hasattr(orders_response, 'orders'):
                        # 转换回用户 symbol（"1000BONK" → "BONK"）
                        user_symbol = self.lighter_to_user_symbol.get(lighter_symbol, lighter_symbol)
                        for order in orders_response.orders:
                            open_orders.append(self._parse_order(order, user_symbol))

            return open_orders

        except Exception as e:
            logger.error(f"Error fetching open orders: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []

    def _parse_order(self, order, symbol: str) -> dict:
        """解析订单对象为标准格式"""
        # Order对象使用 timestamp 字段，不是 created_at
        created_at = None
        if hasattr(order, 'timestamp') and order.timestamp:
            created_at = datetime.fromtimestamp(order.timestamp / 1000)
        elif hasattr(order, 'created_at') and order.created_at:
            created_at = datetime.fromtimestamp(order.created_at / 1000)
        else:
            created_at = datetime.now()

        # Order对象字段：
        # - remaining_base_amount: 剩余未成交数量（链上整数）
        # - base_size: 订单大小（实际数量，已转换）
        # - is_ask: True=卖单, False=买单
        size = 0.0
        if hasattr(order, 'base_size') and order.base_size:
            size = float(order.base_size)
        elif hasattr(order, 'remaining_base_amount') and order.remaining_base_amount:
            # Fallback: 手动转换（除以1000，因为是1000x市场）
            size = float(order.remaining_base_amount) / 1000

        side = "sell" if hasattr(order, 'is_ask') and order.is_ask else "buy"

        return {
            "order_id": str(order.order_index) if hasattr(order, 'order_index') else None,
            "symbol": symbol,
            "side": side,
            "size": size,
            "price": float(order.price) if hasattr(order, 'price') else 0,
            "filled_size": 0.0,  # 活跃订单还未成交
            "status": "open",
            "created_at": created_at,
            "updated_at": datetime.now()
        }

    async def get_recent_fills(self, symbol: str = None, minutes_back: int = 10) -> list:
        """
        获取最近成交记录（从交易所真实查询）
        """
        import logging
        logger = logging.getLogger(__name__)

        try:
            # 确保市场映射已加载
            await self._ensure_market_map()

            # 计算时间范围（毫秒时间戳）
            cutoff_time = datetime.now() - timedelta(minutes=minutes_back)
            cutoff_timestamp_ms = int(cutoff_time.timestamp() * 1000)

            logger.debug(f"[get_recent_fills] Querying fills for {symbol or 'all symbols'}, cutoff: {cutoff_time}, timestamp_ms: {cutoff_timestamp_ms}")

            # 如果指定了symbol，获取market_id
            market_id = None
            if symbol:
                market_id = self.symbol_to_market_id.get(symbol)
                if market_id:
                    logger.debug(f"[get_recent_fills] market_id for {symbol}: {market_id}")

            # 调用 OrderApi.trades() 查询成交历史
            trades_response = await self.lighter_client.order_api.trades(
                sort_by="block_number",
                sort_dir="desc",
                limit=100,  # 最多查100条
                account_index=self.lighter_client.account_index,
                market_id=market_id,
                var_from=cutoff_timestamp_ms
            )

            logger.debug(f"[get_recent_fills] API response: {trades_response}")
            logger.debug(f"[get_recent_fills] Has 'data' attr: {hasattr(trades_response, 'data')}")
            if hasattr(trades_response, 'data'):
                logger.debug(f"[get_recent_fills] Number of trades: {len(trades_response.data) if trades_response.data else 0}")

            # 解析成交记录
            recent_fills = []
            if trades_response and hasattr(trades_response, 'data'):
                for trade in trades_response.data:
                    logger.debug(f"[get_recent_fills] Trade object: {trade}")

                    # 解析时间 - Trade对象使用 timestamp 字段（毫秒时间戳）
                    filled_at = None
                    if hasattr(trade, 'timestamp') and trade.timestamp:
                        filled_at = datetime.fromtimestamp(trade.timestamp / 1000)
                    logger.debug(f"[get_recent_fills] Parsed filled_at: {filled_at}")

                    # 获取symbol（使用反向映射，O(1)）
                    lighter_symbol = None
                    if hasattr(trade, 'market_id'):
                        lighter_symbol = self.market_id_to_symbol.get(trade.market_id)

                    if lighter_symbol and filled_at:
                        # 转换回用户 symbol（"1000BONK" → "BONK"）
                        trade_symbol = self.lighter_to_user_symbol.get(lighter_symbol, lighter_symbol)
                        # Trade对象字段：size, price, is_maker_ask
                        # 判断方向：需要知道这笔成交是我们作为maker还是taker
                        # 简化：如果是ask方（卖），就是sell；如果是bid方（买），就是buy
                        side = "sell" if hasattr(trade, 'is_maker_ask') and trade.is_maker_ask else "buy"

                        fill_record = {
                            "order_id": str(trade.trade_id) if hasattr(trade, 'trade_id') else None,
                            "symbol": trade_symbol,
                            "side": side,
                            "filled_size": float(trade.size) / 1000 if hasattr(trade, 'size') else 0,
                            "filled_price": float(trade.price) if hasattr(trade, 'price') else 0,
                            "filled_at": filled_at
                        }
                        logger.debug(f"[get_recent_fills] Parsed fill: {fill_record}")
                        recent_fills.append(fill_record)

            logger.info(f"[get_recent_fills] Found {len(recent_fills)} fills for {symbol or 'all symbols'}")
            return recent_fills

        except Exception as e:
            logger.error(f"Error fetching recent fills: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
