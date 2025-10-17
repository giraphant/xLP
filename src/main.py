#!/usr/bin/env python3
"""
对冲引擎主程序
持续监控并执行对冲平仓逻辑
"""

import asyncio
import signal
import sys
from datetime import datetime
from hedge_engine import HedgeEngine


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

        while self.running:
            try:
                await self.engine.run_once()

                if self.running:
                    print(f"\n等待 {interval} 秒...\n")
                    await asyncio.sleep(interval)

            except KeyboardInterrupt:
                print("\n\n收到中断信号，正在退出...")
                self.running = False
                break

            except Exception as e:
                print(f"\n❌ 发生错误: {e}")
                import traceback
                traceback.print_exc()

                # 错误后等待一段时间再重试
                if self.running:
                    print(f"\n等待 {interval} 秒后重试...\n")
                    await asyncio.sleep(interval)

        print("\n对冲引擎已停止")

    def stop(self):
        """停止运行"""
        self.running = False


def signal_handler(signum, frame):
    """处理信号"""
    print("\n\n收到停止信号，正在退出...")
    sys.exit(0)


async def main():
    """主函数"""
    # 注册信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 创建并运行机器人
    bot = HedgeBot()

    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\n\n程序已停止")
    except Exception as e:
        print(f"\n❌ 致命错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序已停止")
        sys.exit(0)
