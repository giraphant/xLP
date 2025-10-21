#!/usr/bin/env python3
"""
对冲机器人 - 主协调层

职责：
- 协调所有adapters和pure functions
- 执行主对冲循环
- 调用plugin callbacks

特点：
- 数据结构优先（Linus哲学）
- 纯函数 + 适配器组合
- 插件通过回调注入
- ~200行替代1122行（HedgeEngine + DecisionEngine + ActionExecutor）
"""

import asyncio
import logging
from typing import Dict, Optional, List, Callable, Any
from datetime import datetime

# Pure functions
from core.zone_calculator import calculate_zone
from core.order_calculator import (
    calculate_order_price,
    calculate_order_size,
    calculate_order_side
)
from core.decision_logic import (
    Decision,
    decide_on_threshold_breach,
    decide_on_timeout,
    decide_on_zone_change,
    check_cooldown
)
from core.offset_tracker import calculate_offset_and_cost

# Adapters
from adapters.state_store import StateStore
from adapters.pool_fetcher import PoolFetcher

# Exchange helpers (替代 ExchangeClient)
from utils import exchange_helpers

logger = logging.getLogger(__name__)


class HedgeBot:
    """
    对冲机器人 - 简化的主协调器

    替代原来的 HedgeEngine (250行) + DecisionEngine (443行) + ActionExecutor (429行)
    简化为 ~200行
    """

    def __init__(
        self,
        # 核心配置
        config: dict,
        # 核心组件（无间接层！）
        exchange,  # 直接使用 exchange，不要 ExchangeClient 包装
        state_store: StateStore,
        pool_fetcher: PoolFetcher,
        # 可选插件（通过回调注入）
        on_decision: Optional[Callable] = None,
        on_action: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        on_report: Optional[Callable] = None
    ):
        """
        初始化对冲机器人

        Args:
            config: 配置字典
            exchange: 交易所实例（直接使用，无包装）
            state_store: 状态存储
            pool_fetcher: 池子数据获取器
            on_decision: 决策回调（用于audit log）
            on_action: 执行回调（用于metrics）
            on_error: 错误回调（用于通知）
            on_report: 报告回调（用于监控）
        """
        self.config = config
        self.exchange = exchange  # 直接使用 exchange！
        self.state = state_store
        self.pools = pool_fetcher

        # 插件回调
        self.on_decision = on_decision or (lambda *args, **kwargs: None)
        self.on_action = on_action or (lambda *args, **kwargs: None)
        self.on_error = on_error or (lambda *args, **kwargs: None)
        self.on_report = on_report or (lambda *args, **kwargs: None)

        # 提取核心配置
        self.threshold_min = config.get("threshold_min_usd", 5.0)
        self.threshold_max = config.get("threshold_max_usd", 20.0)
        self.threshold_step = config.get("threshold_step_usd", 2.5)
        self.price_offset_pct = config.get("order_price_offset", 0.2)
        self.close_ratio = config.get("close_ratio", 40.0)
        self.timeout_minutes = config.get("timeout_minutes", 20)
        self.cooldown_minutes = config.get("cooldown_after_fill_minutes", 5)

        logger.info(f"HedgeBot initialized with thresholds: ${self.threshold_min}-${self.threshold_max}")

    async def run_once(self) -> Dict[str, Any]:
        """
        执行一次完整的对冲检查循环

        Returns:
            执行结果摘要
        """
        start_time = datetime.now()
        step_timings = {}  # 记录每个步骤的耗时

        logger.info("="*70)
        logger.info(f"🚀 HEDGE BOT RUN - {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("="*70)

        try:
            # 步骤1: 获取池子理想对冲
            step_start = datetime.now()
            pool_configs = {
                "jlp": {"amount": self.config.get("jlp_amount", 0)},
                "alp": {"amount": self.config.get("alp_amount", 0)}
            }
            ideal_hedges = await self.pools.fetch_pool_hedges(pool_configs)
            step_timings["FetchPoolData"] = (datetime.now() - step_start).total_seconds()

            # 步骤2: 获取当前仓位和价格
            step_start = datetime.now()
            positions = await self.exchange.get_positions()
            prices = await exchange_helpers.get_prices(self.exchange, list(ideal_hedges.keys()))
            step_timings["FetchMarketData"] = (datetime.now() - step_start).total_seconds()

            # 步骤3: 计算offset和决策
            step_start = datetime.now()
            decisions = []
            symbol_details = {}  # 收集每个symbol的详细信息

            for symbol, ideal_hedge in ideal_hedges.items():
                try:
                    decision, details = await self._process_symbol(
                        symbol=symbol,
                        ideal_hedge=ideal_hedge,
                        current_position=positions.get(symbol, 0.0),
                        current_price=prices.get(symbol, 0.0)
                    )
                    if decision:
                        decisions.append(decision)
                    symbol_details[symbol] = details
                except Exception as e:
                    logger.error(f"❌ Error processing {symbol}: {e}")
                    await self.on_error(symbol=symbol, error=str(e))

            step_timings["ProcessDecisions"] = (datetime.now() - step_start).total_seconds()

            # 步骤4: 执行决策
            step_start = datetime.now()
            results = []
            for decision in decisions:
                if decision.action != "wait":
                    try:
                        result = await self._execute_decision(decision)
                        results.append(result)
                    except Exception as e:
                        logger.error(f"❌ Error executing {decision}: {e}")
                        await self.on_error(decision=decision, error=str(e))
            step_timings["ExecuteActions"] = (datetime.now() - step_start).total_seconds()

            # 步骤5: 打印详细仓位报告
            logger.info("="*70)
            logger.info("📊 DETAILED POSITION REPORT")
            logger.info("="*70)
            logger.info("")

            total_exposure_usd = 0.0
            total_pnl = 0.0

            for symbol in sorted(symbol_details.keys()):
                details = symbol_details[symbol]
                offset = details["offset"]
                offset_usd = details["offset_usd"]
                current_price = details["current_price"]
                cost_basis = details["cost_basis"]
                unrealized_pnl = details["unrealized_pnl"]
                pnl_pct = details["pnl_pct"]
                decision = details["decision"]
                reason = details["reason"]
                monitoring = details["monitoring"]

                total_exposure_usd += offset_usd
                total_pnl += unrealized_pnl

                logger.info(f"【{symbol}】")
                if offset > 0:
                    logger.info(f"  状态: 🔴 LONG 需要卖出平仓")
                elif offset < 0:
                    logger.info(f"  状态: 🟢 SHORT 需要买入平仓")
                else:
                    logger.info(f"  状态: ⚖️  BALANCED")

                logger.info(f"  偏移: {offset:+.6f} {symbol} (${offset_usd:.2f})")
                logger.info(f"  当前价格: ${current_price:.2f}")
                logger.info(f"  平均成本: ${cost_basis:.2f}")

                if unrealized_pnl != 0:
                    pnl_emoji = "💚" if unrealized_pnl > 0 else "❤️ "
                    logger.info(f"  浮动盈亏: {pnl_emoji} ${unrealized_pnl:+.2f} ({pnl_pct:+.2f}%)")

                if monitoring:
                    elapsed = (datetime.now() - monitoring["started_at"]).total_seconds() / 60
                    logger.info(f"  📍 监控中: Zone {monitoring['zone']} | 订单 {monitoring['order_id']} | {elapsed:.1f}分钟")

                if decision == "wait":
                    logger.info(f"  决策: ⏸️  无操作")
                elif decision == "place_order":
                    logger.info(f"  决策: 📝 挂单")
                elif decision == "market_order":
                    logger.info(f"  决策: 🚨 市价单")
                elif decision == "cancel":
                    logger.info(f"  决策: ❌ 撤单")
                elif decision == "alert":
                    logger.info(f"  决策: ⚠️  警报")

                logger.info(f"  原因: {reason}")
                logger.info("")

            logger.info(f"📊 总计:")
            logger.info(f"  总敞口: ${total_exposure_usd:.2f}")
            pnl_emoji = "💚" if total_pnl >= 0 else "❤️ "
            logger.info(f"  总盈亏: {pnl_emoji} ${total_pnl:+.2f}")
            logger.info("="*70)

            # 步骤6: Pipeline执行总结
            duration = (datetime.now() - start_time).total_seconds()
            success_count = sum(1 for r in results if r.get("success"))
            failed_count = len(results) - success_count

            logger.info("="*70)
            logger.info("📊 PIPELINE EXECUTION SUMMARY")
            logger.info("="*70)
            logger.info("📈 Step Results:")
            for step_name, step_time in step_timings.items():
                logger.info(f"  ✅ {step_name}: success ({step_time:.2f}s)")

            logger.info("💰 Position Summary:")
            for symbol, details in symbol_details.items():
                offset = details["offset"]
                offset_usd = details["offset_usd"]
                status_emoji = "🔴" if offset > 0 else "🟢" if offset < 0 else "⚖️ "
                status_text = "LONG" if offset > 0 else "SHORT" if offset < 0 else "BALANCED"
                logger.info(f"  • {symbol}: {status_emoji} {status_text} ${offset_usd:.2f} (Offset: {offset:+.4f})")

            logger.info(f"  📊 Total Exposure: ${total_exposure_usd:.2f}")

            logger.info(f"⚡ Actions Executed: {success_count}/{len(results)} successful")
            logger.info(f"⏱️  Total Time: {len(step_timings)} steps completed in {duration:.2f}s")
            logger.info("="*70)
            logger.info(f"✅ PIPELINE COMPLETED - Duration: {duration:.2f}s")
            logger.info("="*70)

            summary = {
                "timestamp": start_time.isoformat(),
                "duration": duration,
                "symbols_processed": len(ideal_hedges),
                "decisions_made": len(decisions),
                "actions_executed": len(results),
                "actions_succeeded": success_count,
                "actions_failed": failed_count,
                "total_exposure_usd": total_exposure_usd,
                "total_pnl": total_pnl,
                "results": results
            }

            await self.on_report(summary=summary)
            return summary

        except Exception as e:
            logger.error(f"Run failed: {e}")
            await self.on_error(error=str(e))
            raise

    async def _process_symbol(
        self,
        symbol: str,
        ideal_hedge: float,
        current_position: float,
        current_price: float
    ) -> tuple[Optional[Decision], Dict[str, Any]]:
        """
        处理单个symbol的决策逻辑

        Args:
            symbol: 币种符号
            ideal_hedge: 理想对冲仓位
            current_position: 当前仓位
            current_price: 当前价格

        Returns:
            决策对象（如果需要操作）
        """
        # 应用初始偏移
        initial_offset = self.config.get("initial_offset", {}).get(symbol, 0.0)
        adjusted_position = current_position + initial_offset

        # 计算offset和cost_basis
        offset, cost_basis = calculate_offset_and_cost(
            ideal=ideal_hedge,
            actual=adjusted_position,
            price=current_price
        )

        # 应用预定义偏移（外部对冲调整）
        predefined_offset = self.config.get("predefined_offset", {}).get(symbol, 0.0)
        raw_offset = offset
        if predefined_offset != 0.0:
            offset = offset - predefined_offset

        offset_usd = abs(offset) * current_price

        # 计算浮动盈亏
        if cost_basis > 0 and offset != 0:
            unrealized_pnl = -offset * (current_price - cost_basis)  # 负号因为offset是需要平仓的量
            pnl_pct = (unrealized_pnl / (abs(offset) * cost_basis)) * 100
        else:
            unrealized_pnl = 0.0
            pnl_pct = 0.0

        # 获取symbol状态
        state = self.state.get_symbol_state(symbol)
        monitoring = state.monitoring
        started_at = monitoring.started_at
        last_fill_time = state.last_fill_time

        # 决策1: 检查阈值
        decision = decide_on_threshold_breach(offset_usd, self.threshold_max)
        if decision.action == "alert":
            decision.metadata = decision.metadata or {}
            decision.metadata["symbol"] = symbol
            decision.metadata["offset"] = offset
            decision.metadata["offset_usd"] = offset_usd
            await self.on_decision(symbol=symbol, decision=decision)

        # 决策2: 检查超时
        if decision.action == "wait" and started_at:
            timeout_decision = decide_on_timeout(started_at, self.timeout_minutes, offset, self.close_ratio)
            if timeout_decision:
                decision = timeout_decision
                decision.metadata = decision.metadata or {}
                decision.metadata["symbol"] = symbol
                decision.metadata["offset"] = offset
                decision.metadata["offset_usd"] = offset_usd
                await self.on_decision(symbol=symbol, decision=decision)

        # 决策3: 检查zone变化
        if decision.action == "wait":
            old_zone = monitoring.current_zone
            new_zone = calculate_zone(offset_usd, self.threshold_min, self.threshold_max, self.threshold_step)

            in_cooldown = False
            if last_fill_time:
                in_cooldown = check_cooldown(last_fill_time, self.cooldown_minutes)

            decision = decide_on_zone_change(
                old_zone=old_zone,
                new_zone=new_zone,
                in_cooldown=in_cooldown,
                offset=offset,
                cost_basis=cost_basis,
                close_ratio=self.close_ratio,
                price_offset_pct=self.price_offset_pct
            )

            decision.metadata = decision.metadata or {}
            decision.metadata["symbol"] = symbol
            decision.metadata["offset"] = offset
            decision.metadata["offset_usd"] = offset_usd
            decision.metadata["zone"] = new_zone
            await self.on_decision(symbol=symbol, decision=decision)

        # 收集详细信息
        details = {
            "symbol": symbol,
            "offset": offset,
            "offset_usd": offset_usd,
            "current_price": current_price,
            "cost_basis": cost_basis,
            "unrealized_pnl": unrealized_pnl,
            "pnl_pct": pnl_pct,
            "decision": decision.action,
            "reason": decision.reason,
            "monitoring": {
                "zone": monitoring.current_zone,
                "order_id": monitoring.order_id,
                "started_at": started_at
            } if started_at else None
        }

        return decision, details

    async def _execute_decision(self, decision: Decision) -> Dict[str, Any]:
        """
        执行决策

        Args:
            decision: 决策对象

        Returns:
            执行结果
        """
        symbol = decision.metadata.get("symbol")
        action = decision.action

        result = {
            "symbol": symbol,
            "action": action,
            "success": False,
            "reason": decision.reason
        }

        try:
            if action == "place_order":
                # 挂限价单（带确认）
                order_id = await exchange_helpers.place_limit_order_confirmed(
                    self.exchange,
                    symbol=symbol,
                    side=decision.side,
                    size=decision.size,
                    price=decision.price
                )
                result["order_id"] = order_id
                result["success"] = True

                # 更新状态（同步操作）
                zone = decision.metadata.get("zone")
                self.state.start_monitoring(symbol, order_id, zone)

            elif action == "market_order":
                # 市价单
                order_id = await exchange_helpers.place_market_order(
                    self.exchange,
                    symbol=symbol,
                    side=decision.side,
                    size=decision.size
                )
                result["order_id"] = order_id
                result["success"] = True

                # 更新状态（清除monitoring，记录成交时间）
                self.state.stop_monitoring(symbol, with_fill=True)

            elif action == "cancel":
                # 撤单
                state = self.state.get_symbol_state(symbol)
                existing_order_id = state.monitoring.order_id
                if existing_order_id:
                    await exchange_helpers.cancel_order(self.exchange, symbol, existing_order_id)
                    result["success"] = True

                    # 更新状态（停止监控）
                    self.state.stop_monitoring(symbol, with_fill=False)

            elif action == "alert":
                # 警报 - 记录到日志和通知系统
                logger.warning(f"⚠️  ALERT: {symbol} - {decision.reason}")
                offset_usd = decision.metadata.get("offset_usd", 0)
                logger.warning(f"   Offset: ${offset_usd:.2f} exceeds threshold")
                result["success"] = True  # Alert 总是成功

            await self.on_action(symbol=symbol, action=action, result=result)

        except Exception as e:
            logger.error(f"Execution failed for {symbol}: {e}")
            result["error"] = str(e)
            await self.on_error(symbol=symbol, action=action, error=str(e))

        return result
