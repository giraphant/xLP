#!/usr/bin/env python3
"""
对冲引擎核心模块
负责计算偏移、判断区间、执行平仓逻辑
"""

import json
import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path

# 导入本地模块
from exchanges.interface import create_exchange
from notifications.pushover import Notifier
from core.offset_tracker import calculate_offset_and_cost
from core.state_manager import StateManager
from core.circuit_breaker import CircuitBreakerManager
from core.exceptions import HedgeEngineError, InvalidConfigError
from core.config_validator import HedgeConfig, ValidationError
from core.metrics import MetricsCollector
from core.pipeline import PipelineContext, create_hedge_pipeline
from core.decision_engine import DecisionEngine
from core.action_executor import ActionExecutor
from pools import jlp, alp

logger = logging.getLogger(__name__)


class HedgeEngine:
    def __init__(self, config_path: str = "config.json"):
        self.config_path = Path(config_path)

        # 使用新的配置验证器加载配置
        try:
            self.validated_config = HedgeConfig.from_env_and_file(self.config_path)
            self.config = self.validated_config.to_dict()  # 兼容旧代码
            logger.info(self.validated_config.get_summary())
        except ValidationError as e:
            logger.critical(f"Configuration validation failed: {e}")
            raise InvalidConfigError("config", str(e), "Valid configuration required")

        # 初始化状态管理器（内存模式）
        self.state_manager = StateManager()

        # 初始化熔断器管理器
        self.circuit_manager = CircuitBreakerManager()

        # 初始化指标收集器
        self.metrics = MetricsCollector()

        # 初始化交易所和通知器
        self.exchange = create_exchange(self.config["exchange"])
        self.notifier = Notifier(self.config["pushover"])

        # 初始化决策引擎
        self.decision_engine = DecisionEngine(self.config, self.state_manager)

        # 初始化操作执行器
        self.action_executor = ActionExecutor(
            exchange=self.exchange,
            state_manager=self.state_manager,
            notifier=self.notifier,
            metrics_collector=self.metrics,
            circuit_manager=self.circuit_manager
        )

        # 创建完整的数据处理管道
        self.pipeline = self._create_full_pipeline()

    def _create_full_pipeline(self):
        """创建完整的数据处理管道"""
        # 准备池子计算器
        pool_calculators = {
            "jlp": jlp.calculate_hedge,
            "alp": alp.calculate_hedge
        }

        # 使用工厂函数创建管道
        return create_hedge_pipeline(
            pool_calculators=pool_calculators,
            exchange=self.exchange,
            state_manager=self.state_manager,
            offset_calculator=calculate_offset_and_cost,
            decision_engine=self.decision_engine,
            action_executor=self.action_executor
        )

    async def run_once_pipeline(self):
        """使用管道执行一次完整的对冲检查循环"""
        start_time = time.time()
        logger.info(f"{'='*70}")
        logger.info(f"🚀 HEDGE ENGINE PIPELINE - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{'='*70}")

        try:
            # 准备管道上下文
            context = PipelineContext(
                config={
                    **self.config,
                    "jlp": {"amount": self.config["jlp_amount"]},
                    "alp": {"amount": self.config["alp_amount"]}
                }
            )

            # 执行管道
            context = await self.pipeline.execute(context)

            # 处理管道结果
            if context.results:
                success_count = sum(1 for r in context.results if r.status.value == "success")
                failed_count = sum(1 for r in context.results if r.status.value == "failed")

                # 检查是否有关键步骤失败
                critical_failures = [
                    r for r in context.results
                    if r.status.value == "failed" and r.name in ["FetchPoolData", "CalculateIdealHedges"]
                ]

                if critical_failures:
                    logger.error(f"❌ Critical steps failed: {[f.name for f in critical_failures]}")
                    raise HedgeEngineError("Critical pipeline steps failed")

                # 生成最终摘要报告
                logger.info("=" * 70)
                logger.info("📊 PIPELINE EXECUTION SUMMARY")
                logger.info("=" * 70)

                # 显示各步骤状态
                logger.info("📈 Step Results:")
                for result in context.results:
                    status_icon = "✅" if result.status.value == "success" else "❌"
                    logger.info(f"  {status_icon} {result.name}: {result.status.value} ({result.duration:.2f}s)")

                # 显示关键指标 - 增强版，显示完整决策信息
                if context.offsets:
                    logger.info("💰 Position Summary:")
                    total_offset_usd = 0

                    for symbol, (offset, cost_basis) in context.offsets.items():
                        if symbol in context.prices:
                            current_price = context.prices[symbol]
                            offset_usd = abs(offset) * current_price
                            total_offset_usd += offset_usd

                            # 状态标识
                            if offset > 0:
                                status = "🔴 LONG"
                                direction = "需要卖出平仓"
                            elif offset < 0:
                                status = "🟢 SHORT"
                                direction = "需要买入平仓"
                            else:
                                status = "✅ BALANCED"
                                direction = "无需操作"

                            # 基础信息
                            logger.info(f"")
                            logger.info(f"  【{symbol}】")
                            logger.info(f"    状态: {status} {direction}")
                            logger.info(f"    偏移: {offset:+.6f} {symbol} (${offset_usd:.2f})")
                            logger.info(f"    当前价格: ${current_price:.2f}")

                            # 成本和盈亏信息
                            if cost_basis > 0 and offset != 0:
                                logger.info(f"    平均成本: ${cost_basis:.2f}")
                                pnl = (current_price - cost_basis) * abs(offset)
                                pnl_percent = ((current_price - cost_basis) / cost_basis) * 100
                                pnl_status = "💚" if pnl > 0 else "❤️" if pnl < 0 else "💛"
                                logger.info(f"    浮动盈亏: {pnl_status} ${pnl:+.2f} ({pnl_percent:+.2f}%)")

                            # 获取决策信息
                            symbol_state = await self.state_manager.get_symbol_state(symbol)
                            monitoring = symbol_state.get("monitoring", {})

                            # 显示监控状态
                            if monitoring.get("active"):
                                zone = monitoring.get("current_zone", "N/A")
                                order_id = monitoring.get("order_id", "N/A")
                                started_at = monitoring.get("started_at", "")

                                # 计算监控时长
                                if started_at:
                                    start_time = datetime.fromisoformat(started_at)
                                    elapsed = (datetime.now() - start_time).total_seconds() / 60
                                    logger.info(f"    📍 监控中: Zone {zone} | 订单 {order_id} | 已监控 {elapsed:.1f}分钟")
                                else:
                                    logger.info(f"    📍 监控中: Zone {zone} | 订单 {order_id}")

                            # 显示决策逻辑（从 context.actions 获取）
                            if hasattr(context, 'actions') and context.actions:
                                symbol_action = next((a for a in context.actions if a.symbol == symbol), None)
                                if symbol_action:
                                    action_desc = {
                                        "place_limit_order": f"✅ 下限价单: {symbol_action.side.upper()} {symbol_action.size:.6f} @ ${symbol_action.price:.2f}",
                                        "place_market_order": f"⚡ 下市价单: {symbol_action.side.upper()} {symbol_action.size:.6f}",
                                        "cancel_order": f"🚫 撤单: {symbol_action.order_id}",
                                        "no_action": "⏸️  无操作",
                                        "alert": f"⚠️  警报: {symbol_action.reason}"
                                    }.get(symbol_action.type.value, "未知操作")

                                    logger.info(f"    决策: {action_desc}")

                                    # 显示决策原因
                                    if symbol_action.reason:
                                        logger.info(f"    原因: {symbol_action.reason}")

                    logger.info(f"")
                    logger.info(f"  📊 Total Exposure: ${total_offset_usd:.2f}")

                # 显示执行结果
                if context.metadata.get("execution_results"):
                    exec_results = context.metadata["execution_results"]
                    exec_success = sum(1 for r in exec_results if r.success)
                    logger.info(f"⚡ Actions Executed: {exec_success}/{len(exec_results)} successful")

                logger.info(f"⏱️ Total Time: {success_count} steps completed in {time.time() - start_time:.2f}s")

            # 更新元数据
            await self.state_manager.update_metadata({
                "last_check": datetime.now().isoformat(),
                "total_runs": (await self.state_manager.get_metadata()).get("total_runs", 0) + 1
            })

            # 清理超时的订单监控
            await self.state_manager.cleanup_stale_orders()

            # 清理空闲的熔断器
            self.circuit_manager.cleanup_idle()

            # 记录处理时间指标
            processing_time = time.time() - start_time
            await self.metrics.record_processing("pipeline_run", processing_time)

            # 定期导出指标摘要（每10次运行）
            total_runs = (await self.state_manager.get_metadata()).get("total_runs", 0)
            if total_runs % 10 == 0:
                summary = await self.metrics.export_summary()
                logger.info(f"Metrics Summary: {json.dumps(summary, indent=2)}")

            logger.info("=" * 70)
            logger.info(f"✅ PIPELINE COMPLETED - Duration: {processing_time:.2f}s")
            logger.info("=" * 70)

        except Exception as e:
            logger.error(f"Pipeline execution error: {e}")
            # 记录错误指标
            self.metrics.record_error(type(e).__name__, str(e))

            # 记录最后的错误
            await self.state_manager.update_metadata({
                "last_error": str(e),
                "last_error_time": datetime.now().isoformat()
            })
            raise

    async def run_once(self):
        """执行一次检查循环 - 使用数据管道架构"""
        return await self.run_once_pipeline()


async def main():
    """测试主函数"""
    engine = HedgeEngine()
    await engine.run_once()


if __name__ == "__main__":
    asyncio.run(main())
