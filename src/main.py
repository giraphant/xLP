#!/usr/bin/env python3
"""
对冲引擎主程序
持续监控并执行对冲平仓逻辑
"""

import asyncio
import signal
import sys
import logging
import os
import json
import traceback
from datetime import datetime
from pathlib import Path
from engine import HedgeEngine
from core.exceptions import (
    HedgeEngineError,
    RecoverableError,
    CriticalError,
    ConfigError,
    classify_exception,
    should_retry,
    get_retry_delay
)
from utils.breakers import CircuitOpenError
from utils.structlog_config import setup_structlog
from tenacity import (
    AsyncRetrying,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)

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


class HedgeBot:
    """对冲机器人主类（增强错误处理）"""

    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.engine = None
        self.running = False
        self.error_count = 0
        self.max_consecutive_errors = 10
        self.logger = logging.getLogger(__name__)

    async def initialize(self):
        """初始化引擎（可能失败）"""
        try:
            self.engine = HedgeEngine(self.config_path)
            self.logger.info("对冲引擎初始化成功")
            self.error_count = 0  # 重置错误计数
        except ConfigError as e:
            self.logger.critical(f"配置错误: {e}")
            raise
        except Exception as e:
            self.logger.error(f"初始化失败: {e}")
            raise

    async def run(self):
        """主运行循环（增强错误处理）"""
        self.running = True
        self.logger.info("="*60)
        self.logger.info("对冲引擎启动")
        self.logger.info(f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info("="*60)

        # 初始化引擎
        if not self.engine:
            await self.initialize()

        # 获取检查间隔
        interval = self.engine.config["check_interval_seconds"]
        retry_attempt = 0

        try:
            while self.running:
                try:
                    # 执行一次检查
                    await asyncio.wait_for(
                        self.engine.run_once(),
                        timeout=interval * 2  # 设置超时为间隔的2倍
                    )

                    # 成功执行，重置计数器
                    self.error_count = 0
                    retry_attempt = 0

                    if self.running:
                        self.logger.info(f"等待 {interval} 秒...")
                        await asyncio.sleep(interval)

                except asyncio.TimeoutError:
                    self.logger.error("引擎执行超时")
                    self.error_count += 1

                except CircuitOpenError as e:
                    # 熔断器开启，等待更长时间
                    self.logger.warning(f"熔断器开启: {e}")
                    if e.retry_after:
                        await asyncio.sleep(e.retry_after)
                    else:
                        await asyncio.sleep(interval * 2)

                except CriticalError as e:
                    # 严重错误，立即停止
                    self.logger.critical(f"严重错误: {e}")
                    self.logger.critical("系统将立即停止")
                    self.running = False
                    break

                except RecoverableError as e:
                    # 可恢复错误，使用 Tenacity 自动重试（指数退避）
                    self.logger.warning(f"可恢复错误: {e}")

                    # 使用 Tenacity 进行重试
                    try:
                        async for attempt in AsyncRetrying(
                            stop=stop_after_attempt(e.max_retries),
                            wait=wait_exponential(min=1, max=60),
                            before_sleep=before_sleep_log(self.logger, logging.INFO)
                        ):
                            with attempt:
                                await self.engine.run_once()
                                self.error_count = 0  # 重试成功，重置错误计数
                    except Exception:
                        self.logger.error(f"重试失败: {e}")
                        self.error_count += 1
                        await asyncio.sleep(interval)

                except HedgeEngineError as e:
                    # 其他对冲引擎错误
                    self.error_count += 1
                    self.logger.error(f"对冲引擎错误: {e}")

                    if e.should_notify and self.engine:
                        try:
                            await self.engine.notifier.alert_error("System", str(e))
                        except:
                            pass

                    retry_delay = e.retry_after if e.retry_after else interval
                    self.logger.info(f"等待 {retry_delay} 秒后重试...")
                    await asyncio.sleep(retry_delay)

                except Exception as e:
                    # 未分类的错误，尝试分类
                    classified_error = classify_exception(e)
                    self.logger.error(f"未预期的错误 ({classified_error.__class__.__name__}): {e}")
                    self.error_count += 1

                    if self.running:
                        await asyncio.sleep(interval)

                # 检查连续错误次数
                if self.error_count >= self.max_consecutive_errors:
                    self.logger.critical(f"连续错误次数达到上限 ({self.max_consecutive_errors})，系统停止")
                    self.running = False
                    break

        except KeyboardInterrupt:
            self.logger.info("\n收到中断信号，正在退出...")

        finally:
            await self.shutdown()

    async def shutdown(self):
        """优雅关闭"""
        self.logger.info("正在执行优雅关闭...")
        self.running = False

        if self.engine:
            try:
                # 显示熔断器状态
                breaker_stats = self.engine.circuit_manager.get_all_stats()
                if breaker_stats:
                    self.logger.info("熔断器最终状态:")
                    for name, stats in breaker_stats.items():
                        self.logger.info(f"  {name}: {stats['state']} (失败: {stats['failure_count']})")

            except Exception as e:
                self.logger.error(f"关闭时出错: {e}")

        self.logger.info("对冲引擎已停止")


def signal_handler(signum, frame):
    """处理SIGTERM信号（Docker/systemd停止）"""
    print("\n\n收到停止信号（SIGTERM），正在退出...")
    sys.exit(0)


async def main():
    """主函数（增强错误处理）"""
    logger = logging.getLogger(__name__)

    # 只注册SIGTERM处理（SIGINT由KeyboardInterrupt处理）
    signal.signal(signal.SIGTERM, signal_handler)

    # 创建机器人
    bot = HedgeBot()

    try:
        # 尝试初始化
        await bot.initialize()

        # 运行主循环
        await bot.run()

    except ConfigError as e:
        logger.critical(f"配置错误，无法启动: {e}")
        logger.critical("请检查配置文件和环境变量")
        sys.exit(2)

    except CriticalError as e:
        logger.critical(f"严重错误: {e}")
        logger.critical("系统处于不一致状态，需要人工介入")
        sys.exit(3)

    except Exception as e:
        logger.error(f"未预期的致命错误: {e}")
        traceback.print_exc()
        sys.exit(1)

    # 正常退出
    logger.info("程序正常退出")
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
