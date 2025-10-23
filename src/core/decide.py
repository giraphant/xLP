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
    config: HedgeConfig
) -> List[TradingAction]:
    """
    批量决策所有币种（纯决策引擎 - 不做任何计算）

    职责：基于 prepare 准备好的数据做决策
    原则：只从 data 获取数据，不做任何计算

    Args:
        data: prepare_data() 准备好的所有数据
            {
                "symbols": [...],
                "prices": {...},
                "offsets": {symbol: (offset, cost_basis)},
                "zones": {symbol: {"zone": x, "offset_usd": y}},  # prepare 计算好
                "order_status": {symbol: {"previous_zone": x, ...}},  # prepare 计算好
                "fill_history": {symbol: {"latest_fill_time": ...}}
            }
        config: 配置对象

    Returns:
        List[TradingAction]
    """
    logger.info("=" * 50)
    logger.info("🤔 DECISION MAKING")
    logger.info("=" * 50)

    all_actions = []

    for symbol in data["symbols"]:
        # 从 prepare 获取所有准备好的数据（纯决策，无计算）
        if symbol not in data["offsets"] or symbol not in data["zones"]:
            continue

        # 数据获取（不做计算）
        offset, cost_basis = data["offsets"][symbol]
        price = data["prices"][symbol]
        zone_info = data["zones"][symbol]
        zone = zone_info["zone"]
        offset_usd = zone_info["offset_usd"]

        # 获取订单和成交状态
        order_info = data.get("order_status", {}).get(symbol, {})
        fill_info = data.get("fill_history", {}).get(symbol, {})
        previous_zone = order_info.get("previous_zone")

        # 调用核心决策函数（纯决策逻辑）
        actions = _decide_symbol_actions_v2(
            symbol=symbol,
            offset=offset,
            cost_basis=cost_basis,
            current_price=price,
            offset_usd=offset_usd,
            zone=zone,
            previous_zone=previous_zone,
            order_info=order_info,
            fill_info=fill_info,
            config=config
        )

        all_actions.extend(actions)

    # 统计操作类型
    action_summary = {}
    for action in all_actions:
        action_summary[action.type.value] = action_summary.get(action.type.value, 0) + 1

    logger.info(f"📋 Decision summary: {action_summary}")

    return all_actions


def calculate_zone(
    offset_usd: float,
    min_threshold: float,
    max_threshold: float,
    step: float
) -> Optional[int]:
    """
    根据偏移USD绝对值计算所在区间（纯函数 - 供 prepare 调用）

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


def _calculate_zone_from_orders(
    orders: List[Dict],
    current_price: float,
    threshold_min: float,
    threshold_step: float
) -> Optional[int]:
    """
    从订单信息反推上次下单时的 zone（无状态）

    算法：(订单价值 - threshold_min) / threshold_step

    Args:
        orders: 订单列表 [{"size": x, "price": y}, ...]
        current_price: 当前价格（用于fallback）
        threshold_min: 最小阈值
        threshold_step: 阈值步长

    Returns:
        zone (int) 或 None（无订单）
    """
    if not orders:
        return None

    # 取第一个订单（假设同一symbol的订单zone相同）
    order = orders[0]
    order_size = abs(order.get("size", 0))
    order_price = order.get("price", current_price)

    # 计算订单价值（USD）
    order_value_usd = order_size * order_price

    # 反推 zone
    zone = int((order_value_usd - threshold_min) / threshold_step)

    return max(zone, 1)  # zone 至少为 1


def _decide_symbol_actions_v2(
    symbol: str,
    offset: float,
    cost_basis: float,
    current_price: float,
    offset_usd: float,
    zone: Optional[int],
    previous_zone: Optional[int],
    order_info: Dict[str, Any],
    fill_info: Dict[str, Any],
    config: Dict[str, Any]
) -> List[TradingAction]:
    """
    优化版决策函数 - 完全无状态

    与v1的区别：
    - 使用从交易所查询的实时订单状态
    - 使用从交易所查询的成交历史
    - previous_zone 从订单信息实时计算，不依赖本地状态

    状态机：
    1. 超阈值 → 警报退出
    2. 超时 → 强制平仓
    3. 有敞口(zone is not None) → 订单管理
    4. 无敞口(zone is None) → 清理状态
    """
    actions = []

    # 从实时状态获取信息
    has_active_order = order_info.get("has_order", False)
    oldest_order_time = order_info.get("oldest_order_time")
    latest_fill_time = fill_info.get("latest_fill_time")

    # 记录状态转换
    if zone != previous_zone:
        logger.info(f"{symbol}: Zone transition: {previous_zone} → {zone} (${offset_usd:.2f})")

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
    if has_active_order and oldest_order_time:
        elapsed_minutes = (datetime.now() - oldest_order_time).total_seconds() / 60
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
        # 检查冷却期（使用实时成交时间）
        in_cooldown = False
        cooldown_remaining = 0

        if latest_fill_time:
            elapsed = (datetime.now() - latest_fill_time).total_seconds() / 60
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
                # 非冷却期+有订单：正常状态，订单继续挂着
                logger.debug(f"{symbol}: Order active in zone {zone}, maintaining")
                return [TradingAction(
                    type=ActionType.NO_ACTION,
                    symbol=symbol,
                    reason=f"Maintaining order in zone {zone}",
                    metadata={"zone": zone, "has_order": True}
                )]

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
