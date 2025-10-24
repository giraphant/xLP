#!/usr/bin/env python3
"""
对冲引擎主程序
持续监控并执行对冲平仓逻辑
"""

import asyncio
import logging
import os
import traceback
from datetime import datetime
from engine import HedgeEngine
from core.exceptions import ConfigError
from utils.logger import setup_structlog

# 配置日志系统（带轮转）
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
log_file = os.getenv("LOG_FILE", "logs/hedge_engine.log")
log_retention_days = int(os.getenv("LOG_RETENTION_DAYS", "7"))

setup_structlog(
    log_level=log_level,
    log_file=log_file,
    use_json=False,  # 使用人类可读格式（如需 JSON 设置为 True）
    rotation_type="time",  # 按时间轮转
    retention_days=log_retention_days,
    enable_console=True
)


async def main():
    """主循环"""
    logger = logging.getLogger(__name__)

    # 初始化引擎
    try:
        engine = HedgeEngine()
        logger.info("对冲引擎初始化成功")
    except ConfigError as e:
        logger.critical(f"配置错误: {e}")
        logger.critical("请检查配置文件和环境变量")
        return
    except Exception as e:
        logger.error(f"初始化失败: {e}")
        traceback.print_exc()
        return

    # DRY RUN 模式醒目提示
    logger.info("=" * 70)
    if engine.config.dry_run:
        logger.warning("⚠️  ⚠️  ⚠️  DRY RUN MODE ENABLED ⚠️  ⚠️  ⚠️")
        logger.warning("⚠️  NO REAL TRADES WILL BE EXECUTED")
        logger.warning("⚠️  Set DRY_RUN=false in .env to enable real trading")
    else:
        logger.warning("🔴 🔴 🔴 REAL TRADING MODE ACTIVE 🔴 🔴 🔴")
        logger.warning("🔴 ACTUAL TRADES WILL BE EXECUTED")
        logger.warning("🔴 Make sure you understand the risks")
    logger.info("=" * 70)

    # 主循环参数
    interval = engine.config.check_interval_seconds
    error_count = 0
    max_errors = 10

    logger.info("=" * 60)
    logger.info("对冲引擎启动")
    logger.info(f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    while True:
        try:
            await engine.run_once()
            error_count = 0  # 成功执行，重置计数

            logger.info(f"等待 {interval} 秒...")
            await asyncio.sleep(interval)

        except Exception as e:
            error_count += 1
            logger.error(f"引擎错误: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")

            if error_count >= max_errors:
                logger.critical(f"连续错误 {max_errors} 次，系统停止")
                break

            await asyncio.sleep(interval)

    logger.info("对冲引擎已停止")


if __name__ == "__main__":
    asyncio.run(main())
