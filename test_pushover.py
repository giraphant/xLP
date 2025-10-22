#!/usr/bin/env python3
"""
Pushover 通知测试脚本
快速测试 Apprise + Pushover 是否工作
"""

import asyncio
import logging
from apprise import Apprise, NotifyType

# 设置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

# 启用 Apprise 调试
apprise_logger = logging.getLogger('apprise')
apprise_logger.setLevel(logging.DEBUG)

logger = logging.getLogger(__name__)


async def test_pushover():
    """测试 Pushover 通知"""

    # 用户凭据
    user_key = "uzdgypdww7obcie5nsvvnkx1gwdww7"
    api_token = "aifotexgo5qvcww4xzdxkoyz8wb2hh"

    logger.info("=" * 60)
    logger.info("Testing Pushover Notification")
    logger.info("=" * 60)
    logger.info(f"User Key: {user_key[:4]}...{user_key[-4:]}")
    logger.info(f"API Token: {api_token[:4]}...{api_token[-4:]}")

    # 创建 Apprise 对象
    apobj = Apprise()

    # 测试不同的 URL 格式
    url_formats = [
        f"pover://{user_key}@{api_token}",
        f"pover://{api_token}@{user_key}",  # 尝试反过来
        f"pover://{user_key}/{api_token}",
        f"pushover://{user_key}@{api_token}",
    ]

    for i, url in enumerate(url_formats, 1):
        logger.info(f"\n{'=' * 60}")
        logger.info(f"测试 #{i}: {url[:20]}...")
        logger.info(f"{'=' * 60}")

        # 清空之前的服务
        apobj.clear()

        # 添加服务
        result = apobj.add(url)
        logger.info(f"apobj.add() returned: {result}")

        if not result:
            logger.error("URL 格式不被接受，跳过")
            continue

        logger.info(f"Services configured: {len(apobj)}")

        # 尝试发送通知
        try:
            logger.info("发送测试通知...")
            success = await apobj.async_notify(
                title="🧪 测试通知",
                body=f"测试 Pushover 格式 #{i}",
                notify_type=NotifyType.INFO
            )

            if success:
                logger.info("✅ 通知发送成功！")
                logger.info(f"成功的 URL 格式: {url[:20]}...")
                return True
            else:
                logger.error("❌ 通知发送失败")

        except Exception as e:
            logger.error(f"发送异常: {e}", exc_info=True)

    logger.error("\n所有格式都失败了")
    return False


if __name__ == "__main__":
    success = asyncio.run(test_pushover())
    exit(0 if success else 1)
