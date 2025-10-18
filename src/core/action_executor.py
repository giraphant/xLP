#!/usr/bin/env python3
"""
操作执行器 - 执行决策引擎产生的交易操作
"""

import logging
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, field

from core.decision_engine import TradingAction, ActionType
from core.exceptions import OrderPlacementError, OrderCancellationError

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """执行结果"""
    action: TradingAction
    success: bool
    result: Any = None
    error: Optional[Exception] = None
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ActionExecutor:
    """
    操作执行器

    负责执行决策引擎产生的各种操作，包括：
    - 下单（限价/市价）
    - 撤单
    - 发送通知
    - 更新状态
    """

    def __init__(
        self,
        exchange,
        state_manager,
        notifier,
        metrics_collector,
        circuit_manager
    ):
        """
        Args:
            exchange: 交易所接口
            state_manager: 状态管理器
            notifier: 通知器
            metrics_collector: 指标收集器
            circuit_manager: 熔断器管理器
        """
        self.exchange = exchange
        self.state_manager = state_manager
        self.notifier = notifier
        self.metrics = metrics_collector
        self.circuit_manager = circuit_manager

        # 执行统计
        self.execution_stats = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "by_type": {}
        }

    async def execute(self, action: TradingAction) -> ExecutionResult:
        """
        执行单个操作

        Args:
            action: 操作对象

        Returns:
            执行结果
        """
        logger.debug(f"Executing action: {action.type.value} for {action.symbol}")

        try:
            # 根据操作类型分发
            if action.type == ActionType.PLACE_LIMIT_ORDER:
                result = await self._execute_limit_order(action)

            elif action.type == ActionType.PLACE_MARKET_ORDER:
                result = await self._execute_market_order(action)

            elif action.type == ActionType.CANCEL_ORDER:
                result = await self._execute_cancel_order(action)

            elif action.type == ActionType.ALERT:
                result = await self._execute_alert(action)

            elif action.type == ActionType.NO_ACTION:
                result = ExecutionResult(
                    action=action,
                    success=True,
                    result="No action needed"
                )

            else:
                raise ValueError(f"Unknown action type: {action.type}")

            # 更新统计
            self._update_stats(action.type, result.success)

            return result

        except Exception as e:
            logger.error(f"Failed to execute {action.type.value} for {action.symbol}: {e}")
            self._update_stats(action.type, False)

            return ExecutionResult(
                action=action,
                success=False,
                error=e
            )

    async def _execute_limit_order(self, action: TradingAction) -> ExecutionResult:
        """执行限价单"""
        try:
            # 通过熔断器执行
            breaker = await self.circuit_manager.get_or_create(
                f"exchange_{action.symbol}",
                failure_threshold=3,
                timeout=30
            )

            order_id = await breaker.call(
                self.exchange.place_limit_order,
                action.symbol,
                action.side,
                action.size,
                action.price
            )

            logger.info(f"Limit order placed: {action.symbol} {action.side} "
                       f"{action.size:.4f} @ ${action.price:.2f} (ID: {order_id})")

            # 更新状态
            await self.state_manager.update_symbol_state(action.symbol, {
                "monitoring": {
                    "active": True,
                    "current_zone": action.metadata.get("zone"),
                    "order_id": order_id,
                    "started_at": datetime.now().isoformat()
                }
            })

            # 记录指标
            await self.metrics.record_order(
                action.symbol,
                action.side,
                action.size,
                action.price,
                "limit",
                True
            )

            # 增加统计
            await self.state_manager.increment_counter(
                action.symbol, "stats.total_orders"
            )

            return ExecutionResult(
                action=action,
                success=True,
                result=order_id,
                metadata={"order_id": order_id}
            )

        except Exception as e:
            logger.error(f"Failed to place limit order: {e}")

            # 记录失败指标
            await self.metrics.record_order(
                action.symbol,
                action.side,
                action.size,
                action.price,
                "limit",
                False
            )
            self.metrics.record_error("limit_order", str(e))

            raise OrderPlacementError(
                action.symbol,
                action.side,
                action.size,
                str(e)
            )

    async def _execute_market_order(self, action: TradingAction) -> ExecutionResult:
        """执行市价单"""
        try:
            # 通过熔断器执行
            breaker = await self.circuit_manager.get_or_create(
                f"exchange_{action.symbol}",
                failure_threshold=3,
                timeout=30
            )

            order_id = await breaker.call(
                self.exchange.place_market_order,
                action.symbol,
                action.side,
                action.size
            )

            logger.info(f"Market order placed: {action.symbol} {action.side} "
                       f"{action.size:.4f} (ID: {order_id})")

            # 如果是强制平仓
            if action.metadata.get("force_close"):
                await self.notifier.alert_force_close(
                    action.symbol,
                    action.size,
                    action.side
                )

                # 记录强制平仓指标
                current_price = await self.exchange.get_price(action.symbol)
                await self.metrics.record_forced_close(
                    action.symbol,
                    action.size,
                    current_price
                )

                await self.state_manager.increment_counter(
                    action.symbol, "stats.forced_closes"
                )

            # 清理监控状态（通过deep_merge自动保留current_zone用于cooldown判断）
            await self.state_manager.update_symbol_state(action.symbol, {
                "monitoring": {
                    "active": False,
                    "started_at": None,
                    "order_id": None
                    # current_zone不更新，deep_merge会保留原值用于cooldown判断
                }
            })

            # 记录指标
            await self.metrics.record_order(
                action.symbol,
                action.side,
                action.size,
                0,  # 市价单没有指定价格
                "market",
                True
            )

            return ExecutionResult(
                action=action,
                success=True,
                result=order_id,
                metadata={"order_id": order_id}
            )

        except Exception as e:
            logger.error(f"Failed to place market order: {e}")

            # 市价单失败是严重问题
            await self.notifier.alert_critical_error(
                f"Market order failed for {action.symbol}",
                str(e)
            )

            # 记录失败指标
            await self.metrics.record_order(
                action.symbol,
                action.side,
                action.size,
                0,
                "market",
                False
            )
            self.metrics.record_error("market_order", str(e))

            raise OrderPlacementError(
                action.symbol,
                action.side,
                action.size,
                str(e)
            )

    async def _execute_cancel_order(self, action: TradingAction) -> ExecutionResult:
        """执行撤单"""
        try:
            success = await self.exchange.cancel_order(action.order_id)

            if success:
                logger.info(f"Order cancelled: {action.order_id} for {action.symbol}")
            else:
                logger.warning(f"Failed to cancel order: {action.order_id}")

            return ExecutionResult(
                action=action,
                success=success,
                result=success
            )

        except Exception as e:
            logger.error(f"Error cancelling order {action.order_id}: {e}")
            raise OrderCancellationError(action.order_id, str(e))

    async def _execute_alert(self, action: TradingAction) -> ExecutionResult:
        """执行警报"""
        try:
            alert_type = action.metadata.get("alert_type", "general")

            if alert_type == "threshold_exceeded":
                await self.notifier.alert_threshold_exceeded(
                    action.symbol,
                    action.metadata.get("offset_usd"),
                    action.metadata.get("offset"),
                    action.metadata.get("current_price")
                )

                # 记录阈值突破
                await self.metrics.record_threshold_breach(
                    action.symbol,
                    action.metadata.get("offset_usd")
                )

            elif alert_type == "error":
                await self.notifier.alert_error(
                    action.symbol,
                    action.reason
                )

            else:
                # 通用警报
                await self.notifier.send_message(
                    f"Alert: {action.symbol}",
                    action.reason
                )

            return ExecutionResult(
                action=action,
                success=True,
                result="Alert sent"
            )

        except Exception as e:
            logger.error(f"Failed to send alert: {e}")
            return ExecutionResult(
                action=action,
                success=False,
                error=e
            )

    async def batch_execute(
        self,
        actions: List[TradingAction],
        parallel: bool = False
    ) -> List[ExecutionResult]:
        """
        批量执行操作

        Args:
            actions: 操作列表
            parallel: 是否并行执行（默认串行）

        Returns:
            执行结果列表
        """
        if not actions:
            return []

        logger.info(f"Executing {len(actions)} actions ({'parallel' if parallel else 'serial'})")

        if parallel:
            # 并行执行（小心使用，可能导致竞态条件）
            tasks = [self.execute(action) for action in actions]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 处理异常结果
            final_results = []
            for action, result in zip(actions, results):
                if isinstance(result, Exception):
                    final_results.append(ExecutionResult(
                        action=action,
                        success=False,
                        error=result
                    ))
                else:
                    final_results.append(result)

            return final_results

        else:
            # 串行执行（更安全）
            results = []
            for action in actions:
                try:
                    result = await self.execute(action)
                    results.append(result)

                    # 如果是关键操作失败，可能需要停止后续操作
                    if not result.success and action.type in [
                        ActionType.PLACE_MARKET_ORDER
                    ]:
                        logger.warning(f"Critical action failed, stopping batch execution")
                        break

                except Exception as e:
                    logger.error(f"Unexpected error during batch execution: {e}")
                    results.append(ExecutionResult(
                        action=action,
                        success=False,
                        error=e
                    ))

            return results

    def _update_stats(self, action_type: ActionType, success: bool):
        """更新执行统计"""
        self.execution_stats["total"] += 1

        if success:
            self.execution_stats["success"] += 1
        else:
            self.execution_stats["failed"] += 1

        # 按类型统计
        type_key = action_type.value
        if type_key not in self.execution_stats["by_type"]:
            self.execution_stats["by_type"][type_key] = {"success": 0, "failed": 0}

        if success:
            self.execution_stats["by_type"][type_key]["success"] += 1
        else:
            self.execution_stats["by_type"][type_key]["failed"] += 1

    def get_stats(self) -> Dict[str, Any]:
        """获取执行统计"""
        return {
            **self.execution_stats,
            "success_rate": (
                self.execution_stats["success"] / self.execution_stats["total"]
                if self.execution_stats["total"] > 0
                else 0
            )
        }

    def reset_stats(self):
        """重置统计"""
        self.execution_stats = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "by_type": {}
        }