"""
执行模块

职责：执行决策产生的所有操作

包含：
- 限价单执行
- 市价单执行
- 撤单
- 警报
"""
import logging
from typing import List, Dict, Any
from .types import TradingAction, ActionType

logger = logging.getLogger(__name__)


# ========== DRY RUN 辅助函数 ==========

def _should_execute_real_trade(config) -> bool:
    """检查是否应该真实执行交易（非 dry run 模式）"""
    return not config.dry_run


def _log_dry_run_action(action_desc: str):
    """统一的 dry run 日志输出"""
    logger.info(f"🔍 [DRY RUN] {action_desc}")


async def execute_actions(
    actions: List[TradingAction],
    exchange,
    notifier,
    config
) -> List[Dict[str, Any]]:
    """
    执行所有操作（完全无状态）

    依赖：exchanges/, notifications/

    Args:
        actions: 决策产生的操作列表
        exchange: 交易所接口
        notifier: 通知器
        config: 配置对象（检查 dry_run 模式）

    Returns:
        执行结果列表 [{"action": TradingAction, "success": bool, ...}, ...]
    """
    logger.info("=" * 50)
    logger.info("⚡ EXECUTING ACTIONS")
    if not _should_execute_real_trade(config):
        logger.warning("⚠️  DRY RUN MODE - No real trades will be executed")
    logger.info("=" * 50)

    if not actions:
        logger.info("No actions to execute")
        return []

    results = []

    for action in actions:
        try:
            result = {"action": action, "success": False}

            # 执行限价单
            if action.type == ActionType.PLACE_LIMIT_ORDER:
                if _should_execute_real_trade(config):
                    order_id = await _execute_limit_order(action, exchange)
                    result["order_id"] = order_id
                else:
                    _log_dry_run_action(
                        f"Place limit order: {action.symbol} {action.side} "
                        f"{action.size:.4f} @ ${action.price:.2f}"
                    )
                    result["order_id"] = "DRY_RUN"
                result["success"] = True

            # 执行市价单
            elif action.type == ActionType.PLACE_MARKET_ORDER:
                if _should_execute_real_trade(config):
                    order_id = await _execute_market_order(action, exchange, notifier)
                    result["order_id"] = order_id
                else:
                    _log_dry_run_action(
                        f"Place market order: {action.symbol} {action.side} "
                        f"{action.size:.4f}"
                    )
                    result["order_id"] = "DRY_RUN"
                result["success"] = True

            # 撤销订单
            elif action.type == ActionType.CANCEL_ORDER:
                if _should_execute_real_trade(config):
                    success = await _execute_cancel_order(action, exchange)
                    result["success"] = success
                else:
                    _log_dry_run_action(f"Cancel all orders: {action.symbol}")
                    result["success"] = True

            # 发送警报
            elif action.type == ActionType.ALERT:
                # 警报始终发送（即使在 dry run 模式）
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
    if not _should_execute_real_trade(config):
        logger.warning("⚠️  DRY RUN MODE - No trades were executed")

    return results


async def _execute_limit_order(
    action: TradingAction,
    exchange
) -> str:
    """
    执行限价单（无状态）

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

    return order_id


async def _execute_market_order(
    action: TradingAction,
    exchange,
    notifier
) -> str:
    """
    执行市价单（无状态）

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

    return order_id


async def _execute_cancel_order(
    action: TradingAction,
    exchange
) -> bool:
    """
    撤销订单（无状态）

    Returns:
        是否成功
    """
    logger.info(f"🚫 Canceling all orders: {action.symbol}")

    # 取消该币种的所有订单
    canceled_count = await exchange.cancel_all_orders(action.symbol)

    if canceled_count > 0:
        logger.info(f"✅ Canceled {canceled_count} order(s): {action.symbol}")
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
