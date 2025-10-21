"""
Action decision functions

Pure functions for deciding trading actions based on current state.
"""
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
import logging

# Import calculation functions
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from calculations.orders import calculate_close_size, calculate_limit_price

logger = logging.getLogger(__name__)


class ActionType(Enum):
    """操作类型"""
    PLACE_LIMIT_ORDER = "place_limit_order"
    PLACE_MARKET_ORDER = "place_market_order"
    CANCEL_ORDER = "cancel_order"
    NO_ACTION = "no_action"
    ALERT = "alert"


@dataclass
class TradingAction:
    """交易操作"""
    type: ActionType
    symbol: str
    side: Optional[str] = None  # buy/sell
    size: Optional[float] = None
    price: Optional[float] = None
    order_id: Optional[str] = None
    reason: str = ""
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


def decide_action(
    symbol: str,
    offset: float,
    cost_basis: float,
    current_price: float,
    offset_usd: float,
    zone: Optional[int],
    state: Dict[str, Any],
    config: Dict[str, Any]
) -> List[TradingAction]:
    """
    核心决策函数：根据当前状态决定需要执行的操作

    Pure function extracted from DecisionEngine.decide()

    Args:
        symbol: 币种符号
        offset: 偏移量
        cost_basis: 成本基础
        current_price: 当前价格
        offset_usd: 偏移USD价值
        zone: 区间编号（None=阈值内, 0-N=区间, -1=超阈值）
        state: 币种状态（只读）
            {
                "monitoring": {
                    "active": bool,
                    "current_zone": int,
                    "order_id": str,
                    "started_at": str
                },
                "last_fill_time": str
            }
        config: 配置（只读）
            {
                "close_ratio": float,
                "order_price_offset": float,
                "timeout_minutes": float,
                "cooldown_after_fill_minutes": float
            }

    Returns:
        操作列表
    """
    from .cooldown import is_in_cooldown, analyze_cooldown_status

    actions = []

    # 获取状态信息
    monitoring = state.get("monitoring", {})
    is_monitoring = monitoring.get("active", False)
    current_zone = monitoring.get("current_zone")
    existing_order_id = monitoring.get("order_id")
    started_at = monitoring.get("started_at")

    logger.debug(f"{symbol}: offset=${offset_usd:.2f}, zone={zone}, "
                f"current_zone={current_zone}, monitoring={is_monitoring}")

    # ========== 决策1: 检查是否超过最高阈值 ==========
    if zone == -1:
        logger.warning(f"{symbol}: Exceeded max threshold ${offset_usd:.2f}")

        # 撤销现有订单
        if existing_order_id:
            actions.append(TradingAction(
                type=ActionType.CANCEL_ORDER,
                symbol=symbol,
                order_id=existing_order_id,
                reason="Exceeded max threshold"
            ))

        # 发出警报
        actions.append(TradingAction(
            type=ActionType.ALERT,
            symbol=symbol,
            reason=f"Threshold exceeded: ${offset_usd:.2f}",
            metadata={
                "alert_type": "threshold_exceeded",
                "offset": offset,
                "offset_usd": offset_usd,
                "current_price": current_price
            }
        ))

        return actions

    # ========== 决策2: 检查超时 ==========
    if is_monitoring and started_at:
        started_time = datetime.fromisoformat(started_at)
        elapsed_minutes = (datetime.now() - started_time).total_seconds() / 60
        timeout_minutes = config.get("timeout_minutes", 20)

        if elapsed_minutes >= timeout_minutes:
            logger.warning(f"{symbol}: Order timeout after {elapsed_minutes:.1f} minutes")

            # 撤销现有订单
            if existing_order_id:
                actions.append(TradingAction(
                    type=ActionType.CANCEL_ORDER,
                    symbol=symbol,
                    order_id=existing_order_id,
                    reason=f"Timeout after {elapsed_minutes:.1f} minutes"
                ))

            # 市价平仓（100%）
            order_size = calculate_close_size(offset, 100.0)
            side = "sell" if offset > 0 else "buy"

            actions.append(TradingAction(
                type=ActionType.PLACE_MARKET_ORDER,
                symbol=symbol,
                side=side,
                size=order_size,
                reason="Force close due to timeout",
                metadata={
                    "force_close": True,
                    "timeout_minutes": elapsed_minutes,
                    "offset": offset,
                    "cost_basis": cost_basis
                }
            ))

            return actions

    # ========== 决策3: 区间变化处理 ==========
    if zone != current_zone:
        logger.info(f"{symbol}: Zone changed from {current_zone} to {zone}")

        # 检查冷却期
        last_fill_time_str = state.get("last_fill_time")
        last_fill_time = None
        if last_fill_time_str:
            last_fill_time = datetime.fromisoformat(last_fill_time_str)

        in_cooldown_flag, cooldown_remaining = is_in_cooldown(
            last_fill_time,
            config.get("cooldown_after_fill_minutes", 5)
        )

        # 冷却期内的特殊处理
        if in_cooldown_flag:
            logger.info(f"{symbol}: In cooldown period ({cooldown_remaining:.1f}min remaining)")

            # 分析冷却期状态
            cooldown_status, cooldown_reason = analyze_cooldown_status(
                current_zone,
                zone,
                in_cooldown_flag,
                cooldown_remaining
            )

            # 情况1: 回到阈值内 (Zone → None)
            if cooldown_status == "cancel_only":
                logger.info(f"{symbol}: {cooldown_reason}")
                if existing_order_id:
                    actions.append(TradingAction(
                        type=ActionType.CANCEL_ORDER,
                        symbol=symbol,
                        order_id=existing_order_id,
                        reason=cooldown_reason
                    ))
                actions.append(TradingAction(
                    type=ActionType.NO_ACTION,
                    symbol=symbol,
                    reason="Within threshold during cooldown"
                ))
                return actions

            # 情况2: Zone恶化 (增大)
            elif cooldown_status == "re_order":
                logger.warning(f"{symbol}: {cooldown_reason}")

                # 撤销旧订单
                if existing_order_id:
                    actions.append(TradingAction(
                        type=ActionType.CANCEL_ORDER,
                        symbol=symbol,
                        order_id=existing_order_id,
                        reason=f"Zone worsened during cooldown: {current_zone} → {zone}"
                    ))

                # 挂新的限价单
                order_price = calculate_limit_price(offset, cost_basis, config.get("order_price_offset", 0.2))
                order_size = calculate_close_size(offset, config.get("close_ratio", 40.0))
                side = "sell" if offset > 0 else "buy"

                actions.append(TradingAction(
                    type=ActionType.PLACE_LIMIT_ORDER,
                    symbol=symbol,
                    side=side,
                    size=order_size,
                    price=order_price,
                    reason=f"Zone worsened to {zone} during cooldown",
                    metadata={
                        "zone": zone,
                        "offset": offset,
                        "offset_usd": offset_usd,
                        "cost_basis": cost_basis,
                        "in_cooldown": True
                    }
                ))
                return actions

            # 情况3: Zone改善 (减小)
            elif cooldown_status == "skip":
                logger.info(f"{symbol}: {cooldown_reason}")
                actions.append(TradingAction(
                    type=ActionType.NO_ACTION,
                    symbol=symbol,
                    reason=cooldown_reason
                ))
                return actions

        # 非冷却期：正常的区间变化处理
        # 撤销旧订单（如果有）
        if is_monitoring and existing_order_id:
            actions.append(TradingAction(
                type=ActionType.CANCEL_ORDER,
                symbol=symbol,
                order_id=existing_order_id,
                reason=f"Zone changed from {current_zone} to {zone}"
            ))

        # 根据新区间决定操作
        if zone is None:
            # 回到阈值内，不需要操作
            logger.info(f"{symbol}: Back within threshold, no action needed")
            actions.append(TradingAction(
                type=ActionType.NO_ACTION,
                symbol=symbol,
                reason="Within threshold"
            ))
        else:
            # 进入新区间，挂限价单
            order_price = calculate_limit_price(offset, cost_basis, config.get("order_price_offset", 0.2))
            order_size = calculate_close_size(offset, config.get("close_ratio", 40.0))
            side = "sell" if offset > 0 else "buy"

            logger.info(f"{symbol}: Placing {side} order for {order_size:.4f} @ ${order_price:.2f}")

            actions.append(TradingAction(
                type=ActionType.PLACE_LIMIT_ORDER,
                symbol=symbol,
                side=side,
                size=order_size,
                price=order_price,
                reason=f"Entered zone {zone}",
                metadata={
                    "zone": zone,
                    "offset": offset,
                    "offset_usd": offset_usd,
                    "cost_basis": cost_basis
                }
            ))

    # ========== 决策4: 无变化 ==========
    if not actions:
        actions.append(TradingAction(
            type=ActionType.NO_ACTION,
            symbol=symbol,
            reason=f"No change needed (zone={zone})"
        ))

    return actions
