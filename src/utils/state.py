#!/usr/bin/env python3
"""
内存状态管理器 - 运行时状态跟踪
纯内存模式，不持久化状态，每次重启全新评估
"""

import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class StateManager:
    """
    内存状态管理器 - 运行时状态跟踪

    特性：
    - 纯内存模式，不持久化（每次重启全新状态）
    - 异步安全的状态更新（asyncio.Lock）
    - 深度合并更新，支持嵌套字典

    设计理念：
    - 简单可靠：无状态污染，每次重启重新评估
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
            "last_check": None
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
            }
        }

    async def update_symbol_state(self, symbol: str, updates: dict):
        """
        原子更新单个币种状态

        Args:
            symbol: 币种符号
            updates: 要更新的字段
        """
        async with self._lock:
            # 确保symbols字典存在
            if "symbols" not in self._state:
                self._state["symbols"] = {}

            # 确保币种存在
            if symbol not in self._state["symbols"]:
                self._state["symbols"][symbol] = self._get_default_symbol_state()

            # 深度合并更新
            self._deep_merge(self._state["symbols"][symbol], updates)

            # 更新时间戳
            self._state["symbols"][symbol]["last_updated"] = datetime.now().isoformat()
            logger.debug(f"Updated state for {symbol}: {updates}")

    def _deep_merge(self, target: dict, source: dict):
        """深度合并字典"""
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._deep_merge(target[key], value)
            else:
                target[key] = value