#!/usr/bin/env python3
"""
新架构的主入口 - 演示如何组装所有组件

对比旧架构：
- 旧: HedgeEngine(250行) + DecisionEngine(443行) + ActionExecutor(429行) = 1122行
- 新: HedgeBot(200行) + Pure Functions(415行) + Adapters(720行) = 1335行
- 但新架构100%可测试，无依赖注入开销，清晰的数据流

这个文件展示如何用"乐高"方式组装系统
"""

import asyncio
import logging
from pathlib import Path

# 配置
from utils.config import HedgeConfig

# Adapters
from adapters.exchange_client import ExchangeClient
from adapters.state_store import StateStore
from adapters.pool_fetcher import PoolFetcher

# Plugins
from plugins.audit_log import AuditLog
from plugins.metrics import MetricsCollector
from plugins.notifier import Notifier

# Orchestration
from hedge_bot import HedgeBot

# Exchange implementation (旧代码，暂时复用)
from exchanges.interface import create_exchange

# Pool calculators (旧代码，暂时复用)
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
    """
    主函数 - 展示Linus风格的"数据结构优先"架构

    关键理念：
    1. Pure functions处理所有业务逻辑（100%可测）
    2. Adapters处理所有I/O（薄封装）
    3. Plugins通过回调注入（无依赖注入框架）
    4. 主协调器只做数据流转（简单清晰）
    """
    logger.info("="*70)
    logger.info("🚀 Starting HedgeBot - Refactored Architecture")
    logger.info("="*70)

    # 加载配置
    config = HedgeConfig()
    config_dict = config.to_dict()

    # 1️⃣ 初始化底层适配器
    logger.info("📦 Initializing adapters...")

    # 交易所实现（暂时复用旧代码）
    exchange_impl = create_exchange(config_dict["exchange"])

    # Rate limiter（可选）
    rate_limiter = RateLimiter(max_tokens=10, refill_rate=1.0)

    # Exchange client（薄封装）
    exchange_client = ExchangeClient(
        exchange_impl=exchange_impl,
        rate_limiter=rate_limiter
    )

    # State store（内存存储）
    state_store = StateStore()

    # Pool fetcher（池子数据获取）
    pool_calculators = {
        "jlp": jlp.calculate_hedge,
        "alp": alp.calculate_hedge
    }
    pool_cache = PriceCache(default_ttl_seconds=60)
    pool_fetcher = PoolFetcher(
        pool_calculators=pool_calculators,
        cache=pool_cache
    )

    # 2️⃣ 初始化插件（通过回调）
    logger.info("🔌 Initializing plugins...")

    # Audit log
    audit_log = AuditLog(
        log_file="logs/audit.jsonl",
        enabled=True
    )

    # Metrics collector
    metrics = MetricsCollector()

    # Notifier（复用旧的apprise notifier）
    from notifications.apprise_notifier import Notifier as AppriseNotifier
    apprise = AppriseNotifier(config_dict["pushover"])
    notifier = Notifier(
        send_func=apprise.send,
        enabled=config_dict.get("notifications_enabled", True)
    )

    # 3️⃣ 组装主协调器
    logger.info("🤖 Initializing HedgeBot...")

    bot = HedgeBot(
        config=config_dict,
        exchange_client=exchange_client,
        state_store=state_store,
        pool_fetcher=pool_fetcher,
        # 插件回调
        on_decision=lambda **kwargs: asyncio.create_task(audit_log.log_decision(**kwargs)),
        on_action=lambda **kwargs: asyncio.gather(
            audit_log.log_action(**kwargs),
            metrics.record_action(**kwargs)
        ),
        on_error=lambda **kwargs: asyncio.gather(
            audit_log.log_error(**kwargs),
            metrics.record_error(**kwargs),
            notifier.notify_error(**kwargs)
        ),
        on_report=lambda summary: logger.info(f"📊 Summary: {summary}")
    )

    # 4️⃣ 运行对冲循环
    logger.info("▶️  Starting hedge loop...")

    try:
        # 运行一次
        summary = await bot.run_once()

        # 显示指标
        metrics_summary = await metrics.get_summary()
        logger.info(f"📈 Metrics: {metrics_summary}")

        logger.info("="*70)
        logger.info("✅ HedgeBot run completed successfully")
        logger.info("="*70)

    except Exception as e:
        logger.error(f"❌ HedgeBot run failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
