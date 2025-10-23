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
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from utils.config import HedgeConfig

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
    reason: str = ""
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


async def decide_actions(
    data: Dict[str, Any],
    state_manager,
    config: HedgeConfig
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
            config.threshold_min_usd,
            config.threshold_max_usd,
            config.threshold_step_usd
        )

        # 获取状态
        state = state_manager.get_symbol_state(symbol)

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


def _create_limit_order_action(
    symbol: str,
    offset: float,
    offset_usd: float,
    cost_basis: float,
    zone: int,
    reason: str,
    config: HedgeConfig,
    in_cooldown: bool = False
) -> TradingAction:
    """创建限价单操作（辅助函数，消除重复）"""
    order_price = _calculate_limit_price(offset, cost_basis, config.order_price_offset)
    order_size = _calculate_close_size(offset, config.close_ratio)
    side = "sell" if offset > 0 else "buy"

    return TradingAction(
        type=ActionType.PLACE_LIMIT_ORDER,
        symbol=symbol,
        side=side,
        size=order_size,
        price=order_price,
        reason=reason,
        metadata={
            "zone": zone,
            "offset": offset,
            "offset_usd": offset_usd,
            "cost_basis": cost_basis,
            "in_cooldown": in_cooldown
        }
    )


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
    优化后的决策函数 - 更清晰的状态机

    状态机：
    1. 超阈值 → 警报退出
    2. 超时 → 强制平仓
    3. 有敞口(zone is not None) → 订单管理
    4. 无敞口(zone is None) → 清理状态
    """
    actions = []

    # 获取状态信息
    monitoring = state.get("monitoring", {})
    current_zone = monitoring.get("current_zone")
    started_at = monitoring.get("started_at")
    has_active_order = started_at is not None

    # 记录状态转换
    if zone != current_zone:
        logger.info(f"{symbol}: Zone transition: {current_zone} → {zone} (${offset_usd:.2f})")

    # ========== 决策1: 超阈值检查 ==========
    if zone == -1:
        logger.warning(f"{symbol}: ⚠️ Exceeded max threshold ${offset_usd:.2f}")

        if has_active_order:
            actions.append(TradingAction(
                type=ActionType.CANCEL_ORDER,
                symbol=symbol,
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

    # ========== 决策2: 超时检查 ==========
    if has_active_order:
        elapsed_minutes = (datetime.now() - started_at).total_seconds() / 60
        if elapsed_minutes >= config.timeout_minutes:
            logger.warning(f"{symbol}: ⏰ Order timeout after {elapsed_minutes:.1f} minutes")

            # 取消订单
            actions.append(TradingAction(
                type=ActionType.CANCEL_ORDER,
                symbol=symbol,
                reason=f"Timeout after {elapsed_minutes:.1f} minutes"
            ))

            # 市价平仓
            order_size = _calculate_close_size(offset, config.close_ratio)
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

    # ========== 决策3: 有敞口 - 管理订单 ==========
    if zone is not None:
        # 检查冷却期（简化版）
        last_fill_time = state.get("last_fill_time")
        in_cooldown = False
        cooldown_remaining = 0

        if last_fill_time:
            elapsed = (datetime.now() - last_fill_time).total_seconds() / 60
            in_cooldown = elapsed < config.cooldown_after_fill_minutes
            if in_cooldown:
                cooldown_remaining = config.cooldown_after_fill_minutes - elapsed
                logger.debug(f"{symbol}: In cooldown ({elapsed:.1f}/{config.cooldown_after_fill_minutes} min)")

        # 冷却期逻辑
        if in_cooldown:
            if not has_active_order:
                # 刚成交，等待冷却
                logger.info(f"{symbol}: 🧊 Cooling down after fill ({cooldown_remaining:.1f} min remaining)")
                return [TradingAction(
                    type=ActionType.NO_ACTION,
                    symbol=symbol,
                    reason=f"Waiting in cooldown period ({cooldown_remaining:.1f} min remaining)",
                    metadata={"in_cooldown": True, "cooldown_remaining": cooldown_remaining}
                )]

            # 有订单，检查是否需要调整
            if current_zone is not None and zone > current_zone:
                # Zone恶化，需要重新挂单
                logger.info(f"{symbol}: 📈 Zone worsened during cooldown: {current_zone} → {zone}")
                actions.append(TradingAction(
                    type=ActionType.CANCEL_ORDER,
                    symbol=symbol,
                    reason=f"Zone worsened: {current_zone} → {zone}"
                ))
                actions.append(_create_limit_order_action(
                    symbol, offset, offset_usd, cost_basis, zone,
                    f"Re-order due to zone worsening during cooldown", config,
                    in_cooldown=True
                ))
                return actions
            else:
                # Zone改善或不变，保持现状
                logger.debug(f"{symbol}: Maintaining order during cooldown (zone: {zone})")
                return [TradingAction(
                    type=ActionType.NO_ACTION,
                    symbol=symbol,
                    reason=f"Maintaining order in cooldown (zone: {zone})",
                    metadata={"in_cooldown": True, "zone": zone}
                )]

        # 非冷却期逻辑
        else:
            if not has_active_order:
                # 需要挂新单
                logger.info(f"{symbol}: 📍 Entering zone {zone}, placing order")
                action = _create_limit_order_action(
                    symbol, offset, offset_usd, cost_basis, zone,
                    f"Entering zone {zone}", config
                )
                logger.info(f"{symbol}: Placing {action.side} order for {action.size:.4f} @ ${action.price:.2f}")
                return [action]
            else:
                # 这种情况理论上不该出现（非冷却期+有订单）
                logger.error(f"{symbol}: ❌ Unexpected state: not in cooldown but has order")
                actions.append(TradingAction(
                    type=ActionType.CANCEL_ORDER,
                    symbol=symbol,
                    reason="Unexpected state cleanup"
                ))
                actions.append(_create_limit_order_action(
                    symbol, offset, offset_usd, cost_basis, zone,
                    f"Recovery from unexpected state", config
                ))
                return actions

    # ========== 决策4: 无敞口 - 清理状态 ==========
    if zone is None:
        if has_active_order:
            # 回到安全区，取消订单
            logger.info(f"{symbol}: ✅ Back to safe zone, canceling order")
            return [TradingAction(
                type=ActionType.CANCEL_ORDER,
                symbol=symbol,
                reason="Back within threshold"
            )]
        else:
            # 本来就在安全区
            logger.debug(f"{symbol}: Within threshold, no action needed")
            return [TradingAction(
                type=ActionType.NO_ACTION,
                symbol=symbol,
                reason="Within threshold"
            )]

    # 不应该到达这里
    logger.error(f"{symbol}: Reached unexpected end of decision tree")
    return [TradingAction(
        type=ActionType.NO_ACTION,
        symbol=symbol,
        reason="Unexpected decision tree end"
    )]


# _check_cooldown 函数已被移除 - 冷却期逻辑已内联到 _decide_symbol_actions 中
