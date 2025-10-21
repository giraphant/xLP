#!/usr/bin/env python3
"""
Mock adapters for integration testing

这些mock adapters模拟真实的I/O操作，用于测试HedgeBot的协调逻辑
"""

from typing import Dict, List, Optional
from datetime import datetime


class MockExchangeClient:
    """模拟交易所客户端"""

    def __init__(self):
        self.positions = {}  # {symbol: amount}
        self.prices = {}  # {symbol: price}
        self.orders = {}  # {order_id: order_info}
        self.order_counter = 1000

    async def get_positions(self) -> Dict[str, float]:
        """获取当前仓位"""
        return self.positions.copy()

    async def get_position(self, symbol: str) -> float:
        """获取单个币种的仓位"""
        return self.positions.get(symbol, 0.0)

    async def get_prices(self, symbols: List[str]) -> Dict[str, float]:
        """获取价格"""
        return {symbol: self.prices.get(symbol, 100.0) for symbol in symbols}

    async def get_price(self, symbol: str) -> float:
        """获取单个币种的价格"""
        return self.prices.get(symbol, 100.0)

    async def place_limit_order(
        self,
        symbol: str,
        side: str,
        size: float,
        price: float
    ) -> str:
        """下限价单"""
        order_id = f"ORDER-{self.order_counter}"
        self.order_counter += 1

        self.orders[order_id] = {
            "symbol": symbol,
            "side": side,
            "size": size,
            "price": price,
            "status": "open",
            "type": "limit"
        }

        return order_id

    # 别名：兼容旧测试
    async def place_order(self, symbol: str, side: str, size: float, price: float) -> str:
        """下限价单（别名）"""
        return await self.place_limit_order(symbol, side, size, price)

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        size: float
    ) -> str:
        """下市价单"""
        order_id = f"ORDER-{self.order_counter}"
        self.order_counter += 1

        self.orders[order_id] = {
            "symbol": symbol,
            "side": side,
            "size": size,
            "status": "filled",
            "type": "market"
        }

        # 立即更新仓位
        if side == "buy":
            self.positions[symbol] = self.positions.get(symbol, 0.0) + size
        else:
            self.positions[symbol] = self.positions.get(symbol, 0.0) - size

        return order_id

    async def cancel_order(self, symbol: str, order_id: str):
        """撤单"""
        if order_id in self.orders:
            self.orders[order_id]["status"] = "cancelled"

    async def get_order_status(self, symbol: str, order_id: str) -> str:
        """获取订单状态"""
        if order_id in self.orders:
            return self.orders[order_id]["status"]
        return "unknown"

    def set_position(self, symbol: str, amount: float):
        """设置仓位（测试用）"""
        self.positions[symbol] = amount

    def set_price(self, symbol: str, price: float):
        """设置价格（测试用）"""
        self.prices[symbol] = price

    def fill_order(self, order_id: str):
        """模拟订单成交（测试用）"""
        if order_id in self.orders:
            order = self.orders[order_id]
            order["status"] = "filled"

            # 更新仓位
            symbol = order["symbol"]
            size = order["size"]
            side = order["side"]

            if side == "buy":
                self.positions[symbol] = self.positions.get(symbol, 0.0) + size
            else:
                self.positions[symbol] = self.positions.get(symbol, 0.0) - size


class MockStateStore:
    """
    模拟状态存储 - 匹配新的同步 API

    注意：使用真实的 StateStore 即可，这里只是简化版本
    """

    def __init__(self):
        # 直接使用真实的 StateStore
        from adapters.state_store import StateStore
        self._store = StateStore()

    def get_symbol_state(self, symbol: str):
        """获取symbol状态（同步）"""
        return self._store.get_symbol_state(symbol)

    def update_symbol_state(self, symbol: str, updater):
        """更新symbol状态（同步）"""
        return self._store.update_symbol_state(symbol, updater)

    def start_monitoring(self, symbol: str, order_id: str, zone: int):
        """快捷方法：开始监控"""
        return self._store.start_monitoring(symbol, order_id, zone)

    def stop_monitoring(self, symbol: str, with_fill: bool = False):
        """快捷方法：停止监控"""
        return self._store.stop_monitoring(symbol, with_fill)

    def clear(self):
        """清空状态"""
        return self._store.clear()

    def get_all_states(self):
        """获取所有状态"""
        return self._store.get_all_states()


class MockPoolFetcher:
    """模拟池子数据获取器"""

    def __init__(self):
        self.pool_hedges = {}  # {pool_name: {symbol: hedge}}

    async def fetch_pool_hedges(self, pool_configs: Dict[str, dict]) -> Dict[str, float]:
        """获取池子对冲数据"""
        all_hedges = {}

        for pool_name, config in pool_configs.items():
            amount = config.get("amount", 0)
            if amount == 0:
                continue

            # 获取该池子的hedges
            pool_data = self.pool_hedges.get(pool_name, {})

            # 按amount比例缩放
            for symbol, hedge in pool_data.items():
                scaled_hedge = hedge * (amount / 1000.0)  # 假设1000是基准
                all_hedges[symbol] = all_hedges.get(symbol, 0.0) + scaled_hedge

        return all_hedges

    def set_pool_hedges(self, pool_name: str, hedges: Dict[str, float]):
        """设置池子数据（测试用）"""
        self.pool_hedges[pool_name] = hedges


class MockPlugin:
    """模拟插件 - 用于测试回调"""

    def __init__(self):
        self.decisions = []
        self.actions = []
        self.errors = []
        self.reports = []

    async def on_decision(self, symbol: str, decision, **kwargs):
        """决策回调"""
        self.decisions.append({
            "symbol": symbol,
            "decision": decision,
            "kwargs": kwargs
        })

    async def on_action(self, symbol: str, action: str, result: dict, **kwargs):
        """执行回调"""
        self.actions.append({
            "symbol": symbol,
            "action": action,
            "result": result,
            "kwargs": kwargs
        })

    async def on_error(self, error: str = None, **kwargs):
        """错误回调"""
        self.errors.append({
            "error": error,
            "kwargs": kwargs
        })

    async def on_report(self, summary: dict, **kwargs):
        """报告回调"""
        self.reports.append({
            "summary": summary,
            "kwargs": kwargs
        })

    def reset(self):
        """重置所有记录"""
        self.decisions.clear()
        self.actions.clear()
        self.errors.clear()
        self.reports.clear()
