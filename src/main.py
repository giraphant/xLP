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
from datetime import datetime
from hedge_engine import HedgeEngine

# 配置日志系统
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


class HedgeBot:
    """对冲机器人主类"""

    def __init__(self, config_path: str = "config.json"):
        self.engine = HedgeEngine(config_path)
        self.running = False

    async def run(self):
        """主运行循环"""
        self.running = True
        print("="*60)
        print("对冲引擎启动")
        print(f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*60)
        print()

        # 获取检查间隔
        interval = self.engine.config["check_interval_seconds"]

        try:
            while self.running:
                try:
                    await self.engine.run_once()

                    if self.running:
                        print(f"\n等待 {interval} 秒...\n")
                        await asyncio.sleep(interval)

                except Exception as e:
                    print(f"\n❌ 发生错误: {e}")
                    import traceback
                    traceback.print_exc()

                    # 错误后等待一段时间再重试
                    if self.running:
                        print(f"\n等待 {interval} 秒后重试...\n")
                        await asyncio.sleep(interval)

        except KeyboardInterrupt:
            print("\n\n收到中断信号，正在退出...")

        print("\n对冲引擎已停止")


def signal_handler(signum, frame):
    """处理SIGTERM信号（Docker/systemd停止）"""
    print("\n\n收到停止信号（SIGTERM），正在退出...")
    sys.exit(0)


async def main():
    """主函数"""
    # 只注册SIGTERM处理（SIGINT由KeyboardInterrupt处理）
    signal.signal(signal.SIGTERM, signal_handler)

    # 创建并运行机器人
    bot = HedgeBot()

    try:
        await bot.run()
    except Exception as e:
        print(f"\n❌ 致命错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
