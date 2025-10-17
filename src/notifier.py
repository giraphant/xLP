#!/usr/bin/env python3
"""
通知模块 - Pushover集成
"""

import httpx
from typing import Optional


class Notifier:
    """Pushover通知类"""

    PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"

    def __init__(self, config: dict):
        """
        Args:
            config: Pushover配置
                {
                    "user_key": "...",
                    "api_token": "...",
                    "enabled": true
                }
        """
        self.config = config
        self.enabled = config.get("enabled", False)
        self.user_key = config.get("user_key", "")
        self.api_token = config.get("api_token", "")

    async def send(
        self,
        message: str,
        title: Optional[str] = None,
        priority: int = 0,
        sound: Optional[str] = None
    ) -> bool:
        """
        发送Pushover通知

        Args:
            message: 消息内容
            title: 标题（可选）
            priority: 优先级 (-2到2, 0=正常, 1=高, 2=紧急)
            sound: 通知声音（可选）

        Returns:
            是否发送成功
        """
        if not self.enabled:
            print(f"[Notifier] 通知已禁用: {title or 'Notification'}")
            return False

        if not self.user_key or not self.api_token:
            print("[Notifier] 错误: Pushover配置不完整")
            return False

        payload = {
            "token": self.api_token,
            "user": self.user_key,
            "message": message,
        }

        if title:
            payload["title"] = title
        if priority != 0:
            payload["priority"] = priority
        if sound:
            payload["sound"] = sound

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.PUSHOVER_API_URL, data=payload)

                if response.status_code == 200:
                    print(f"[Notifier] ✓ 通知已发送: {title or message[:50]}")
                    return True
                else:
                    print(f"[Notifier] ✗ 发送失败: {response.status_code} - {response.text}")
                    return False

        except Exception as e:
            print(f"[Notifier] ✗ 发送异常: {e}")
            return False

    async def alert_threshold_exceeded(
        self,
        symbol: str,
        offset_pct: float,
        offset: float,
        price: float
    ):
        """发送阈值超限警报"""
        title = f"⚠️ 对冲偏移超限警报"
        message = (
            f"币种: {symbol}\n"
            f"偏移: {offset:.4f} ({offset_pct:.2f}%)\n"
            f"价格: ${price:.2f}\n"
            f"偏移USD: ${abs(offset) * price:,.2f}"
        )
        await self.send(message, title=title, priority=1, sound="siren")

    async def alert_force_close(
        self,
        symbol: str,
        size: float,
        side: str
    ):
        """发送强制平仓通知"""
        title = f"🔄 强制平仓执行"
        message = (
            f"币种: {symbol}\n"
            f"操作: {side.upper()}\n"
            f"数量: {size:.4f}\n"
            f"原因: 挂单超时未成交"
        )
        await self.send(message, title=title, priority=0)

    async def alert_order_placed(
        self,
        symbol: str,
        side: str,
        size: float,
        price: float
    ):
        """发送挂单通知（可选，避免过多通知）"""
        title = f"📝 对冲订单已挂出"
        message = (
            f"币种: {symbol}\n"
            f"操作: {side.upper()}\n"
            f"数量: {size:.4f}\n"
            f"价格: ${price:.2f}"
        )
        await self.send(message, title=title, priority=-1)


async def test_notifier():
    """测试通知功能"""
    config = {
        "user_key": "",  # 填入你的user key
        "api_token": "",  # 填入你的api token
        "enabled": True
    }

    notifier = Notifier(config)
    await notifier.send("这是一条测试消息", title="测试通知")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_notifier())
