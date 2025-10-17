#!/usr/bin/env python3
"""
报告生成模块 - 独立的日志和报告系统
与主引擎完全分离，通过 middleware 注入
"""

import logging
from datetime import datetime
from typing import Callable, Awaitable

from core.pipeline import PipelineContext

logger = logging.getLogger(__name__)


async def generate_position_report(context: PipelineContext, state_manager=None):
    """
    生成详细的持仓报告

    Args:
        context: Pipeline context with offsets, prices, actions
        state_manager: State manager for monitoring info (optional)
    """
    if not context.offsets or not context.prices:
        return

    logger.info("")
    logger.info("=" * 70)
    logger.info("📊 DETAILED POSITION REPORT")
    logger.info("=" * 70)

    total_exposure = 0
    total_pnl = 0

    for symbol, (offset, cost_basis) in context.offsets.items():
        if symbol not in context.prices:
            continue

        current_price = context.prices[symbol]
        offset_usd = abs(offset) * current_price
        total_exposure += offset_usd

        # 基本信息
        logger.info(f"")
        logger.info(f"【{symbol}】")

        # 持仓方向
        if offset > 0:
            status = "🔴 LONG"
            direction = "需要卖出平仓"
        elif offset < 0:
            status = "🟢 SHORT"
            direction = "需要买入平仓"
        else:
            status = "✅ BALANCED"
            direction = "无需操作"

        logger.info(f"  状态: {status} {direction}")
        logger.info(f"  偏移: {offset:+.6f} {symbol} (${offset_usd:.2f})")
        logger.info(f"  当前价格: ${current_price:.2f}")

        # 成本和盈亏
        if cost_basis > 0 and offset != 0:
            logger.info(f"  平均成本: ${cost_basis:.2f}")

            pnl = (current_price - cost_basis) * abs(offset)
            pnl_percent = ((current_price - cost_basis) / cost_basis) * 100
            total_pnl += pnl

            pnl_icon = "💚" if pnl > 0 else "❤️" if pnl < 0 else "💛"
            logger.info(f"  浮动盈亏: {pnl_icon} ${pnl:+.2f} ({pnl_percent:+.2f}%)")

        # 监控状态（如果有 state_manager）
        if state_manager:
            try:
                symbol_state = await state_manager.get_symbol_state(symbol)
                monitoring = symbol_state.get("monitoring", {})

                if monitoring.get("active"):
                    zone = monitoring.get("current_zone", "N/A")
                    order_id = monitoring.get("order_id", "N/A")
                    started_at = monitoring.get("started_at")

                    if started_at:
                        start_time = datetime.fromisoformat(started_at)
                        elapsed_min = (datetime.now() - start_time).total_seconds() / 60
                        logger.info(f"  📍 监控中: Zone {zone} | 订单 {order_id} | {elapsed_min:.1f}分钟")
                    else:
                        logger.info(f"  📍 监控中: Zone {zone} | 订单 {order_id}")
            except Exception as e:
                logger.debug(f"Failed to get monitoring state for {symbol}: {e}")

        # 决策信息（如果有 actions）
        if hasattr(context, 'actions') and context.actions:
            action = next((a for a in context.actions if a.symbol == symbol), None)
            if action:
                action_map = {
                    "place_limit_order": f"📝 下限价单: {action.side.upper()} {action.size:.6f} @ ${action.price:.2f}",
                    "place_market_order": f"⚡ 下市价单: {action.side.upper()} {action.size:.6f}",
                    "cancel_order": f"🚫 撤单: {action.order_id}",
                    "no_action": "⏸️  无操作",
                    "alert": f"⚠️  警报"
                }

                action_desc = action_map.get(action.type.value, "未知操作")
                logger.info(f"  决策: {action_desc}")

                if action.reason:
                    logger.info(f"  原因: {action.reason}")

    # 总计
    logger.info("")
    logger.info(f"📊 总计:")
    logger.info(f"  总敞口: ${total_exposure:.2f}")
    if total_pnl != 0:
        pnl_icon = "💚" if total_pnl > 0 else "❤️"
        logger.info(f"  总盈亏: {pnl_icon} ${total_pnl:+.2f}")

    logger.info("=" * 70)
