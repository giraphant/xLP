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
from datetime import datetime
from utils.config import HedgeConfig
from utils.calculators import calculate_close_size, calculate_limit_price
from .types import ActionType, TradingAction, PreparedData, OrderInfo

logger = logging.getLogger(__name__)


async def decide_actions(
    data: PreparedData,
    config: HedgeConfig
) -> List[TradingAction]:
    """
    批量决策所有币种（纯决策引擎 - 不做任何计算）

    职责：基于 prepare 准备好的数据做决策
    原则：只从 data 获取数据，不做任何计算

    Args:
        data: prepare_data() 准备好的 PreparedData 对象
        config: 配置对象

    Returns:
        List[TradingAction]
    """
    logger.info("=" * 50)
    logger.info("🤔 DECISION MAKING")
    logger.info("=" * 50)

    all_actions = []

    for symbol in data.symbols:
        # 从 prepare 获取所有准备好的数据（纯决策，无计算）
        if symbol not in data.offsets or symbol not in data.zones:
            continue

        # 数据获取（不做计算）
        offset, cost_basis = data.offsets[symbol]
        price = data.prices[symbol]
        zone_info = data.zones[symbol]
        zone = zone_info.zone
        offset_usd = zone_info.offset_usd

        # 获取订单和成交状态
        order_info = data.order_status.get(symbol)
        last_fill_time = data.last_fill_times.get(symbol)
        previous_zone = order_info.previous_zone if order_info else 0

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
            last_fill_time=last_fill_time,
            config=config
        )

        all_actions.extend(actions)

    # 统计操作类型
    action_summary = {}
    for action in all_actions:
        action_summary[action.type.value] = action_summary.get(action.type.value, 0) + 1

    logger.info(f"📋 Decision summary: {action_summary}")

    return all_actions


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
    order_price = calculate_limit_price(offset, cost_basis, config.order_price_offset)
    order_size = calculate_close_size(offset, config.close_ratio)
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


def _decide_symbol_actions_v2(
    symbol: str,
    offset: float,
    cost_basis: float,
    current_price: float,
    offset_usd: float,
    zone: Optional[int],
    previous_zone: int,  # 不再是 Optional，最小值是 0
    order_info: Optional[OrderInfo],
    last_fill_time: Optional[datetime],
    config: Dict[str, Any]
) -> List[TradingAction]:
    """
    优化版决策函数 - 完全无状态

    与v1的区别：
    - 使用从交易所查询的实时订单状态
    - 使用从交易所查询的成交历史
    - previous_zone 从订单信息实时计算，不依赖本地状态

    决策树（按优先级）：
    1. 超阈值 → 警报退出
    2. 超时 → 强制平仓
    3. Zone恶化 → 强制重新下单
    4. 有敞口 → 订单管理（检查冷却期）
    5. 无敞口 → 清理状态
    """
    actions = []

    # 从实时状态获取信息
    has_active_order = order_info.has_order if order_info else False
    oldest_order_time = order_info.oldest_order_time if order_info else None

    # 记录状态转换
    # 注意：zone=None 表示安全区，previous_zone=0 也可能表示安全区（无历史记录）
    # 为了避免混淆，统一将 None 视为 0
    normalized_zone = zone if zone is not None else 0

    if normalized_zone != previous_zone:
        logger.info(f"{symbol}: Zone transition: {previous_zone} → {normalized_zone} (${offset_usd:.2f})")

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
            order_size = calculate_close_size(offset, config.close_ratio)
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

    # ========== 决策3: Zone恶化强制下单（最高优先级，无视冷却期） ==========
    # 只要 zone 恶化（zone > previous_zone），立即强制下单，无视冷却期
    # previous_zone 最小值是 0（从订单/成交/默认计算得出）
    if zone is not None and zone > previous_zone:
        logger.warning(f"{symbol}: 🚨 Zone worsened: {previous_zone} → {zone} (${offset_usd:.2f}) - FORCING ORDER (ignoring cooldown)")

        # 取消旧订单（如果有）
        if has_active_order:
            actions.append(TradingAction(
                type=ActionType.CANCEL_ORDER,
                symbol=symbol,
                reason=f"Zone worsened: {previous_zone} → {zone}"
            ))

        # 立即下新订单（无视冷却期）
        actions.append(_create_limit_order_action(
            symbol, offset, offset_usd, cost_basis, zone,
            f"Emergency order: zone worsened ({previous_zone} → {zone})", config
        ))
        return actions

    # ========== 决策4: 有敞口 - 订单管理 ==========
    if zone is not None:
        # 检查冷却期（使用实时成交时间）
        in_cooldown = False
        cooldown_remaining = 0

        if last_fill_time:
            elapsed = (datetime.now() - last_fill_time).total_seconds() / 60
            in_cooldown = elapsed < config.cooldown_after_fill_minutes
            if in_cooldown:
                cooldown_remaining = config.cooldown_after_fill_minutes - elapsed
                logger.debug(f"{symbol}: In cooldown ({elapsed:.1f}/{config.cooldown_after_fill_minutes} min)")

        # 冷却期：保持现状（避免触发下单）
        if in_cooldown:
            reason = f"In cooldown period ({cooldown_remaining:.1f} min remaining)" if not has_active_order else f"Maintaining order in cooldown (zone: {zone})"
            logger.info(f"{symbol}: 🧊 {reason}")
            return [TradingAction(
                type=ActionType.NO_ACTION,
                symbol=symbol,
                reason=reason,
                metadata={"in_cooldown": True, "zone": zone, "has_order": has_active_order}
            )]

        # 非冷却期：无订单就下单
        if not has_active_order:
            logger.info(f"{symbol}: 📍 Entering zone {zone}, placing order")
            action = _create_limit_order_action(
                symbol, offset, offset_usd, cost_basis, zone,
                f"Entering zone {zone}", config
            )
            logger.info(f"{symbol}: Placing {action.side} order for {action.size:.4f} @ ${action.price:.2f}")
            return [action]

        # 默认：保持订单
        logger.debug(f"{symbol}: Order active in zone {zone}, maintaining")
        return [TradingAction(
            type=ActionType.NO_ACTION,
            symbol=symbol,
            reason=f"Maintaining order in zone {zone}",
            metadata={"zone": zone, "has_order": True}
        )]

    # ========== 决策5: 无敞口 - 清理状态 ==========
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
