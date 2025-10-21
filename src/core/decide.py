"""
决策模块

职责：根据准备好的数据，决定每个币种需要执行的操作

包含：
- 超阈值检测
- 超时检测
- 冷却期逻辑（内部函数）
- 区间变化处理
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

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


async def decide_actions(
    data: Dict[str, Any],
    state_manager,
    config: Dict[str, Any]
) -> List[TradingAction]:
    """
    批量决策所有币种

    Args:
        data: prepare_data() 的返回值
            {
                "symbols": [...],
                "prices": {...},
                "offsets": {symbol: (offset, cost_basis)}
            }
        state_manager: 状态管理器
        config: 配置字典

    Returns:
        List[TradingAction]
    """
    logger.info("=" * 50)
    logger.info("🤔 DECISION MAKING")
    logger.info("=" * 50)

    all_actions = []

    for symbol in data["symbols"]:
        if symbol not in data["offsets"] or symbol not in data["prices"]:
            continue

        offset, cost_basis = data["offsets"][symbol]
        price = data["prices"][symbol]
        offset_usd = abs(offset) * price

        # 计算区间
        zone = _calculate_zone(
            offset_usd,
            config["threshold_min_usd"],
            config["threshold_max_usd"],
            config["threshold_step_usd"]
        )

        # 获取状态
        state = await state_manager.get_symbol_state(symbol)

        # 调用核心决策函数
        actions = _decide_symbol_actions(
            symbol, offset, cost_basis, price, offset_usd, zone, state, config
        )

        all_actions.extend(actions)

    # 统计操作类型
    action_summary = {}
    for action in all_actions:
        action_summary[action.type.value] = action_summary.get(action.type.value, 0) + 1

    logger.info(f"📋 Decision summary: {action_summary}")

    return all_actions


def _calculate_zone(
    offset_usd: float,
    min_threshold: float,
    max_threshold: float,
    step: float
) -> Optional[int]:
    """
    根据偏移USD绝对值计算所在区间（纯函数）

    Returns:
        None: 低于最低阈值
        0-N: 区间编号
        -1: 超过最高阈值（警报）
    """
    abs_usd = abs(offset_usd)

    if abs_usd < min_threshold:
        return None

    if abs_usd > max_threshold:
        return -1

    zone = int((abs_usd - min_threshold) / step)
    return zone


def _calculate_close_size(offset: float, close_ratio: float) -> float:
    """计算平仓数量（纯函数）"""
    return abs(offset) * (close_ratio / 100.0)


def _calculate_limit_price(offset: float, cost_basis: float, price_offset_percent: float) -> float:
    """计算限价单价格（纯函数）"""
    if offset > 0:
        # 多头敞口：需要卖出平仓，挂高价
        return cost_basis * (1 + price_offset_percent / 100)
    else:
        # 空头敞口：需要买入平仓，挂低价
        return cost_basis * (1 - price_offset_percent / 100)


def _decide_symbol_actions(
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
    单个币种的核心决策函数

    包含完整的决策状态机
    """
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

        if existing_order_id:
            actions.append(TradingAction(
                type=ActionType.CANCEL_ORDER,
                symbol=symbol,
                order_id=existing_order_id,
                reason="Exceeded max threshold"
            ))

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

            if existing_order_id:
                actions.append(TradingAction(
                    type=ActionType.CANCEL_ORDER,
                    symbol=symbol,
                    order_id=existing_order_id,
                    reason=f"Timeout after {elapsed_minutes:.1f} minutes"
                ))

            # 市价平仓（100%）
            order_size = _calculate_close_size(offset, 100.0)
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
        in_cooldown, cooldown_status = _check_cooldown(state, current_zone, zone, config)

        if in_cooldown:
            logger.info(f"{symbol}: In cooldown - {cooldown_status}")

            # 情况1: 回到阈值内 (Zone → None)
            if cooldown_status == "cancel_only":
                if existing_order_id:
                    actions.append(TradingAction(
                        type=ActionType.CANCEL_ORDER,
                        symbol=symbol,
                        order_id=existing_order_id,
                        reason="Back within threshold during cooldown"
                    ))
                actions.append(TradingAction(
                    type=ActionType.NO_ACTION,
                    symbol=symbol,
                    reason="Within threshold during cooldown"
                ))
                return actions

            # 情况2: Zone恶化 (增大)
            elif cooldown_status == "re_order":
                if existing_order_id:
                    actions.append(TradingAction(
                        type=ActionType.CANCEL_ORDER,
                        symbol=symbol,
                        order_id=existing_order_id,
                        reason=f"Zone worsened during cooldown: {current_zone} → {zone}"
                    ))

                # 挂新的限价单
                order_price = _calculate_limit_price(offset, cost_basis, config.get("order_price_offset", 0.2))
                order_size = _calculate_close_size(offset, config.get("close_ratio", 40.0))
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

            # 情况3: Zone改善 (减小) - 等待观察
            elif cooldown_status == "skip":
                actions.append(TradingAction(
                    type=ActionType.NO_ACTION,
                    symbol=symbol,
                    reason=f"Zone improved during cooldown, waiting for natural regression"
                ))
                return actions

        # 非冷却期：正常的区间变化处理
        if is_monitoring and existing_order_id:
            actions.append(TradingAction(
                type=ActionType.CANCEL_ORDER,
                symbol=symbol,
                order_id=existing_order_id,
                reason=f"Zone changed from {current_zone} to {zone}"
            ))

        # 根据新区间决定操作
        if zone is None:
            logger.info(f"{symbol}: Back within threshold, no action needed")
            actions.append(TradingAction(
                type=ActionType.NO_ACTION,
                symbol=symbol,
                reason="Within threshold"
            ))
        else:
            # 进入新区间，挂限价单
            order_price = _calculate_limit_price(offset, cost_basis, config.get("order_price_offset", 0.2))
            order_size = _calculate_close_size(offset, config.get("close_ratio", 40.0))
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


def _check_cooldown(
    state: Dict[str, Any],
    current_zone: Optional[int],
    new_zone: Optional[int],
    config: Dict[str, Any]
) -> Tuple[bool, str]:
    """
    检查冷却期并分析状态（内部函数）

    Returns:
        (in_cooldown, status)
        - in_cooldown: 是否在冷却期
        - status: "normal" | "skip" | "cancel_only" | "re_order"
    """
    last_fill_time_str = state.get("last_fill_time")
    if not last_fill_time_str:
        return False, "normal"

    last_fill_time = datetime.fromisoformat(last_fill_time_str)
    elapsed = (datetime.now() - last_fill_time).total_seconds() / 60
    cooldown_minutes = config.get("cooldown_after_fill_minutes", 5)

    if elapsed >= cooldown_minutes:
        return False, "normal"

    # 在冷却期内，分析状态
    remaining = cooldown_minutes - elapsed

    # 回到阈值内
    if new_zone is None:
        return True, "cancel_only"

    # Zone恶化（增大）
    if current_zone is not None and new_zone is not None and new_zone > current_zone:
        return True, "re_order"

    # Zone改善（减小）
    if current_zone is not None and new_zone is not None and new_zone < current_zone:
        return True, "skip"

    return True, "normal"
