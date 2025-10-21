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
    notifier
) -> List[Dict[str, Any]]:
    """
    执行所有操作

    依赖：exchanges/, notifications/

    Args:
        actions: 决策产生的操作列表
        exchange: 交易所接口
        state_manager: 状态管理器
        notifier: 通知器

    Returns:
        执行结果列表 [{"action": TradingAction, "success": bool, ...}, ...]
    """
    if not actions:
        logger.info("No actions to execute")
        return []

    logger.info("=" * 50)
    logger.info("⚡ EXECUTING ACTIONS")
    logger.info("=" * 50)

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
    await state_manager.update_symbol_state(action.symbol, {
        "monitoring": {
            "active": True,
            "current_zone": action.metadata.get("zone"),
            "order_id": order_id,
            "started_at": datetime.now().isoformat()
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

    # 清除监控状态
    await state_manager.update_symbol_state(action.symbol, {
        "monitoring": {
            "active": False,
            "started_at": None,
            "order_id": None
            # current_zone 保留用于 cooldown 判断
        }
    })

    # 更新最后成交时间（用于冷却期）
    await state_manager.update_symbol_state(action.symbol, {
        "last_fill_time": datetime.now().isoformat()
    })

    return order_id


async def _execute_cancel_order(
    action: TradingAction,
    exchange,
    state_manager
) -> bool:
    """
    撤销订单

    Returns:
        是否成功
    """
    logger.info(f"🚫 Canceling order: {action.symbol} (ID: {action.order_id})")

    # 撤单
    success = await exchange.cancel_order(action.order_id)

    if success:
        logger.info(f"✅ Order canceled: {action.symbol} (ID: {action.order_id})")

        # 清除监控状态
        await state_manager.update_symbol_state(action.symbol, {
            "monitoring": {
                "active": False,
                "started_at": None,
                "order_id": None
            }
        })
    else:
        logger.warning(f"⚠️  Failed to cancel order: {action.symbol} (ID: {action.order_id})")

    return success


async def _execute_alert(
    action: TradingAction,
    notifier
):
    """
    发送警报（根据 alert_type 调用对应方法）
    """
    logger.warning(f"🚨 ALERT: {action.symbol} - {action.reason}")

    alert_type = action.metadata.get("alert_type", "warning")

    # 根据 alert_type 调用对应的通知方法
    if alert_type == "threshold_exceeded":
        await notifier.alert_threshold_exceeded(
            action.symbol,
            action.metadata["offset_usd"],
            action.metadata["offset"],
            action.metadata["current_price"]
        )
    else:
        # 通用警告
        await notifier.alert_warning(action.symbol, action.reason)
