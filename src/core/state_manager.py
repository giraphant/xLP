#!/usr/bin/env python3
"""
状态管理器 - 集中管理所有状态操作
确保状态更新的原子性和一致性
"""

import json
import asyncio
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Any
import logging

logger = logging.getLogger(__name__)


class StateManager:
    """
    集中管理所有状态操作，确保原子性和一致性

    特性：
    - 线程安全的状态更新
    - 自动备份机制
    - 事务性批量更新
    - 状态验证
    """

    def __init__(self, state_path: Path, backup_dir: Optional[Path] = None):
        """
        Args:
            state_path: 状态文件路径
            backup_dir: 备份目录路径（可选）
        """
        self._state_path = Path(state_path)
        self._backup_dir = Path(backup_dir) if backup_dir else self._state_path.parent / "backups"
        self._lock = asyncio.Lock()
        self._state = self._load_state()
        self._dirty = False  # 标记是否有未保存的更改

        # 确保备份目录存在
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    def _load_state(self) -> dict:
        """加载状态文件"""
        if not self._state_path.exists():
            # 使用模板初始化
            template_path = Path("state_template.json")
            if template_path.exists():
                with open(template_path, 'r', encoding='utf-8') as f:
                    state = json.load(f)
            else:
                state = self._get_default_state()

            # 保存初始状态
            self._save_state_sync(state)
            return state

        try:
            with open(self._state_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse state file: {e}")
            # 尝试从备份恢复
            return self._restore_from_backup()

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

    def _save_state_sync(self, state: dict):
        """同步保存状态（内部使用）"""
        # 创建临时文件，避免写入失败导致数据丢失
        temp_path = self._state_path.with_suffix('.tmp')

        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)

            # 原子性替换
            temp_path.replace(self._state_path)

        except Exception as e:
            logger.error(f"Failed to save state: {e}")
            if temp_path.exists():
                temp_path.unlink()
            raise

    async def save_state(self):
        """异步保存状态"""
        async with self._lock:
            if not self._dirty:
                return

            self._save_state_sync(self._state)
            self._dirty = False
            logger.debug("State saved successfully")

    async def create_backup(self, tag: str = None) -> Path:
        """创建状态备份"""
        async with self._lock:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            tag_suffix = f"_{tag}" if tag else ""
            backup_path = self._backup_dir / f"state_{timestamp}{tag_suffix}.json"

            try:
                shutil.copy2(self._state_path, backup_path)
                logger.info(f"Created backup: {backup_path}")

                # 清理旧备份（保留最近10个）
                await self._cleanup_old_backups()

                return backup_path
            except Exception as e:
                logger.error(f"Failed to create backup: {e}")
                raise

    async def _cleanup_old_backups(self, keep_count: int = 10):
        """清理旧的备份文件"""
        backups = sorted(self._backup_dir.glob("state_*.json"), key=lambda p: p.stat().st_mtime)

        if len(backups) > keep_count:
            for backup in backups[:-keep_count]:
                try:
                    backup.unlink()
                    logger.debug(f"Deleted old backup: {backup}")
                except Exception as e:
                    logger.warning(f"Failed to delete backup {backup}: {e}")

    def _restore_from_backup(self) -> dict:
        """从备份恢复状态"""
        backups = sorted(self._backup_dir.glob("state_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)

        for backup in backups[:3]:  # 尝试最新的3个备份
            try:
                with open(backup, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                logger.info(f"Restored state from backup: {backup}")
                return state
            except Exception as e:
                logger.warning(f"Failed to restore from {backup}: {e}")
                continue

        # 所有备份都失败，返回默认状态
        logger.warning("All backups failed, using default state")
        return self._get_default_state()

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

            self._dirty = True
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
            self._dirty = True

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

            self._dirty = True

    async def reset_symbol_monitoring(self, symbol: str):
        """重置币种的监控状态"""
        await self.update_symbol_state(symbol, {
            "monitoring": {
                "active": False,
                "started_at": None,
                "current_zone": None,
                "order_id": None
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

    @property
    def state_path(self) -> Path:
        """获取状态文件路径"""
        return self._state_path

    @property
    def is_dirty(self) -> bool:
        """是否有未保存的更改"""
        return self._dirty