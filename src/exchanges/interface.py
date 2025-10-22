#!/usr/bin/env python3
"""
交易所接口抽象层 - 纯接口定义
提供统一的交易所接口，可扩展支持不同交易所
"""

from abc import ABC, abstractmethod


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
    async def cancel_all_orders(self, symbol: str) -> int:
        """
        取消该币种的所有活跃订单

        Args:
            symbol: 币种符号

        Returns:
            取消的订单数量
        """
        pass
