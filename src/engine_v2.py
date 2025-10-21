#!/usr/bin/env python3
"""
对冲引擎 V2 - 三步架构

使用 prepare/decide/execute 三步流程，简洁清晰
"""

import logging
import time
from datetime import datetime
from pathlib import Path

# 导入三步核心模块
from core.prepare import prepare_data
from core.decide import decide_actions
from core.execute import execute_actions

# 导入基础设施
from exchanges import create_exchange
from notifications.apprise_notifier import Notifier
from core.state_manager import StateManager
from core.exceptions import HedgeEngineError, InvalidConfigError
from utils.config import HedgeConfig, ValidationError
from utils.breakers import CircuitBreakerManager
from monitoring.prometheus_metrics import PrometheusMetrics as MetricsCollector
from monitoring.matsu_reporter import MatsuReporter
from pools import jlp, alp

logger = logging.getLogger(__name__)


class HedgeEngineV2:
    """
    对冲引擎 V2 - 三步架构

    流程：
    1. Prepare - 准备数据
    2. Decide - 做出决策
    3. Execute - 执行操作
    """

    def __init__(self, config_path: str = "config.json"):
        """初始化引擎"""
        self.config_path = Path(config_path)

        # 加载配置
        try:
            self.validated_config = HedgeConfig()
            self.config = self.validated_config.to_dict()
            logger.info(self.validated_config.get_summary())
        except ValidationError as e:
            logger.critical(f"Configuration validation failed: {e}")
            raise InvalidConfigError("config", str(e), "Valid configuration required")

        # 初始化组件
        self.state_manager = StateManager()
        self.circuit_manager = CircuitBreakerManager()
        self.metrics = MetricsCollector()
        self.exchange = create_exchange(self.config["exchange"])
        self.notifier = Notifier(self.config["pushover"])

        # 初始化Matsu监控上报器（可选）
        self.matsu_reporter = self._initialize_matsu_reporter()

        # 池子计算器
        self.pool_calculators = {
            "jlp": jlp.calculate_hedge,
            "alp": alp.calculate_hedge
        }

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

    async def run_once_pipeline(self):
        """
        执行一次完整的对冲检查循环

        三步流程：Prepare → Decide → Execute
        """
        start_time = time.time()
        logger.info(f"{'='*70}")
        logger.info(f"🚀 HEDGE ENGINE V2 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{'='*70}")

        try:
            # ========== 步骤 1: 准备数据 ==========
            data = await prepare_data(
                self.config,
                self.pool_calculators,
                self.exchange,
                self.state_manager
            )

            # ========== 步骤 2: 决策 ==========
            actions = await decide_actions(
                data,
                self.state_manager,
                self.config
            )

            # ========== 步骤 3: 执行 ==========
            results = await execute_actions(
                actions,
                self.exchange,
                self.state_manager,
                self.notifier
            )

            # ========== 步骤 4: 报告（可选） ==========
            await self._generate_reports(data, results)

            # ========== 步骤 5: Matsu上报（可选） ==========
            if self.matsu_reporter:
                await self._report_to_matsu(data)

            # 最终摘要
            duration = time.time() - start_time
            logger.info("=" * 70)
            logger.info(f"✅ CYCLE COMPLETED in {duration:.2f}s")
            logger.info("=" * 70)

        except Exception as e:
            logger.error(f"❌ Engine cycle failed: {e}")
            import traceback
            logger.error(f"Full traceback:\n{traceback.format_exc()}")
            raise HedgeEngineError(f"Engine cycle failed: {e}")

    async def _generate_reports(self, data: dict, results: list):
        """生成详细报告"""
        import os
        if os.getenv("ENABLE_DETAILED_REPORTS", "true").lower() not in ("true", "1", "yes"):
            return

        logger.info("=" * 70)
        logger.info("📊 POSITION SUMMARY")
        logger.info("=" * 70)

        total_offset_usd = 0

        for symbol in data["symbols"]:
            if symbol not in data["offsets"] or symbol not in data["prices"]:
                continue

            offset, cost_basis = data["offsets"][symbol]
            price = data["prices"][symbol]
            offset_usd = abs(offset) * price
            total_offset_usd += offset_usd

            # 获取状态
            state = await self.state_manager.get_symbol_state(symbol)
            monitoring = state.get("monitoring", {})

            status = "🔴 LONG" if offset > 0 else ("🟢 SHORT" if offset < 0 else "✅ BALANCED")

            logger.info(f"  {status} {symbol}:")
            logger.info(f"    • Offset: {offset:+.4f} (${offset_usd:.2f})")
            logger.info(f"    • Cost: ${cost_basis:.2f}")

            if monitoring.get("active"):
                logger.info(f"    • Order: {monitoring.get('order_id')} (zone {monitoring.get('current_zone')})")

        logger.info(f"  📊 Total Exposure: ${total_offset_usd:.2f}")

    async def _report_to_matsu(self, data: dict):
        """上报数据到 Matsu（可选）"""
        if not self.matsu_reporter:
            return

        try:
            hedge_data = {
                "timestamp": datetime.now().isoformat(),
                "ideal_hedges": data["ideal_hedges"],
                "positions": data["positions"],
                "prices": data["prices"],
                "offsets": {
                    symbol: {"offset": offset, "cost_basis": cost}
                    for symbol, (offset, cost) in data["offsets"].items()
                }
            }

            await self.matsu_reporter.report_hedge_data(hedge_data)
            logger.debug("✅ Reported to Matsu")

        except Exception as e:
            logger.warning(f"Failed to report to Matsu: {e}")

    async def run_once(self):
        """执行一次检查循环 - 兼容接口"""
        return await self.run_once_pipeline()
