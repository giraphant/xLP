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
from exchanges import create_exchange
from utils.notifier import Notifier
from core.offset_tracker import calculate_offset_and_cost
from core.state_manager import StateManager
from core.exceptions import HedgeEngineError, InvalidConfigError
from core.pipeline import PipelineContext, create_hedge_pipeline
from core.decision_engine import DecisionEngine
from core.action_executor import ActionExecutor
from utils.breakers import CircuitBreakerManager
from utils.config import HedgeConfig, ValidationError
from utils.matsu_reporter import MatsuReporter
from pools import jlp, alp

logger = logging.getLogger(__name__)


class HedgeEngine:
    def __init__(self, config_path: str = "config.json"):
        self.config_path = Path(config_path)

        # 使用 Pydantic 配置加载（自动从环境变量和 .env 文件读取）
        try:
            self.validated_config = HedgeConfig()
            self.config = self.validated_config.to_dict()  # 兼容旧代码
            logger.info(self.validated_config.get_summary())
        except ValidationError as e:
            logger.critical(f"Configuration validation failed: {e}")
            raise InvalidConfigError("config", str(e), "Valid configuration required")

        # 初始化状态管理器（内存模式）
        self.state_manager = StateManager()

        # 初始化熔断器管理器
        self.circuit_manager = CircuitBreakerManager()

        # 初始化交易所和通知器
        self.exchange = create_exchange(self.config["exchange"])
        self.notifier = Notifier(self.config["pushover"])

        # 初始化Matsu监控上报器（可选插件）
        self.matsu_reporter = self._initialize_matsu_reporter()

        # 初始化决策引擎
        self.decision_engine = DecisionEngine(self.config, self.state_manager)

        # 初始化操作执行器
        self.action_executor = ActionExecutor(
            exchange=self.exchange,
            state_manager=self.state_manager,
            notifier=self.notifier,
            metrics_collector=None,  # Metrics已移除
            circuit_manager=self.circuit_manager
        )

        # 创建完整的数据处理管道
        self.pipeline = self._create_full_pipeline()

    def _initialize_matsu_reporter(self):
        """初始化Matsu监控上报器（可选）"""
        matsu_config = self.config.get("matsu", {})

        if not matsu_config.get("enabled", False):
            logger.debug("Matsu reporter disabled")
            return None

        auth_token = matsu_config.get("auth_token", "")
        if not auth_token:
            logger.warning("Matsu reporter enabled but auth_token is empty")
            return None

        try:
            api_url = matsu_config.get("api_endpoint", "https://distill.baa.one/api/hedge-data")
            pool_name = matsu_config.get("pool_name", "xLP")
            timeout = matsu_config.get("timeout", 10)

            reporter = MatsuReporter(
                api_url=api_url,
                auth_token=auth_token,
                enabled=True,
                timeout=timeout,
                pool_name=pool_name
            )
            logger.info(f"✅ Matsu reporter enabled: {pool_name}")
            return reporter
        except Exception as e:
            logger.error(f"Failed to initialize Matsu reporter: {e}")
            return None

    def _create_full_pipeline(self):
        """创建完整的数据处理管道"""
        # 准备池子计算器
        pool_calculators = {
            "jlp": jlp.calculate_hedge,
            "alp": alp.calculate_hedge
        }

        # 使用工厂函数创建管道（包含可选的Matsu上报中间件）
        return create_hedge_pipeline(
            pool_calculators=pool_calculators,
            exchange=self.exchange,
            state_manager=self.state_manager,
            offset_calculator=calculate_offset_and_cost,
            decision_engine=self.decision_engine,
            action_executor=self.action_executor,
            cooldown_minutes=self.config.get("cooldown_after_fill_minutes", 5),
            matsu_reporter=self.matsu_reporter  # 🆕 可选的Matsu上报插件
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

            # 为 reporting 提供 state_manager
            context.metadata["state_manager"] = self.state_manager

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

                # 显示关键指标
                if context.offsets:
                    logger.info("💰 Position Summary:")
                    total_offset_usd = 0
                    for symbol, (offset, cost_basis) in context.offsets.items():
                        if symbol in context.prices:
                            offset_usd = abs(offset) * context.prices[symbol]
                            total_offset_usd += offset_usd
                            status = "🔴 LONG" if offset > 0 else ("🟢 SHORT" if offset < 0 else "✅ BALANCED")
                            logger.info(f"  • {symbol}: {status} ${offset_usd:.2f} (Offset: {offset:+.4f})")
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

            # 记录处理时间
            processing_time = time.time() - start_time

            logger.info("=" * 70)
            logger.info(f"✅ PIPELINE COMPLETED - Duration: {processing_time:.2f}s")
            logger.info("=" * 70)

        except Exception as e:
            logger.error(f"Pipeline execution error: {e}")

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
