#!/usr/bin/env python3
"""
xLP对冲引擎 - 主入口（极简版）

Linus风格：
- Pure functions处理逻辑
- Adapters处理I/O
- 回调注入插件
- 数据结构优先
"""

import asyncio
import logging
import sys
from pathlib import Path

# 配置
from utils.config import HedgeConfig

# Adapters
from adapters.exchange_client import ExchangeClient
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

# Utils
from utils.rate_limiter import RateLimiter
from utils.price_cache import PriceCache

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    """主函数"""
    logger.info("🚀 Starting xLP Hedge Engine")

    # 加载配置
    config = HedgeConfig()
    config_dict = config.to_dict()

    # 初始化适配器
    exchange_impl = create_exchange(config_dict["exchange"])
    rate_limiter = RateLimiter(max_tokens=10, refill_rate=1.0)

    exchange_client = ExchangeClient(
        exchange_impl=exchange_impl,
        rate_limiter=rate_limiter
    )

    state_store = StateStore()

    pool_calculators = {
        "jlp": jlp.calculate_hedge,
        "alp": alp.calculate_hedge
    }
    pool_cache = PriceCache(default_ttl_seconds=60)
    pool_fetcher = PoolFetcher(
        pool_calculators=pool_calculators,
        cache=pool_cache
    )

    # 初始化插件
    audit_log = AuditLog(
        log_file="logs/audit.jsonl",
        enabled=config_dict.get("audit_enabled", True)
    )

    metrics = MetricsCollector()

    # 组装HedgeBot
    bot = HedgeBot(
        config=config_dict,
        exchange_client=exchange_client,
        state_store=state_store,
        pool_fetcher=pool_fetcher,
        on_decision=audit_log.log_decision,
        on_action=lambda **kw: asyncio.gather(
            audit_log.log_action(**kw),
            metrics.record_action(**kw)
        ),
        on_error=lambda **kw: asyncio.gather(
            audit_log.log_error(**kw),
            metrics.record_error(**kw)
        ),
        on_report=lambda summary: logger.info(f"📊 Summary: {summary}")
    )

    # 运行对冲循环
    interval = config_dict.get("interval_seconds", 60)

    logger.info(f"⏱️  Running hedge loop every {interval}s")

    try:
        while True:
            try:
                summary = await bot.run_once()
                logger.info(f"✅ Run complete: {summary['actions_executed']} actions")

                # 显示指标
                if summary['actions_executed'] > 0:
                    metrics_summary = await metrics.get_summary()
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
