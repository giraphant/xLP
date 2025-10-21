#!/usr/bin/env python3
"""
状态存储 - 简单的内存存储

职责：
- 存储symbol状态（offset, cost_basis, zone等）
- 原子更新操作
- 线程安全

特点：
- 内存存储（简单、快速）
- 异步锁保护
- Deep merge更新
"""

import asyncio
import logging
from typing import Any, Optional
from copy import deepcopy

logger = logging.getLogger(__name__)


class StateStore:
    """
    状态存储 - 替代原来150行的StateManager

    简化为纯dict封装，~80行
    """

    def __init__(self):
        """初始化空状态"""
        self.data = {}
        self.lock = asyncio.Lock()

    async def get(self, key: str, default: Optional[Any] = None) -> Any:
        """
        获取状态

        Args:
            key: 键（通常是symbol）
            default: 默认值

        Returns:
            状态数据
        """
        async with self.lock:
            return deepcopy(self.data.get(key, default))

    async def set(self, key: str, value: Any):
        """
        设置状态（完全替换）

        Args:
            key: 键
            value: 值
        """
        async with self.lock:
            self.data[key] = deepcopy(value)
            logger.debug(f"State set: {key}")

    async def update(self, key: str, partial: dict):
        """
        更新状态（深度合并）

        Args:
            key: 键
            partial: 部分更新数据

        Example:
            >>> await state.set("SOL", {"offset": 10, "zone": 2})
            >>> await state.update("SOL", {"zone": 3})
            >>> await state.get("SOL")
            {"offset": 10, "zone": 3}  # offset保留，zone更新
        """
        async with self.lock:
            current = self.data.get(key, {})

            if not isinstance(current, dict):
                # 如果当前值不是dict，直接替换
                self.data[key] = deepcopy(partial)
            else:
                # Deep merge
                merged = self._deep_merge(current, partial)
                self.data[key] = merged

            logger.debug(f"State updated: {key}")

    async def delete(self, key: str):
        """
        删除状态

        Args:
            key: 键
        """
        async with self.lock:
            if key in self.data:
                del self.data[key]
                logger.debug(f"State deleted: {key}")

    async def get_all(self) -> dict:
        """
        获取所有状态

        Returns:
            完整的状态字典
        """
        async with self.lock:
            return deepcopy(self.data)

    async def clear(self):
        """清空所有状态"""
        async with self.lock:
            self.data.clear()
            logger.info("State cleared")

    def _deep_merge(self, base: dict, update: dict) -> dict:
        """
        深度合并两个字典

        Args:
            base: 基础字典
            update: 更新字典

        Returns:
            合并后的字典
        """
        result = deepcopy(base)

        for key, value in update.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                # 递归合并嵌套字典
                result[key] = self._deep_merge(result[key], value)
            else:
                # 直接替换
                result[key] = deepcopy(value)

        return result

    # 便捷方法：symbol状态管理

    async def get_symbol_state(self, symbol: str) -> dict:
        """
        获取symbol状态

        Args:
            symbol: 交易对符号

        Returns:
            状态字典，默认包含初始值
        """
        state = await self.get(symbol, {})

        # 确保基本字段存在
        if "offset" not in state:
            state["offset"] = 0.0
        if "cost_basis" not in state:
            state["cost_basis"] = 0.0
        if "zone" not in state:
            state["zone"] = None

        return state

    async def update_symbol_state(self, symbol: str, updates: dict):
        """
        更新symbol状态

        Args:
            symbol: 交易对符号
            updates: 更新数据
        """
        await self.update(symbol, updates)

    async def get_metadata(self) -> dict:
        """
        获取全局元数据

        Returns:
            元数据字典
        """
        return await self.get("__metadata__", {})

    async def update_metadata(self, updates: dict):
        """
        更新全局元数据

        Args:
            updates: 更新数据
        """
        await self.update("__metadata__", updates)
