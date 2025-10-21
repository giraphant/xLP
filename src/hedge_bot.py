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
        logger.info("="*50)
        logger.info(f"🚀 HEDGE BOT RUN - {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("="*50)

        try:
            # 步骤1: 获取池子理想对冲
            logger.info("="*50)
            logger.info("📊 FETCHING POOL DATA")
            logger.info("="*50)

            pool_configs = {
                "jlp": {"amount": self.config.get("jlp_amount", 0)},
                "alp": {"amount": self.config.get("alp_amount", 0)}
            }

            # 显示配置
            for pool_type, cfg in pool_configs.items():
                if cfg["amount"] > 0:
                    logger.info(f"🏊 {pool_type.upper()} Pool: Amount = {cfg['amount']:,.2f}")

            ideal_hedges = await self.pools.fetch_pool_hedges(pool_configs)

            logger.info("📊 IDEAL HEDGES (Negative = Short):")
            for symbol, hedge in sorted(ideal_hedges.items()):
                logger.info(f"  💹 {symbol}: {hedge:+.4f}")
            logger.info(f"✅ Fetched ideal hedges for {len(ideal_hedges)} symbols")

            # 步骤2: 获取当前仓位和价格
            logger.info("="*50)
            logger.info("💹 FETCHING MARKET DATA")
            logger.info("="*50)

            positions = await self.exchange.get_positions()
            prices = await exchange_helpers.get_prices(self.exchange, list(ideal_hedges.keys()))

            logger.info("📈 CURRENT PRICES:")
            for symbol in sorted(prices.keys()):
                logger.info(f"  💵 {symbol}: ${prices[symbol]:,.2f}")

            logger.info("📊 ACTUAL POSITIONS:")
            for symbol in sorted(ideal_hedges.keys()):
                pos = positions.get(symbol, 0.0)
                # 应用初始偏移
                initial_offset = self.config.get("initial_offset", {}).get(symbol, 0.0)
                if initial_offset != 0:
                    total_pos = pos + initial_offset
                    logger.info(f"  📍 {symbol}: {total_pos:+.4f} (Exchange: {pos:+.4f}, Initial: {initial_offset:+.4f})")
                else:
                    logger.info(f"  📍 {symbol}: {pos:+.4f}")

            logger.info(f"✅ Fetched market data for {len(prices)} symbols")

            # 步骤3: 计算每个symbol的offset和决策
            logger.info("="*50)
            logger.info("🤔 DECISION ENGINE - EVALUATING ACTIONS")
            logger.info("="*50)
            logger.info(f"⚡ Thresholds: ${self.threshold_min:.2f} - ${self.threshold_max:.2f} (Step: ${self.threshold_step:.2f})")

            decisions = []
            for symbol, ideal_hedge in ideal_hedges.items():
                try:
                    decision = await self._process_symbol(
                        symbol=symbol,
                        ideal_hedge=ideal_hedge,
                        current_position=positions.get(symbol, 0.0),
                        current_price=prices.get(symbol, 0.0)
                    )
                    if decision:
                        decisions.append(decision)
                except Exception as e:
                    logger.error(f"❌ Error processing {symbol}: {e}")
                    await self.on_error(symbol=symbol, error=str(e))

            # 显示决策结果汇总
            logger.info("📋 DECISIONS:")
            action_counts = {}
            for decision in decisions:
                action = decision.action
                action_counts[action] = action_counts.get(action, 0) + 1

                symbol = decision.metadata.get("symbol")
                if action == "place_order":
                    logger.info(f"  📝 {symbol}: PLACE LIMIT {decision.side.upper()} "
                               f"{decision.size:.4f} @ ${decision.price:.2f} - {decision.reason}")
                elif action == "market_order":
                    logger.info(f"  🚨 {symbol}: PLACE MARKET {decision.side.upper()} "
                               f"{decision.size:.4f} - {decision.reason}")
                elif action == "cancel":
                    logger.info(f"  ❌ {symbol}: CANCEL ORDER - {decision.reason}")
                elif action == "alert":
                    logger.info(f"  ⚠️  {symbol}: ALERT - {decision.reason}")
                else:
                    logger.debug(f"  ✅ {symbol}: NO ACTION - {decision.reason}")

            logger.info(f"📊 Summary: {action_counts}")
            logger.info(f"✅ Decided on {len(decisions)} actions")

            # 步骤4: 执行决策
            logger.info("="*50)
            logger.info("⚡ EXECUTING ACTIONS")
            logger.info("="*50)

            results = []
            for decision in decisions:
                if decision.action != "wait":
                    try:
                        result = await self._execute_decision(decision)
                        results.append(result)
                    except Exception as e:
                        logger.error(f"❌ Error executing {decision}: {e}")
                        await self.on_error(decision=decision, error=str(e))

            # 显示执行结果
            if results:
                logger.info("📊 EXECUTION RESULTS:")
                success_count = sum(1 for r in results if r.get("success"))
                failed_count = len(results) - success_count
                for i, result in enumerate(results, 1):
                    symbol = result.get("symbol")
                    action = result.get("action")
                    if result.get("success"):
                        if "order_id" in result:
                            logger.info(f"  ✅ [{i}] {symbol}: {action} - Order ID: {result['order_id']}")
                        else:
                            logger.info(f"  ✅ [{i}] {symbol}: {action} completed")
                    else:
                        logger.error(f"  ❌ [{i}] {symbol}: {action} failed - {result.get('error')}")

                logger.info(f"📈 EXECUTION STATISTICS:")
                logger.info(f"  • Total Actions: {len(results)}")
                logger.info(f"  • Successful: {success_count}")
                logger.info(f"  • Failed: {failed_count}")
            else:
                logger.info("✅ No actions to execute")

            # 步骤5: 生成摘要报告
            duration = (datetime.now() - start_time).total_seconds()
            summary = {
                "timestamp": start_time.isoformat(),
                "duration": duration,
                "symbols_processed": len(ideal_hedges),
                "decisions_made": len(decisions),
                "actions_executed": len(results),
                "results": results
            }

            logger.info(f"✅ Run complete: {len(results)} actions in {duration:.2f}s")
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
    ) -> Optional[Decision]:
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

        # 详细日志
        logger.info(f"📊 {symbol}:")
        logger.info(f"  ├─ Ideal Position: {ideal_hedge:+.4f}")
        logger.info(f"  ├─ Actual Position: {adjusted_position:+.4f}")
        if predefined_offset != 0.0:
            logger.info(f"  ├─ Raw Offset: {raw_offset:+.4f} ({abs(raw_offset) * current_price:.2f} USD)")
            logger.info(f"  ├─ Predefined Adjustment: {predefined_offset:+.4f}")
        logger.info(f"  ├─ Final Offset: {offset:+.4f} ({offset_usd:.2f} USD)")
        logger.info(f"  ├─ Cost Basis: ${cost_basis:.2f}")

        # 显示偏移方向
        if offset > 0:
            logger.info(f"  └─ Status: 🔴 LONG exposure (Need to SELL {abs(offset):.4f})")
        elif offset < 0:
            logger.info(f"  └─ Status: 🟢 SHORT exposure (Need to BUY {abs(offset):.4f})")
        else:
            logger.info(f"  └─ Status: ✅ BALANCED")

        # 决策1: 检查阈值
        decision = decide_on_threshold_breach(offset_usd, self.threshold_max)
        if decision.action == "alert":
            # 添加symbol和offset信息到metadata
            decision.metadata = decision.metadata or {}
            decision.metadata["symbol"] = symbol
            decision.metadata["offset"] = offset
            decision.metadata["offset_usd"] = offset_usd
            await self.on_decision(symbol=symbol, decision=decision)
            return decision

        # 获取symbol状态（同步操作，无需 await）
        state = self.state.get_symbol_state(symbol)
        monitoring = state.monitoring
        started_at = monitoring.started_at
        last_fill_time = state.last_fill_time

        # 决策2: 检查超时
        if started_at:
            decision = decide_on_timeout(started_at, self.timeout_minutes, offset, self.close_ratio)
            if decision:
                # 添加symbol和offset信息到metadata
                decision.metadata = decision.metadata or {}
                decision.metadata["symbol"] = symbol
                decision.metadata["offset"] = offset
                decision.metadata["offset_usd"] = offset_usd
                await self.on_decision(symbol=symbol, decision=decision)
                return decision

        # 决策3: 检查zone变化
        old_zone = monitoring.current_zone
        new_zone = calculate_zone(offset_usd, self.threshold_min, self.threshold_max, self.threshold_step)

        # 检查cooldown
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

        # 附加symbol和metadata
        decision.metadata = decision.metadata or {}
        decision.metadata["symbol"] = symbol
        decision.metadata["offset"] = offset
        decision.metadata["offset_usd"] = offset_usd
        decision.metadata["zone"] = new_zone

        await self.on_decision(symbol=symbol, decision=decision)
        return decision

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

        logger.info(f"⚡ Executing {action} for {symbol}: {decision.reason}")

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

            await self.on_action(symbol=symbol, action=action, result=result)

        except Exception as e:
            logger.error(f"Execution failed for {symbol}: {e}")
            result["error"] = str(e)
            await self.on_error(symbol=symbol, action=action, error=str(e))

        return result
