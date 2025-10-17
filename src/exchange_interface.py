#!/usr/bin/env python3
"""
交易所接口抽象层
提供统一的接口，可扩展支持不同交易所
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict


class ExchangeInterface(ABC):
    """交易所接口基类"""

    def __init__(self, config: dict):
        """
        Args:
            config: 交易所配置
                {
                    "name": "lighter",
                    "api_key": "...",
                    "api_secret": "...",
                    "testnet": false
                }
        """
        self.config = config
        self.name = config["name"]

    @abstractmethod
    async def get_position(self, symbol: str) -> float:
        """
        获取当前持仓数量

        Args:
            symbol: 币种符号 (如 "SOL", "ETH", "BTC")

        Returns:
            持仓数量，负数表示空头，正数表示多头，0表示无持仓
        """
        pass

    @abstractmethod
    async def get_price(self, symbol: str) -> float:
        """
        获取当前市场价格

        Args:
            symbol: 币种符号

        Returns:
            当前价格
        """
        pass

    @abstractmethod
    async def place_limit_order(
        self,
        symbol: str,
        side: str,
        size: float,
        price: float
    ) -> str:
        """
        下限价单

        Args:
            symbol: 币种符号
            side: "buy" 或 "sell"
            size: 数量
            price: 价格

        Returns:
            订单ID
        """
        pass

    @abstractmethod
    async def place_market_order(
        self,
        symbol: str,
        side: str,
        size: float
    ) -> str:
        """
        下市价单

        Args:
            symbol: 币种符号
            side: "buy" 或 "sell"
            size: 数量

        Returns:
            订单ID
        """
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """
        撤销订单

        Args:
            order_id: 订单ID

        Returns:
            是否成功
        """
        pass

    @abstractmethod
    async def get_order_status(self, order_id: str) -> Dict:
        """
        查询订单状态

        Args:
            order_id: 订单ID

        Returns:
            {
                "status": "open" | "filled" | "canceled",
                "filled_size": 已成交数量,
                "remaining_size": 剩余数量
            }
        """
        pass


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

    async def get_order_status(self, order_id: str) -> Dict:
        if order_id not in self.orders:
            return {"status": "not_found", "filled_size": 0.0, "remaining_size": 0.0}

        order = self.orders[order_id]
        return {
            "status": order["status"],
            "filled_size": order["filled_size"],
            "remaining_size": order["size"] - order["filled_size"],
        }


class LighterExchange(ExchangeInterface):
    """
    Lighter交易所实现
    """

    # Symbol to Lighter market ID mapping
    SYMBOL_MAP = {
        "SOL": "SOL_USDC",
        "ETH": "ETH_USDC",
        "BTC": "BTC_USDC",
        "BONK": "BONK_USDC",
    }

    def __init__(self, config: dict):
        super().__init__(config)

        from lighter_integration import LighterClient

        # Initialize Lighter client
        self.lighter_client = LighterClient(
            private_key=config.get("api_key", config.get("private_key")),
            account_index=config.get("account_index", 0),
            api_key_index=config.get("api_key_index", 0),
            base_url=config.get("base_url", "https://mainnet.zklighter.elliot.ai")
        )

        # Track order IDs per symbol for cancellation
        self.order_map = {}  # {order_id: (symbol, market_id)}

    def _get_market_id(self, symbol: str) -> str:
        """Convert symbol to Lighter market ID"""
        return self.SYMBOL_MAP.get(symbol.upper(), f"{symbol.upper()}_USDC")

    async def get_position(self, symbol: str) -> float:
        """获取当前持仓数量"""
        market_id = self._get_market_id(symbol)
        position = await self.lighter_client.get_position(market_id)
        return position

    async def get_price(self, symbol: str) -> float:
        """获取当前市场价格"""
        market_id = self._get_market_id(symbol)
        price = await self.lighter_client.get_price(market_id)
        return price

    async def place_limit_order(
        self,
        symbol: str,
        side: str,
        size: float,
        price: float
    ) -> str:
        """下限价单"""
        market_id = self._get_market_id(symbol)
        order_id = await self.lighter_client.place_limit_order(
            market_id=market_id,
            side=side,
            size=size,
            price=price,
            reduce_only=False
        )

        # Store mapping for cancellation
        self.order_map[order_id] = (symbol, market_id)
        return order_id

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        size: float
    ) -> str:
        """下市价单"""
        market_id = self._get_market_id(symbol)
        order_id = await self.lighter_client.place_market_order(
            market_id=market_id,
            side=side,
            size=size
        )

        # Store mapping for cancellation
        self.order_map[order_id] = (symbol, market_id)
        return order_id

    async def cancel_order(self, order_id: str) -> bool:
        """撤销订单"""
        if order_id not in self.order_map:
            # Try to extract market ID from order ID or use default
            # This is a fallback - ideally we should always have the mapping
            return False

        symbol, market_id = self.order_map[order_id]
        success = await self.lighter_client.cancel_order(market_id, order_id)

        if success:
            del self.order_map[order_id]

        return success

    async def get_order_status(self, order_id: str) -> Dict:
        """查询订单状态"""
        if order_id not in self.order_map:
            return {"status": "not_found", "filled_size": 0.0, "remaining_size": 0.0}

        symbol, market_id = self.order_map[order_id]
        status = await self.lighter_client.get_order_status(market_id, order_id)
        return status


def create_exchange(config: dict) -> ExchangeInterface:
    """
    工厂函数：根据配置创建交易所实例

    Args:
        config: 交易所配置

    Returns:
        ExchangeInterface实例
    """
    name = config.get("name", "").lower()

    if name == "mock":
        return MockExchange(config)
    elif name == "lighter":
        return LighterExchange(config)
    else:
        raise ValueError(f"Unknown exchange: {name}")
