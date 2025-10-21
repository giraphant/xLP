#!/usr/bin/env python3
"""
状态存储 - 高性能版本

性能优化：
- 使用 dataclass(frozen=True) → 无需 deepcopy
- 同步锁（非 async） → 减少开销
- 细粒度锁（per-symbol） → 并发性能更好

替代原来 191 行的版本，优化为 ~120 行
"""

import threading
import logging
from typing import Dict, Optional, Callable
from collections import defaultdict

from core.state import SymbolState

logger = logging.getLogger(__name__)


class StateStore:
    """
    状态存储 - Linus 风格重构版

    核心改进：
    1. 同步操作（纯内存，不需要 async）
    2. frozen dataclass（不可变，无需拷贝）
    3. 细粒度锁（每个 symbol 独立锁）
    """

    def __init__(self):
        """初始化状态存储"""
        # Symbol 状态存储
        self._states: Dict[str, SymbolState] = {}

        # 细粒度锁：每个 symbol 一个锁
        self._locks: Dict[str, threading.Lock] = defaultdict(threading.Lock)

        # 全局锁（仅用于 get_all, clear 等全局操作）
        self._global_lock = threading.Lock()

        # 元数据存储（目前未使用，保留兼容性）
        self._metadata: Dict = {}

    def get_symbol_state(self, symbol: str) -> SymbolState:
        """
        获取 symbol 状态（同步操作）

        Args:
            symbol: 交易对符号

        Returns:
            SymbolState（默认为空状态）

        注意：
            - frozen dataclass 不可变，直接返回无需拷贝
            - O(1) 查找，无锁读取（Python GIL 保护）
        """
        # Python dict 的 get 操作在 GIL 下是线程安全的
        # 由于 SymbolState 是 frozen，直接返回即可
        return self._states.get(symbol, SymbolState())

    def update_symbol_state(
        self,
        symbol: str,
        updater: Callable[[SymbolState], SymbolState]
    ) -> SymbolState:
        """
        原子更新 symbol 状态

        Args:
            symbol: 交易对符号
            updater: 更新函数 (old_state) -> new_state

        Returns:
            更新后的 SymbolState

        Example:
            >>> state.update_symbol_state(
            ...     "SOL",
            ...     lambda s: s.start_monitoring("order123", zone=2)
            ... )

        注意：
            - 使用 per-symbol 锁，不同 symbol 可并发更新
            - frozen dataclass 确保不会意外修改
        """
        with self._locks[symbol]:
            old_state = self._states.get(symbol, SymbolState())
            new_state = updater(old_state)
            self._states[symbol] = new_state
            logger.debug(f"State updated: {symbol}")
            return new_state

    def set_symbol_state(self, symbol: str, state: SymbolState):
        """
        直接设置 symbol 状态（完全替换）

        Args:
            symbol: 交易对符号
            state: 新的状态
        """
        with self._locks[symbol]:
            self._states[symbol] = state
            logger.debug(f"State set: {symbol}")

    def delete_symbol_state(self, symbol: str):
        """
        删除 symbol 状态

        Args:
            symbol: 交易对符号
        """
        with self._locks[symbol]:
            if symbol in self._states:
                del self._states[symbol]
                logger.debug(f"State deleted: {symbol}")

    # 全局操作（需要全局锁）

    def get_all_states(self) -> Dict[str, SymbolState]:
        """
        获取所有 symbol 状态

        Returns:
            Dict[symbol, SymbolState]

        注意：
            - frozen dataclass，返回的 dict 是新的，但内容无需拷贝
        """
        with self._global_lock:
            # 浅拷贝 dict，但值是 frozen dataclass 无需深拷贝
            return dict(self._states)

    def clear(self):
        """清空所有状态"""
        with self._global_lock:
            self._states.clear()
            # 清理锁（可选，避免内存泄漏）
            self._locks.clear()
            logger.info("State cleared")

    # 元数据管理（兼容旧接口）

    def get_metadata(self) -> dict:
        """获取全局元数据"""
        with self._global_lock:
            return dict(self._metadata)

    def update_metadata(self, updates: dict):
        """更新全局元数据"""
        with self._global_lock:
            self._metadata.update(updates)

    # 便捷方法：常见操作的快捷方式

    def start_monitoring(self, symbol: str, order_id: str, zone: int) -> SymbolState:
        """快捷方法：开始监控"""
        return self.update_symbol_state(
            symbol,
            lambda s: s.start_monitoring(order_id, zone)
        )

    def stop_monitoring(self, symbol: str, with_fill: bool = False) -> SymbolState:
        """快捷方法：停止监控"""
        from datetime import datetime
        return self.update_symbol_state(
            symbol,
            lambda s: s.stop_monitoring(
                fill_time=datetime.now() if with_fill else None
            )
        )

    def update_offset(
        self,
        symbol: str,
        offset: float,
        cost_basis: float,
        zone: Optional[int]
    ) -> SymbolState:
        """快捷方法：更新 offset"""
        return self.update_symbol_state(
            symbol,
            lambda s: s.update_offset(offset, cost_basis, zone)
        )
