#!/usr/bin/env python3
"""
决策逻辑 - 纯函数

替代原来230行的DecisionEngine.decide()方法。
拆分成5个小函数，每个 < 30行，零依赖，100%可测试。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Decision:
    """
    决策结果 - 简单的数据类

    替代原来复杂的TradingAction对象
    """
    action: str  # "place_order" | "market_order" | "cancel" | "alert" | "wait"
    side: Optional[str] = None  # "buy" | "sell"
    size: float = 0.0
    price: float = 0.0
    reason: str = ""
    metadata: dict | None = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


def decide_on_threshold_breach(
    offset_usd: float,
    max_threshold: float
) -> Decision:
    """
    决策1: 检查是否超过最大阈值

    Args:
        offset_usd: 偏移USD价值（绝对值）
        max_threshold: 最大阈值

    Returns:
        Decision对象

    Logic:
        - 如果超过最大阈值 -> 警报
        - 否则 -> 继续检查其他条件
    """
    abs_usd = abs(offset_usd)

    if abs_usd > max_threshold:
        return Decision(
            action="alert",
            reason=f"Threshold exceeded: ${abs_usd:.2f} > ${max_threshold:.2f}",
            metadata={"offset_usd": abs_usd, "max_threshold": max_threshold}
        )

    return Decision(action="wait", reason="Within max threshold")


def decide_on_timeout(
    started_at: Optional[datetime],
    timeout_minutes: int,
    offset: float,
    close_ratio: float
) -> Optional[Decision]:
    """
    决策2: 检查订单是否超时

    Args:
        started_at: 订单开始时间（None表示无订单）
        timeout_minutes: 超时分钟数
        offset: 偏移量
        close_ratio: 平仓比例

    Returns:
        Decision对象（如果超时），否则None

    Logic:
        - 如果有订单且超时 -> 市价平仓
        - 否则 -> 不操作
    """
    if started_at is None:
        return None

    elapsed_minutes = (datetime.now() - started_at).total_seconds() / 60

    if elapsed_minutes >= timeout_minutes:
        side = "sell" if offset > 0 else "buy"
        size = abs(offset) * close_ratio / 100

        return Decision(
            action="market_order",
            side=side,
            size=size,
            reason=f"Timeout after {elapsed_minutes:.1f}min",
            metadata={
                "force_close": True,
                "timeout_minutes": elapsed_minutes,
                "offset": offset
            }
        )

    return None


def decide_on_zone_change(
    old_zone: Optional[int],
    new_zone: Optional[int],
    in_cooldown: bool,
    offset: float,
    cost_basis: float,
    close_ratio: float,
    price_offset_pct: float
) -> Decision:
    """
    决策3: 检查Zone变化

    Args:
        old_zone: 旧的zone编号（None表示在阈值内）
        new_zone: 新的zone编号（None表示在阈值内）
        in_cooldown: 是否在cooldown期间
        offset: 偏移量
        cost_basis: 成本基础
        close_ratio: 平仓比例
        price_offset_pct: 价格偏移百分比

    Returns:
        Decision对象

    Logic:
        - 如果在cooldown期间 -> 使用cooldown逻辑
        - 如果zone无变化 -> 不操作
        - 如果zone → None -> 撤单
        - 如果进入新zone -> 挂单
    """
    # Cooldown期间的特殊逻辑
    if in_cooldown:
        return _decide_in_cooldown(
            old_zone, new_zone, offset,
            cost_basis, close_ratio, price_offset_pct
        )

    # 正常期间
    if new_zone == old_zone:
        return Decision(action="wait", reason="No zone change")

    if new_zone is None:
        return Decision(action="cancel", reason="Back within threshold")

    # 进入新zone，挂限价单
    return _create_limit_order_decision(
        offset, cost_basis, close_ratio,
        price_offset_pct, new_zone
    )


def _decide_in_cooldown(
    old_zone: Optional[int],
    new_zone: Optional[int],
    offset: float,
    cost_basis: float,
    close_ratio: float,
    price_offset_pct: float
) -> Decision:
    """
    Cooldown期间的决策逻辑（辅助函数）

    Args:
        old_zone: 上次成交时的zone
        new_zone: 当前zone
        offset: 偏移量
        cost_basis: 成本基础
        close_ratio: 平仓比例
        price_offset_pct: 价格偏移百分比

    Returns:
        Decision对象

    Logic:
        - Zone → None: 撤单（回到阈值内）
        - 上次在阈值内，现在进入zone: 正常挂单
        - Zone恶化（数字变大）: 重新挂单
        - Zone改善（数字变小）: 等待观察
    """
    # 情况1: Zone → None (回到阈值内)
    if new_zone is None:
        return Decision(action="cancel", reason="Cooldown: back within threshold")

    # 情况2: 上次成交在阈值内，现在进入zone
    if old_zone is None:
        return _create_limit_order_decision(
            offset, cost_basis, close_ratio,
            price_offset_pct, new_zone
        )

    # 情况3: Zone恶化 (offset增大)
    if new_zone > old_zone:
        return _create_limit_order_decision(
            offset, cost_basis, close_ratio,
            price_offset_pct, new_zone
        )

    # 情况4: Zone改善或持平 (offset减小或不变)
    return Decision(
        action="wait",
        reason=f"Cooldown: zone improved {old_zone}→{new_zone}, waiting for natural regression"
    )


def _create_limit_order_decision(
    offset: float,
    cost_basis: float,
    close_ratio: float,
    price_offset_pct: float,
    zone: int
) -> Decision:
    """
    创建限价单决策（辅助函数）

    Args:
        offset: 偏移量
        cost_basis: 成本基础
        close_ratio: 平仓比例
        price_offset_pct: 价格偏移百分比
        zone: Zone编号

    Returns:
        Decision对象
    """
    side = "sell" if offset > 0 else "buy"
    size = abs(offset) * close_ratio / 100

    # 计算挂单价格
    if offset > 0:
        price = cost_basis * (1 + price_offset_pct / 100)
    else:
        price = cost_basis * (1 - price_offset_pct / 100)

    return Decision(
        action="place_order",
        side=side,
        size=size,
        price=price,
        reason=f"Zone {zone}",
        metadata={"zone": zone, "offset": offset, "cost_basis": cost_basis}
    )


def check_cooldown(
    last_fill_time: Optional[datetime],
    cooldown_minutes: int
) -> bool:
    """
    检查是否在cooldown期间

    Args:
        last_fill_time: 上次成交时间（None表示从未成交）
        cooldown_minutes: Cooldown时长（分钟）

    Returns:
        True if in cooldown, False otherwise
    """
    if last_fill_time is None:
        return False

    elapsed_minutes = (datetime.now() - last_fill_time).total_seconds() / 60
    return elapsed_minutes < cooldown_minutes
