#!/usr/bin/env python3
"""
对冲引擎 - 四步架构

使用 prepare/decide/execute/report 四步流程，简洁清晰
"""

import logging
import time
from datetime import datetime
from pathlib import Path

# 导入四步核心模块
from core.prepare import prepare_data
from core.decide import decide_actions
from core.execute import execute_actions
from core.report import generate_reports

# 导入基础设施
from exchanges import create_exchange
from utils.notifier import Notifier
from utils.state_manager import StateManager
from core.exceptions import HedgeEngineError, InvalidConfigError
from utils.config import HedgeConfig, ValidationError
from utils.breakers import CircuitBreakerManager
from utils.matsu_reporter import MatsuReporter
from pools import jlp, alp

logger = logging.getLogger(__name__)


class HedgeEngine:
    """
    对冲引擎 - 四步架构

    流程：
    1. Prepare - 准备数据
    2. Decide - 做出决策
    3. Execute - 执行操作
    4. Report - 生成报告
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

        四步流程：Prepare → Decide → Execute → Report
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

            # ========== 步骤 4: 报告 ==========
            await generate_reports(
                data,
                results,
                self.state_manager,
                self.config,
                self.matsu_reporter
            )

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

    async def run_once(self):
        """执行一次检查循环 - 兼容接口"""
        return await self.run_once_pipeline()
