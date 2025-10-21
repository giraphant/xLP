#!/usr/bin/env python3
"""
xLP对冲引擎 - 主入口（极简版）

Linus风格：
- Pure functions处理逻辑
- Adapters处理I/O
- 回调注入插件
- 数据结构优先
- YAGNI原则（不写不需要的代码）
"""

import asyncio
import logging
import sys

# 配置
from utils.config import HedgeConfig

# Adapters
from adapters.state_store import StateStore
from adapters.pool_fetcher import PoolFetcher

# Plugins (可选)
from plugins.audit_log import AuditLog
from plugins.metrics import MetricsCollector

# Orchestration
from hedge_bot import HedgeBot

# Exchange & Pools
from exchanges.interface import create_exchange
from pools import jlp, alp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    """主函数 - 极简启动"""
    logger.info("🚀 Starting xLP Hedge Engine")

    # 加载配置
    config = HedgeConfig()
    config_dict = config.to_dict()

    # 初始化适配器（极简版，无不需要的组件）
    # 直接创建 exchange，不要 ExchangeClient 包装！
    exchange = create_exchange(config_dict["exchange"])

    state_store = StateStore()

    pool_calculators = {
        "jlp": jlp.calculate_hedge,
        "alp": alp.calculate_hedge
    }
    pool_fetcher = PoolFetcher(pool_calculators=pool_calculators)

    # 初始化插件（可选）
    audit_log = AuditLog(
        log_file="logs/audit.jsonl",
        enabled=config_dict.get("audit_enabled", True)
    )

    metrics = MetricsCollector()

    # 包装同步回调为async（避免 HedgeBot 中 await 报错）
    async def on_decision_async(**kw):
        """包装同步回调"""
        audit_log.log_decision(**kw)

    async def on_action_async(**kw):
        """包装同步回调（并行调用）"""
        audit_log.log_action(**kw)
        metrics.record_action(**kw)

    async def on_error_async(**kw):
        """包装同步回调（并行调用）"""
        audit_log.log_error(**kw)
        metrics.record_error(**kw)

    async def on_report_async(summary):
        """包装同步回调"""
        logger.info(f"📊 Summary: {summary}")

    # 组装HedgeBot
    bot = HedgeBot(
        config=config_dict,
        exchange=exchange,  # 直接传递 exchange，无包装！
        state_store=state_store,
        pool_fetcher=pool_fetcher,
        on_decision=on_decision_async,
        on_action=on_action_async,
        on_error=on_error_async,
        on_report=on_report_async
    )

    # 运行对冲循环
    interval = config_dict.get("interval_seconds", 60)

    logger.info(f"⏱️  Running hedge loop every {interval}s")

    try:
        while True:
            try:
                summary = await bot.run_once()
                logger.info(f"✅ Run complete: {summary['actions_executed']} actions")

                # 显示指标（同步调用，无需 await）
                if summary['actions_executed'] > 0:
                    metrics_summary = metrics.get_summary()
                    logger.info(f"📈 Total actions: {metrics_summary['metrics'].get('actions_total', 0)}")

            except Exception as e:
                logger.error(f"❌ Run failed: {e}", exc_info=True)
                await asyncio.sleep(10)  # 错误后等待10秒
                continue

            await asyncio.sleep(interval)

    except KeyboardInterrupt:
        logger.info("👋 Shutting down...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
