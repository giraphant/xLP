#!/usr/bin/env python3
"""
Mock Exchange - 模拟交易所实现
用于测试和开发，避免真实下单
"""

from datetime import datetime, timedelta
from ..interface import ExchangeInterface


class MockExchange(ExchangeInterface):
    """
    模拟交易所实现
    用于测试和开发
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.positions = {}
        self.orders = {}
        self.prices = {
            "SOL": 200.0,
            "ETH": 3500.0,
            "BTC": 95000.0,
            "BONK": 0.00002,
        }

    async def get_position(self, symbol: str) -> float:
        return self.positions.get(symbol, 0.0)

    async def get_price(self, symbol: str) -> float:
        return self.prices.get(symbol, 100.0)

    async def place_limit_order(
        self,
        symbol: str,
        side: str,
        size: float,
        price: float
    ) -> str:
        order_id = f"mock_{symbol}_{side}_{len(self.orders)}"
        now = datetime.now()
        self.orders[order_id] = {
            "symbol": symbol,
            "side": side,
            "size": size,
            "price": price,
            "status": "open",
            "filled_size": 0.0,
            "created_at": now,
            "updated_at": now
        }
        print(f"  [MockExchange] 限价单已下: {order_id} - {side} {size} {symbol} @ ${price:.2f}")
        return order_id

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        size: float
    ) -> str:
        order_id = f"mock_{symbol}_{side}_market_{len(self.orders)}"
        now = datetime.now()
        self.orders[order_id] = {
            "symbol": symbol,
            "side": side,
            "size": size,
            "price": self.prices.get(symbol, 100.0),
            "status": "filled",
            "filled_size": size,
            "created_at": now,
            "updated_at": now,
            "filled_at": now  # 市价单立即成交
        }

        # 更新持仓
        current_pos = self.positions.get(symbol, 0.0)
        if side == "buy":
            self.positions[symbol] = current_pos + size
        else:
            self.positions[symbol] = current_pos - size

        print(f"  [MockExchange] 市价单已成交: {order_id} - {side} {size} {symbol}")
        return order_id

    async def cancel_order(self, order_id: str) -> bool:
        if order_id in self.orders:
            self.orders[order_id]["status"] = "canceled"
            print(f"  [MockExchange] 已撤单: {order_id}")
            return True
        return False

    async def cancel_all_orders(self, symbol: str) -> int:
        """取消该币种的所有活跃订单"""
        canceled_count = 0
        for order_id, order in list(self.orders.items()):
            if order["symbol"] == symbol and order["status"] == "open":
                order["status"] = "canceled"
                canceled_count += 1
                print(f"  [MockExchange] 已撤单: {order_id}")
        return canceled_count

    async def get_open_orders(self, symbol: str = None) -> list:
        """获取活跃订单"""
        open_orders = []
        for order_id, order in self.orders.items():
            if order["status"] == "open":
                if symbol is None or order["symbol"] == symbol:
                    open_orders.append({
                        "order_id": order_id,
                        "symbol": order["symbol"],
                        "side": order["side"],
                        "size": order["size"],
                        "price": order["price"],
                        "filled_size": order.get("filled_size", 0.0),
                        "status": order["status"],
                        "created_at": order.get("created_at", datetime.now()),
                        "updated_at": order.get("updated_at", datetime.now())
                    })
        return open_orders

    async def get_recent_fills(self, symbol: str = None, minutes_back: int = 10) -> list:
        """获取最近成交记录"""
        recent_fills = []
        cutoff_time = datetime.now() - timedelta(minutes=minutes_back)

        # Mock implementation: 查找已成交的订单
        for order_id, order in self.orders.items():
            if order["status"] == "filled":
                filled_at = order.get("filled_at", datetime.now())
                if filled_at >= cutoff_time:
                    if symbol is None or order["symbol"] == symbol:
                        recent_fills.append({
                            "order_id": order_id,
                            "symbol": order["symbol"],
                            "side": order["side"],
                            "filled_size": order["filled_size"],
                            "filled_price": order["price"],
                            "filled_at": filled_at
                        })
        return recent_fills
