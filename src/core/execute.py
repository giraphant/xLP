"""
执行模块

职责：执行决策产生的所有操作

包含：
- 限价单执行
- 市价单执行
- 撤单
- 警报
- 状态更新
"""
import logging
from typing import List, Dict, Any
from datetime import datetime
from .decide import TradingAction, ActionType

logger = logging.getLogger(__name__)


async def execute_actions(
    actions: List[TradingAction],
    exchange,
    state_manager,
    notifier,
    state_updates: Dict[str, Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    执行所有操作

    依赖：exchanges/, notifications/

    Args:
        actions: 决策产生的操作列表
        exchange: 交易所接口
        state_manager: 状态管理器
        notifier: 通知器
        state_updates: prepare阶段计算的状态更新（统一在此更新）

    Returns:
        执行结果列表 [{"action": TradingAction, "success": bool, ...}, ...]
    """
    logger.info("=" * 50)
    logger.info("⚡ EXECUTING ACTIONS")
    logger.info("=" * 50)

    # 第一步：更新所有 prepare 阶段计算的状态（统一在此处更新）
    if state_updates:
        logger.info("📝 Updating states from prepare phase:")
        for symbol, updates in state_updates.items():
            # 构建要更新的状态
            symbol_state_update = {}

            # 更新 offset 和 cost_basis
            if "offset" in updates:
                symbol_state_update["offset"] = updates["offset"]
            if "cost_basis" in updates:
                symbol_state_update["cost_basis"] = updates["cost_basis"]

            # 更新 exchange_position
            if "exchange_position" in updates:
                symbol_state_update["exchange_position"] = updates["exchange_position"]

            # 应用状态更新
            if symbol_state_update:
                state_manager.update_symbol_state(symbol, symbol_state_update)
                logger.debug(f"  • {symbol}: {symbol_state_update}")

            # 如果检测到持仓变化（成交），更新 last_fill_time
            if updates.get("position_changed"):
                state_manager.update_symbol_state(symbol, {
                    "last_fill_time": datetime.now()
                })
                logger.info(f"  🔔 {symbol}: Fill detected, updated last_fill_time")

    if not actions:
        logger.info("No actions to execute")
        return []

    results = []

    for action in actions:
        try:
            result = {"action": action, "success": False}

            # 执行限价单
            if action.type == ActionType.PLACE_LIMIT_ORDER:
                order_id = await _execute_limit_order(
                    action, exchange, state_manager
                )
                result["success"] = True
                result["order_id"] = order_id

            # 执行市价单
            elif action.type == ActionType.PLACE_MARKET_ORDER:
                order_id = await _execute_market_order(
                    action, exchange, state_manager, notifier
                )
                result["success"] = True
                result["order_id"] = order_id

            # 撤销订单
            elif action.type == ActionType.CANCEL_ORDER:
                success = await _execute_cancel_order(
                    action, exchange, state_manager
                )
                result["success"] = success

            # 发送警报
            elif action.type == ActionType.ALERT:
                await _execute_alert(action, notifier)
                result["success"] = True

            # 无操作
            elif action.type == ActionType.NO_ACTION:
                logger.debug(f"⏭️  No action: {action.symbol} - {action.reason}")
                result["success"] = True

            results.append(result)

        except Exception as e:
            logger.error(f"Failed to execute {action.type.value} for {action.symbol}: {e}")
            results.append({"action": action, "success": False, "error": str(e)})

    # 统计执行结果
    success_count = sum(1 for r in results if r["success"])
    logger.info(f"✅ Executed {success_count}/{len(results)} actions successfully")

    return results


async def _execute_limit_order(
    action: TradingAction,
    exchange,
    state_manager
) -> str:
    """
    执行限价单

    Returns:
        order_id
    """
    logger.info(f"📤 Placing limit order: {action.symbol} {action.side} "
               f"{action.size:.4f} @ ${action.price:.2f}")

    # 下单
    order_id = await exchange.place_limit_order(
        action.symbol,
        action.side,
        action.size,
        action.price
    )

    logger.info(f"✅ Limit order placed: {action.symbol} (ID: {order_id})")

    # 更新状态
    state_manager.update_symbol_state(action.symbol, {
        "monitoring": {
            "current_zone": action.metadata.get("zone"),
            "started_at": datetime.now()
        }
    })

    return order_id


async def _execute_market_order(
    action: TradingAction,
    exchange,
    state_manager,
    notifier
) -> str:
    """
    执行市价单

    Returns:
        order_id
    """
    logger.info(f"📤 Placing market order: {action.symbol} {action.side} "
               f"{action.size:.4f}")

    # 下单
    order_id = await exchange.place_market_order(
        action.symbol,
        action.side,
        action.size
    )

    logger.info(f"✅ Market order placed: {action.symbol} (ID: {order_id})")

    # 如果是强制平仓，发送通知
    if action.metadata.get("force_close"):
        await notifier.alert_force_close(
            action.symbol,
            action.size,
            action.side
        )

    # 清除监控状态 + 更新最后成交时间（用于冷却期）
    state_manager.update_symbol_state(action.symbol, {
        "monitoring": {
            "started_at": None
            # current_zone 保留用于 cooldown 判断
        },
        "last_fill_time": datetime.now()
    })

    return order_id


async def _execute_cancel_order(
    action: TradingAction,
    exchange,
    state_manager
) -> bool:
    """
    撤销订单（取消该币种所有活跃订单）

    Returns:
        是否成功
    """
    logger.info(f"🚫 Canceling all orders: {action.symbol}")

    # 取消该币种的所有订单
    canceled_count = await exchange.cancel_all_orders(action.symbol)

    if canceled_count > 0:
        logger.info(f"✅ Canceled {canceled_count} order(s): {action.symbol}")

        # 清除监控状态（保留 current_zone 用于下一轮 zone 对比）
        state_manager.update_symbol_state(action.symbol, {
            "monitoring": {
                "started_at": None
                # current_zone 保留，用于判断下一轮 zone 是否变化
            }
        })
        return True
    else:
        logger.warning(f"⚠️  No orders to cancel: {action.symbol}")
        return False


async def _execute_alert(
    action: TradingAction,
    notifier
):
    """
    发送警报：超过最高阈值
    """
    logger.warning(f"🚨 ALERT: {action.symbol} - {action.reason}")

    # 当前只有一种警报：超过最高阈值
    await notifier.alert_threshold_exceeded(
        action.symbol,
        action.metadata["offset_usd"],
        action.metadata["offset"],
        action.metadata["current_price"]
    )
