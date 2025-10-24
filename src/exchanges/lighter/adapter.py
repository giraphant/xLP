#!/usr/bin/env python3
"""
Lighter Exchange Adapter - 实现 ExchangeInterface
"""

import logging
import traceback
from datetime import datetime, timedelta
from typing import Dict

from ..interface import ExchangeInterface
from .orders import LighterOrderManager

logger = logging.getLogger(__name__)


class LighterExchange(ExchangeInterface):
    """
    Lighter 交易所适配器
    将 Lighter API 适配到统一的 ExchangeInterface
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

        # 唯一需要的运行时映射：用户 symbol → market_id（懒加载缓存）
        self._market_id_cache: Dict[str, int] = {}

    async def _get_market_id(self, user_symbol: str) -> int:
        """
        获取 market_id（带缓存）

        Args:
            user_symbol: 用户 symbol (如 "BONK")

        Returns:
            market_id: 数字 ID (如 789)
        """
        # 缓存命中
        if user_symbol in self._market_id_cache:
            return self._market_id_cache[user_symbol]

        # 确保市场已加载
        await self.lighter_client._load_markets()

        # 转换：用户 symbol → Lighter symbol
        lighter_symbol = self._to_lighter_symbol(user_symbol)

        # 查询：Lighter symbol → market_id
        market_id = self.lighter_client.symbol_to_market_id.get(lighter_symbol)

        if market_id is None:
            raise ValueError(
                f"Market not found for user symbol '{user_symbol}' "
                f"(lighter symbol: '{lighter_symbol}')"
            )

        # 缓存
        self._market_id_cache[user_symbol] = market_id

        return market_id

    def _to_lighter_symbol(self, user_symbol: str) -> str:
        """用户 symbol → Lighter symbol"""
        return self.SYMBOL_MAP.get(user_symbol.upper(), user_symbol.upper())

    async def get_position(self, symbol: str) -> float:
        """获取当前持仓数量"""
        lighter_symbol = self._to_lighter_symbol(symbol)
        position = await self.lighter_client.get_position(lighter_symbol)
        return position

    async def get_price(self, symbol: str) -> float:
        """获取当前市场价格"""
        lighter_symbol = self._to_lighter_symbol(symbol)
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
        lighter_symbol = self._to_lighter_symbol(symbol)
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
        lighter_symbol = self._to_lighter_symbol(symbol)
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
        # 查询该币种的所有活跃订单（真实查询）
        open_orders = await self.get_open_orders(symbol)

        logger.info(f"[Lighter] cancel_all_orders({symbol}): found {len(open_orders)} active orders")

        if not open_orders:
            return 0

        lighter_symbol = self._to_lighter_symbol(symbol)
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
        获取活跃订单

        Args:
            symbol: 用户 symbol，None 表示全部

        Returns:
            订单列表，symbol 字段使用用户 symbol
        """
        try:
            # 确保 client 已初始化
            if self.lighter_client.client is None:
                await self.lighter_client.initialize()

            if symbol:
                # 单个市场
                market_id = await self._get_market_id(symbol)

                # 生成认证 token（返回 tuple，取第一个元素）
                auth_token, _ = self.lighter_client.client.create_auth_token_with_expiry()

                # 使用 client.order_api（需要传入认证 token）
                response = await self.lighter_client.client.order_api.account_active_orders(
                    account_index=self.lighter_client.account_index,
                    market_id=market_id,
                    authorization=auth_token
                )

                orders = []
                if response and hasattr(response, 'orders'):
                    for order in response.orders:
                        # 返回时使用输入的用户 symbol
                        orders.append(self._parse_order(order, symbol))

                return orders

            else:
                # 所有市场：递归调用
                all_orders = []
                for user_symbol in self.SYMBOL_MAP.keys():
                    orders = await self.get_open_orders(user_symbol)
                    all_orders.extend(orders)

                return all_orders

        except Exception as e:
            logger.error(f"Error fetching open orders for {symbol}: {e}")
            logger.error(traceback.format_exc())
            return []

    def _parse_order(self, order, symbol: str) -> dict:
        """解析订单对象为标准格式"""
        # Order.timestamp 是秒级时间戳（不是毫秒！）
        created_at = None
        if hasattr(order, 'timestamp') and order.timestamp:
            created_at = datetime.fromtimestamp(order.timestamp)  # 秒级
        elif hasattr(order, 'created_at') and order.created_at:
            created_at = datetime.fromtimestamp(order.created_at)  # 秒级
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
        获取最近成交

        Args:
            symbol: 用户 symbol，None 表示全部

        Returns:
            成交列表，symbol 字段使用用户 symbol
        """
        try:
            # 确保 client 已初始化
            if self.lighter_client.client is None:
                await self.lighter_client.initialize()

            cutoff_time = datetime.now() - timedelta(minutes=minutes_back)

            # 确定要查询的 market_id
            market_id = None
            if symbol:
                market_id = await self._get_market_id(symbol)

            # 生成认证 token（返回 tuple，取第一个元素）
            auth_token, _ = self.lighter_client.client.create_auth_token_with_expiry()

            # 使用 client.order_api（需要传入认证 token）
            # 注意：不使用 var_from 参数，改为客户端过滤（var_from 行为不符合预期）
            response = await self.lighter_client.client.order_api.trades(
                sort_by="timestamp",
                sort_dir="desc",
                limit=100,
                account_index=self.lighter_client.account_index,
                market_id=market_id,
                authorization=auth_token
            )

            # 解析成交
            fills = []
            if response and hasattr(response, 'trades'):
                for trade in response.trades:
                    # 解析时间
                    filled_at = None
                    if hasattr(trade, 'timestamp') and trade.timestamp:
                        filled_at = datetime.fromtimestamp(trade.timestamp / 1000)

                    if not filled_at:
                        continue

                    # 客户端过滤：跳过 cutoff_time 之前的成交
                    if filled_at < cutoff_time:
                        continue

                    # 从 trade.market_id 反查用户 symbol
                    trade_user_symbol = None

                    # 方法1：如果指定了 symbol，直接使用
                    if symbol:
                        trade_user_symbol = symbol

                    # 方法2：从 market_id 反查
                    else:
                        for user_sym, cached_mid in self._market_id_cache.items():
                            if cached_mid == trade.market_id:
                                trade_user_symbol = user_sym
                                break

                    if not trade_user_symbol:
                        continue

                    # 构建成交记录
                    fill = {
                        "order_id": str(trade.trade_id) if hasattr(trade, 'trade_id') else None,
                        "symbol": trade_user_symbol,
                        "side": "sell" if hasattr(trade, 'is_maker_ask') and trade.is_maker_ask else "buy",
                        "filled_size": float(trade.size) if hasattr(trade, 'size') else 0,
                        "filled_price": float(trade.price) if hasattr(trade, 'price') else 0,
                        "filled_at": filled_at
                    }
                    fills.append(fill)

            return fills

        except Exception as e:
            logger.error(f"Error fetching recent fills for {symbol}: {e}")
            logger.error(traceback.format_exc())
            return []
