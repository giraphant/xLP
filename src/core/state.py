#!/usr/bin/env python3
"""
状态数据结构 - 强类型 dataclass

替代原来松散的 dict，提供：
- 类型安全
- 不可变性（减少拷贝）
- IDE 自动补全
- 更好的性能
"""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class MonitoringState:
    """
    订单监控状态

    frozen=True 使其不可变，无需 deepcopy
    """
    active: bool = False
    order_id: Optional[str] = None
    current_zone: Optional[int] = None
    started_at: Optional[datetime] = None

    def with_order(self, order_id: str, zone: int) -> "MonitoringState":
        """创建一个新的监控状态（有订单）"""
        return replace(
            self,
            active=True,
            order_id=order_id,
            current_zone=zone,
            started_at=datetime.now()
        )

    def deactivate(self) -> "MonitoringState":
        """创建一个新的监控状态（停止监控）"""
        return replace(self, active=False, order_id=None)


@dataclass(frozen=True)
class SymbolState:
    """
    Symbol 完整状态

    包含：
    - 基础状态：offset, cost_basis, zone
    - 监控状态：monitoring
    - 最后成交时间：last_fill_time
    """
    # 基础状态
    offset: float = 0.0
    cost_basis: float = 0.0
    zone: Optional[int] = None

    # 监控状态
    monitoring: MonitoringState = MonitoringState()

    # 最后成交时间
    last_fill_time: Optional[datetime] = None

    def update_offset(self, offset: float, cost_basis: float, zone: Optional[int]) -> "SymbolState":
        """更新 offset 相关字段"""
        return replace(
            self,
            offset=offset,
            cost_basis=cost_basis,
            zone=zone
        )

    def start_monitoring(self, order_id: str, zone: int) -> "SymbolState":
        """开始监控（挂单成功）"""
        return replace(
            self,
            monitoring=self.monitoring.with_order(order_id, zone)
        )

    def stop_monitoring(self, fill_time: Optional[datetime] = None) -> "SymbolState":
        """停止监控（订单完成或取消）"""
        updates = {"monitoring": self.monitoring.deactivate()}
        if fill_time:
            updates["last_fill_time"] = fill_time
        return replace(self, **updates)
