#!/usr/bin/env python3
"""
Mock Exchange - 模拟交易所实现
用于测试和开发，避免真实下单
"""

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
        self.orders[order_id] = {
            "symbol": symbol,
            "side": side,
            "size": size,
            "price": price,
            "status": "open",
            "filled_size": 0.0,
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
        self.orders[order_id] = {
            "symbol": symbol,
            "side": side,
            "size": size,
            "price": self.prices.get(symbol, 100.0),
            "status": "filled",
            "filled_size": size,
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
