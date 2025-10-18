#!/usr/bin/env python3
"""
内存状态管理器 - 运行时状态跟踪
纯内存模式，不持久化状态，每次重启全新评估
"""

import json
import asyncio
from datetime import datetime
from typing import Dict
import logging

logger = logging.getLogger(__name__)


class StateManager:
    """
    内存状态管理器 - 运行时状态跟踪

    特性：
    - 纯内存模式，不持久化（每次重启全新状态）
    - 线程安全的状态更新
    - 事务性批量更新
    - 状态验证

    设计理念：
    - 简单可靠：无状态污染，每次重启重新评估
    - 日志驱动：所有操作记录在日志中，便于审计
    - 实时计算：offset和cost_basis基于当前市场状态
    """

    def __init__(self):
        """初始化内存状态管理器"""
        self._lock = asyncio.Lock()
        self._state = self._get_default_state()
        logger.info("StateManager initialized (in-memory mode, no persistence)")

    def _get_default_state(self) -> dict:
        """获取默认状态结构"""
        return {
            "symbols": {},
            "last_check": None,
            "version": "2.0",  # 添加版本号便于未来迁移
            "metadata": {
                "created_at": datetime.now().isoformat(),
                "total_runs": 0,
                "last_error": None
            }
        }


    async def get_symbol_state(self, symbol: str) -> dict:
        """获取单个币种状态"""
        async with self._lock:
            if symbol not in self._state.get("symbols", {}):
                return self._get_default_symbol_state()
            return self._state["symbols"][symbol].copy()

    def _get_default_symbol_state(self) -> dict:
        """获取默认币种状态"""
        return {
            "offset": 0.0,
            "cost_basis": 0.0,
            "last_updated": None,
            "monitoring": {
                "active": False,
                "started_at": None,
                "current_zone": None,
                "order_id": None
            },
            "stats": {
                "total_orders": 0,
                "successful_closes": 0,
                "forced_closes": 0
            }
        }

    async def update_symbol_state(self, symbol: str, updates: dict, validate: bool = True):
        """
        原子更新单个币种状态

        Args:
            symbol: 币种符号
            updates: 要更新的字段
            validate: 是否验证更新内容
        """
        async with self._lock:
            # 确保symbols字典存在
            if "symbols" not in self._state:
                self._state["symbols"] = {}

            # 确保币种存在
            if symbol not in self._state["symbols"]:
                self._state["symbols"][symbol] = self._get_default_symbol_state()

            # 验证更新内容
            if validate:
                self._validate_symbol_update(updates)

            # 深度合并更新
            self._deep_merge(self._state["symbols"][symbol], updates)

            # 更新时间戳
            self._state["symbols"][symbol]["last_updated"] = datetime.now().isoformat()
            logger.debug(f"Updated state for {symbol}: {updates}")

    async def batch_update(self, updates: Dict[str, dict], transaction: bool = True):
        """
        批量更新多个币种状态

        Args:
            updates: {symbol: update_dict} 的映射
            transaction: 是否作为事务（全部成功或全部失败）
        """
        async with self._lock:
            if transaction:
                # 备份当前状态
                original_state = json.loads(json.dumps(self._state))

                try:
                    for symbol, update in updates.items():
                        await self.update_symbol_state(symbol, update, validate=True)
                except Exception as e:
                    # 回滚到原始状态
                    self._state = original_state
                    logger.error(f"Batch update failed, rolled back: {e}")
                    raise
            else:
                # 非事务模式，逐个更新，失败的跳过
                for symbol, update in updates.items():
                    try:
                        await self.update_symbol_state(symbol, update, validate=True)
                    except Exception as e:
                        logger.warning(f"Failed to update {symbol}: {e}")
                        continue

    def _validate_symbol_update(self, updates: dict):
        """验证币种状态更新内容"""
        # 验证数值字段
        numeric_fields = ["offset", "cost_basis"]
        for field in numeric_fields:
            if field in updates:
                if not isinstance(updates[field], (int, float)):
                    raise ValueError(f"{field} must be numeric, got {type(updates[field])}")
                if updates[field] < 0 and field == "cost_basis":
                    raise ValueError(f"cost_basis cannot be negative: {updates[field]}")

        # 验证监控状态
        if "monitoring" in updates:
            mon = updates["monitoring"]
            if "current_zone" in mon and mon["current_zone"] is not None:
                if not isinstance(mon["current_zone"], int) or mon["current_zone"] < -1:
                    raise ValueError(f"Invalid current_zone: {mon['current_zone']}")

    def _deep_merge(self, target: dict, source: dict):
        """深度合并字典"""
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._deep_merge(target[key], value)
            else:
                target[key] = value

    async def get_all_symbols(self) -> list:
        """获取所有已跟踪的币种"""
        async with self._lock:
            return list(self._state.get("symbols", {}).keys())

    async def get_metadata(self) -> dict:
        """获取元数据"""
        async with self._lock:
            return self._state.get("metadata", {}).copy()

    async def update_metadata(self, updates: dict):
        """更新元数据"""
        async with self._lock:
            if "metadata" not in self._state:
                self._state["metadata"] = {}

            self._deep_merge(self._state["metadata"], updates)

    async def increment_counter(self, symbol: str, counter_path: str, amount: int = 1):
        """
        增加计数器（原子操作）

        Args:
            symbol: 币种符号
            counter_path: 计数器路径，如 "stats.total_orders"
            amount: 增加的数量
        """
        async with self._lock:
            # 解析路径
            parts = counter_path.split(".")

            # 确保路径存在
            if symbol not in self._state.get("symbols", {}):
                self._state["symbols"][symbol] = self._get_default_symbol_state()

            # 导航到目标位置
            target = self._state["symbols"][symbol]
            for part in parts[:-1]:
                if part not in target:
                    target[part] = {}
                target = target[part]

            # 增加计数
            field = parts[-1]
            target[field] = target.get(field, 0) + amount

    async def reset_symbol_monitoring(self, symbol: str):
        """
        重置币种的监控状态

        注意：保留current_zone用于cooldown期间判断zone变化方向
        """
        await self.update_symbol_state(symbol, {
            "monitoring": {
                "active": False,
                "started_at": None,
                "order_id": None
                # current_zone保留，用于cooldown判断
            }
        })

    async def cleanup_stale_orders(self, timeout_minutes: int = 60):
        """清理超时的订单监控"""
        async with self._lock:
            now = datetime.now()

            for symbol, state in self._state.get("symbols", {}).items():
                monitoring = state.get("monitoring", {})
                if monitoring.get("active") and monitoring.get("started_at"):
                    started_at = datetime.fromisoformat(monitoring["started_at"])
                    elapsed = (now - started_at).total_seconds() / 60

                    if elapsed > timeout_minutes:
                        logger.warning(f"Cleaning stale order monitoring for {symbol}")
                        await self.reset_symbol_monitoring(symbol)