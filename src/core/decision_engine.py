#!/usr/bin/env python3
"""
决策引擎 - 根据市场状态和偏移量决定交易操作
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

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


class DecisionEngine:
    """
    决策引擎 - 核心决策逻辑

    负责根据当前市场状态、偏移量、配置等信息决定需要执行的操作
    """

    def __init__(self, config: dict, state_manager):
        """
        Args:
            config: 配置字典
            state_manager: 状态管理器实例
        """
        self.config = config
        self.state_manager = state_manager

        # 提取关键配置
        self.threshold_min_usd = config.get("threshold_min_usd", 5.0)
        self.threshold_max_usd = config.get("threshold_max_usd", 20.0)
        self.threshold_step_usd = config.get("threshold_step_usd", 2.5)
        self.order_price_offset = config.get("order_price_offset", 0.2)
        self.close_ratio = config.get("close_ratio", 40.0)
        self.timeout_minutes = config.get("timeout_minutes", 20)
        self.cooldown_after_fill_minutes = config.get("cooldown_after_fill_minutes", 5)

        logger.info(f"DecisionEngine initialized with thresholds: "
                   f"${self.threshold_min_usd}-${self.threshold_max_usd} "
                   f"(step: ${self.threshold_step_usd})")

    def get_zone(self, offset_usd: float) -> Optional[int]:
        """
        根据偏移USD绝对值计算所在区间

        Args:
            offset_usd: 偏移USD价值（绝对值）

        Returns:
            None: 低于最低阈值
            0-N: 区间编号
            -1: 超过最高阈值（警报）
        """
        abs_usd = abs(offset_usd)

        if abs_usd < self.threshold_min_usd:
            return None

        if abs_usd > self.threshold_max_usd:
            return -1

        # 计算区间
        zone = int((abs_usd - self.threshold_min_usd) / self.threshold_step_usd)
        return zone

    def calculate_close_size(self, offset: float) -> float:
        """
        计算平仓数量

        Args:
            offset: 偏移量（正数或负数）

        Returns:
            应平仓的数量（根据close_ratio配置）
        """
        return abs(offset) * (self.close_ratio / 100)

    def calculate_order_price(
        self,
        cost_basis: float,
        offset: float
    ) -> float:
        """
        计算挂单价格

        Args:
            cost_basis: 成本基础
            offset: 偏移量（正=多头敞口，负=空头敞口）

        Returns:
            挂单价格
        """
        if offset > 0:
            # 多头敞口：需要卖出平仓，挂高价
            return cost_basis * (1 + self.order_price_offset / 100)
        else:
            # 空头敞口：需要买入平仓，挂低价
            return cost_basis * (1 - self.order_price_offset / 100)

    async def decide(
        self,
        symbol: str,
        offset: float,
        cost_basis: float,
        current_price: float,
        offset_usd: float
    ) -> List[TradingAction]:
        """
        决定需要执行的操作

        Args:
            symbol: 币种符号
            offset: 偏移量
            cost_basis: 成本基础
            current_price: 当前价格
            offset_usd: 偏移USD价值

        Returns:
            操作列表
        """
        actions = []

        # 获取当前状态
        state = await self.state_manager.get_symbol_state(symbol)
        monitoring = state.get("monitoring", {})
        is_monitoring = monitoring.get("active", False)
        current_zone = monitoring.get("current_zone")
        existing_order_id = monitoring.get("order_id")
        started_at = monitoring.get("started_at")

        # 计算新区间
        new_zone = self.get_zone(offset_usd)

        logger.debug(f"{symbol}: offset=${offset_usd:.2f}, zone={new_zone}, "
                    f"current_zone={current_zone}, monitoring={is_monitoring}")

        # 决策1: 检查是否超过最高阈值
        if new_zone == -1:
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

        # 决策2: 检查超时
        if is_monitoring and started_at:
            started_time = datetime.fromisoformat(started_at)
            elapsed_minutes = (datetime.now() - started_time).total_seconds() / 60

            if elapsed_minutes >= self.timeout_minutes:
                logger.warning(f"{symbol}: Order timeout after {elapsed_minutes:.1f} minutes")

                # 撤销现有订单
                if existing_order_id:
                    actions.append(TradingAction(
                        type=ActionType.CANCEL_ORDER,
                        symbol=symbol,
                        order_id=existing_order_id,
                        reason=f"Timeout after {elapsed_minutes:.1f} minutes"
                    ))

                # 市价平仓
                order_size = self.calculate_close_size(offset)
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

        # 决策3: 区间变化处理
        if new_zone != current_zone:
            logger.info(f"{symbol}: Zone changed from {current_zone} to {new_zone}")

            # 检查是否在冷却期内
            last_fill_time_str = state.get("last_fill_time")
            in_cooldown = False
            cooldown_remaining = 0

            if last_fill_time_str:
                last_fill_time = datetime.fromisoformat(last_fill_time_str)
                cooldown_elapsed = (datetime.now() - last_fill_time).total_seconds() / 60
                in_cooldown = cooldown_elapsed < self.cooldown_after_fill_minutes
                cooldown_remaining = self.cooldown_after_fill_minutes - cooldown_elapsed

            # 冷却期内的特殊处理
            if in_cooldown:
                logger.info(f"{symbol}: In cooldown period ({cooldown_remaining:.1f}min remaining)")

                # 情况1: 回到阈值内 (Zone → None) - 允许撤单
                if new_zone is None:
                    logger.info(f"{symbol}: Zone → None during cooldown, cancelling order")
                    if is_monitoring and existing_order_id:
                        actions.append(TradingAction(
                            type=ActionType.CANCEL_ORDER,
                            symbol=symbol,
                            order_id=existing_order_id,
                            reason=f"Back within threshold (cooldown: {cooldown_remaining:.1f}min remaining)"
                        ))
                    actions.append(TradingAction(
                        type=ActionType.NO_ACTION,
                        symbol=symbol,
                        reason="Within threshold during cooldown"
                    ))
                    return actions

                # 情况2: Zone恶化 (增大) - 撤单并重新挂单
                elif current_zone is not None and new_zone > current_zone:
                    logger.warning(f"{symbol}: Zone worsened from {current_zone} to {new_zone} during cooldown, re-ordering")

                    # 撤销旧订单
                    if is_monitoring and existing_order_id:
                        actions.append(TradingAction(
                            type=ActionType.CANCEL_ORDER,
                            symbol=symbol,
                            order_id=existing_order_id,
                            reason=f"Zone worsened during cooldown: {current_zone} → {new_zone}"
                        ))

                    # 挂新的限价单
                    order_price = self.calculate_order_price(cost_basis, offset)
                    order_size = self.calculate_close_size(offset)
                    side = "sell" if offset > 0 else "buy"

                    actions.append(TradingAction(
                        type=ActionType.PLACE_LIMIT_ORDER,
                        symbol=symbol,
                        side=side,
                        size=order_size,
                        price=order_price,
                        reason=f"Zone worsened to {new_zone} during cooldown",
                        metadata={
                            "zone": new_zone,
                            "offset": offset,
                            "offset_usd": offset_usd,
                            "cost_basis": cost_basis,
                            "in_cooldown": True
                        }
                    ))
                    return actions

                # 情况3: Zone改善 (减小) - 等待观察，不操作
                elif current_zone is None or new_zone < current_zone:
                    logger.info(f"{symbol}: Zone improved from {current_zone} to {new_zone} during cooldown, waiting...")
                    actions.append(TradingAction(
                        type=ActionType.NO_ACTION,
                        symbol=symbol,
                        reason=f"Zone improved during cooldown, waiting for natural regression (cooldown: {cooldown_remaining:.1f}min remaining)"
                    ))
                    return actions

            # 非冷却期：正常的区间变化处理
            # 撤销旧订单（如果有）
            if is_monitoring and existing_order_id:
                actions.append(TradingAction(
                    type=ActionType.CANCEL_ORDER,
                    symbol=symbol,
                    order_id=existing_order_id,
                    reason=f"Zone changed from {current_zone} to {new_zone}"
                ))

            # 根据新区间决定操作
            if new_zone is None:
                # 回到阈值内，不需要操作
                logger.info(f"{symbol}: Back within threshold, no action needed")
                actions.append(TradingAction(
                    type=ActionType.NO_ACTION,
                    symbol=symbol,
                    reason="Within threshold"
                ))
            else:
                # 进入新区间，挂限价单
                order_price = self.calculate_order_price(cost_basis, offset)
                order_size = self.calculate_close_size(offset)
                side = "sell" if offset > 0 else "buy"

                logger.info(f"{symbol}: Placing {side} order for {order_size:.4f} @ ${order_price:.2f}")

                actions.append(TradingAction(
                    type=ActionType.PLACE_LIMIT_ORDER,
                    symbol=symbol,
                    side=side,
                    size=order_size,
                    price=order_price,
                    reason=f"Entered zone {new_zone}",
                    metadata={
                        "zone": new_zone,
                        "offset": offset,
                        "offset_usd": offset_usd,
                        "cost_basis": cost_basis
                    }
                ))

        # 决策4: 无变化
        if not actions:
            actions.append(TradingAction(
                type=ActionType.NO_ACTION,
                symbol=symbol,
                reason=f"No change needed (zone={new_zone})"
            ))

        return actions

    async def batch_decide(
        self,
        market_data: Dict[str, Dict[str, float]]
    ) -> List[TradingAction]:
        """
        批量决策所有币种

        Args:
            market_data: {
                symbol: {
                    "offset": float,
                    "cost_basis": float,
                    "current_price": float,
                    "offset_usd": float
                }
            }

        Returns:
            所有需要执行的操作列表
        """
        all_actions = []

        for symbol, data in market_data.items():
            try:
                actions = await self.decide(
                    symbol=symbol,
                    offset=data["offset"],
                    cost_basis=data["cost_basis"],
                    current_price=data["current_price"],
                    offset_usd=data["offset_usd"]
                )
                all_actions.extend(actions)
            except Exception as e:
                logger.error(f"Decision error for {symbol}: {e}")
                # 添加错误操作
                all_actions.append(TradingAction(
                    type=ActionType.ALERT,
                    symbol=symbol,
                    reason=f"Decision error: {e}",
                    metadata={"error": str(e)}
                ))

        # 统计操作类型
        action_summary = {}
        for action in all_actions:
            action_summary[action.type.value] = action_summary.get(action.type.value, 0) + 1

        logger.info(f"Decision complete: {action_summary}")

        return all_actions

    def validate_action(self, action: TradingAction) -> bool:
        """
        验证操作是否合法

        Args:
            action: 操作对象

        Returns:
            是否合法
        """
        if action.type in [ActionType.PLACE_LIMIT_ORDER, ActionType.PLACE_MARKET_ORDER]:
            if not action.side or action.side not in ["buy", "sell"]:
                logger.error(f"Invalid side for {action.symbol}: {action.side}")
                return False

            if not action.size or action.size <= 0:
                logger.error(f"Invalid size for {action.symbol}: {action.size}")
                return False

            if action.type == ActionType.PLACE_LIMIT_ORDER and (not action.price or action.price <= 0):
                logger.error(f"Invalid price for {action.symbol}: {action.price}")
                return False

        elif action.type == ActionType.CANCEL_ORDER:
            if not action.order_id:
                logger.error(f"Missing order_id for cancel action on {action.symbol}")
                return False

        return True