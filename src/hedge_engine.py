#!/usr/bin/env python3
"""
对冲引擎核心模块
负责计算偏移、判断区间、执行平仓逻辑
"""

import json
import os
import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from pathlib import Path

# 导入本地模块
from exchanges.interface import create_exchange
from notifications.pushover import Notifier
from core.offset_tracker import calculate_offset_and_cost
from core.state_manager import StateManager
from core.circuit_breaker import CircuitBreaker, CircuitBreakerManager
from core.exceptions import (
    HedgeEngineError,
    ChainReadError,
    ExchangeError,
    OrderPlacementError,
    OrderCancellationError,
    InvalidConfigError,
    MissingConfigError,
    CalculationError,
    classify_exception,
    should_retry,
    get_retry_delay
)
from core.config_validator import HedgeConfig, ValidationError
from core.metrics import MetricsCollector
from core.pipeline import (
    HedgePipeline,
    PipelineContext,
    create_hedge_pipeline,
    FetchPoolDataStep,
    CalculateIdealHedgesStep,
    FetchMarketDataStep,
    CalculateOffsetsStep,
    DecideActionsStep,
    ExecuteActionsStep,
    logging_middleware,
    timing_middleware,
    error_collection_middleware
)
from core.decision_engine import DecisionEngine, TradingAction, ActionType
from core.action_executor import ActionExecutor, ExecutionResult
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

    def _load_config(self) -> dict:
        """
        加载配置 - 优先使用环境变量，config.json作为默认值
        环境变量 > config.json
        """
        # 从config.json加载默认值（如果存在）
        config = {}
        if self.config_path.exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

        # 从环境变量覆盖（优先级更高）
        config["jlp_amount"] = float(os.getenv("JLP_AMOUNT", config.get("jlp_amount", 50000)))
        config["alp_amount"] = float(os.getenv("ALP_AMOUNT", config.get("alp_amount", 10000)))

        config["threshold_min_usd"] = float(os.getenv("THRESHOLD_MIN_USD", config.get("threshold_min_usd", 5.0)))
        config["threshold_max_usd"] = float(os.getenv("THRESHOLD_MAX_USD", config.get("threshold_max_usd", 20.0)))
        config["threshold_step_usd"] = float(os.getenv("THRESHOLD_STEP_USD", config.get("threshold_step_usd", 2.5)))
        config["order_price_offset"] = float(os.getenv("ORDER_PRICE_OFFSET", config.get("order_price_offset", 0.2)))
        config["close_ratio"] = float(os.getenv("CLOSE_RATIO", config.get("close_ratio", 40.0)))
        config["timeout_minutes"] = int(os.getenv("TIMEOUT_MINUTES", config.get("timeout_minutes", 20)))
        config["check_interval_seconds"] = int(os.getenv("CHECK_INTERVAL_SECONDS", config.get("check_interval_seconds", 60)))

        # 初始偏移量（从环境变量或config.json）
        initial_offset = config.get("initial_offset", {})
        config["initial_offset"] = {
            "SOL": float(os.getenv("INITIAL_OFFSET_SOL", initial_offset.get("SOL", 0.0))),
            "ETH": float(os.getenv("INITIAL_OFFSET_ETH", initial_offset.get("ETH", 0.0))),
            "BTC": float(os.getenv("INITIAL_OFFSET_BTC", initial_offset.get("BTC", 0.0))),
            "BONK": float(os.getenv("INITIAL_OFFSET_BONK", initial_offset.get("BONK", 0.0))),
        }

        # Exchange配置
        exchange_config = config.get("exchange", {})
        config["exchange"] = {
            "name": os.getenv("EXCHANGE_NAME", exchange_config.get("name", "mock")),
            "private_key": os.getenv("EXCHANGE_PRIVATE_KEY", exchange_config.get("private_key", "")),
            "account_index": int(os.getenv("EXCHANGE_ACCOUNT_INDEX", exchange_config.get("account_index", 0))),
            "api_key_index": int(os.getenv("EXCHANGE_API_KEY_INDEX", exchange_config.get("api_key_index", 0))),
            "base_url": os.getenv("EXCHANGE_BASE_URL", exchange_config.get("base_url", "https://mainnet.zklighter.elliot.ai")),
        }

        # Pushover配置
        pushover_config = config.get("pushover", {})
        config["pushover"] = {
            "user_key": os.getenv("PUSHOVER_USER_KEY", pushover_config.get("user_key", "")),
            "api_token": os.getenv("PUSHOVER_API_TOKEN", pushover_config.get("api_token", "")),
            "enabled": os.getenv("PUSHOVER_ENABLED", str(pushover_config.get("enabled", True))).lower() in ("true", "1", "yes"),
        }

        # RPC URL
        config["rpc_url"] = os.getenv("RPC_URL", config.get("rpc_url", "https://api.mainnet-beta.solana.com"))

        return config

    def _create_full_pipeline(self) -> HedgePipeline:
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

    def _validate_config(self):
        """验证配置完整性和合理性"""
        required_fields = ['jlp_amount', 'alp_amount', 'exchange', 'threshold_min_usd', 'threshold_max_usd']

        # 检查必要字段
        for field in required_fields:
            if field not in self.config:
                raise MissingConfigError(field)

        # 验证阈值关系
        if self.config['threshold_min_usd'] >= self.config['threshold_max_usd']:
            raise InvalidConfigError(
                'threshold_min_usd/threshold_max_usd',
                f"min={self.config['threshold_min_usd']}, max={self.config['threshold_max_usd']}",
                "threshold_min must be less than threshold_max"
            )

        # 验证close_ratio
        if not 0 < self.config['close_ratio'] <= 100:
            raise InvalidConfigError(
                'close_ratio',
                self.config['close_ratio'],
                "must be between 0 and 100"
            )

        logger.info("Configuration validated successfully")


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
