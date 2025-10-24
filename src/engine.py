#!/usr/bin/env python3
"""
对冲引擎 - 四步架构

使用 prepare/decide/execute/report 四步流程，简洁清晰
"""

import logging
import time
import traceback
from datetime import datetime

# 导入四步核心模块
from core.prepare import prepare_data
from core.decide import decide_actions
from core.execute import execute_actions
from core.report import generate_reports

# 导入基础设施
from exchanges import create_exchange
from utils.notifier import Notifier
from core.exceptions import HedgeEngineError, InvalidConfigError
from utils.config import HedgeConfig, ValidationError
from utils.matsu import MatsuReporter
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

    def __init__(self):
        """初始化引擎（配置从环境变量读取）"""
        # 加载配置
        try:
            self.config = HedgeConfig()
            logger.info(self.config.get_summary())
        except ValidationError as e:
            logger.critical(f"Configuration validation failed: {e}")
            raise InvalidConfigError("config", str(e), "Valid configuration required")

        # 初始化组件（exchange/notifier 需要 dict 格式）
        config_dict = self.config.to_dict()
        self.exchange = create_exchange(config_dict["exchange"])
        self.notifier = Notifier(config_dict["pushover"])

        # 初始化Matsu监控上报器（可选）
        self.matsu_reporter = self._initialize_matsu_reporter()

        # 池子计算器
        self.pool_calculators = {
            "jlp": jlp.calculate_hedge,
            "alp": alp.calculate_hedge
        }

        # 极简状态存储（仅cost_basis用于加权平均）
        self.cost_history = {}  # {symbol: (offset, cost_basis)}

    def _initialize_matsu_reporter(self):
        """初始化Matsu监控上报器（可选）"""
        if not self.config.matsu_enabled:
            logger.debug("Matsu reporter disabled")
            return None

        if not self.config.matsu_auth_token:
            logger.warning("Matsu reporter enabled but auth_token is empty")
            return None

        try:
            reporter = MatsuReporter(
                api_url=self.config.matsu_api_endpoint,
                auth_token=self.config.matsu_auth_token,
                pool_name=self.config.matsu_pool_name
            )
            logger.info(f"✅ Matsu reporter enabled: {self.config.matsu_pool_name}")
            return reporter
        except Exception as e:
            logger.error(f"Failed to initialize Matsu reporter: {e}")
            return None

    async def run_once(self):
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
                self.cost_history  # prepare 会读写 cost_history
            )

            # ========== 步骤 2: 决策（完全无状态）==========
            actions = await decide_actions(
                data,
                self.config
            )

            # ========== 步骤 3: 执行 ==========
            results = await execute_actions(
                actions,
                self.exchange,
                self.notifier,
                self.config
            )

            # ========== 步骤 4: 报告 ==========
            await generate_reports(
                data,
                results,
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
            logger.error(f"Full traceback:\n{traceback.format_exc()}")

            # 发送系统错误警报
            try:
                await self.notifier.alert_system_error(f"引擎错误: {e}")
            except Exception as notify_err:
                logger.error(f"Failed to send alert: {notify_err}")

            raise HedgeEngineError(f"Engine cycle failed: {e}")
