#!/usr/bin/env python3
"""
统一通知器 - 使用 Apprise 支持 80+ 种通知服务
替代手写的 pushover.py (153行 → ~80行)
"""

import logging
from typing import Optional
from apprise import Apprise, NotifyType

logger = logging.getLogger(__name__)


class Notifier:
    """
    统一通知器 - 支持多种通知服务

    使用 Apprise 库，支持 80+ 种通知服务：
    - Pushover, Pushbullet
    - Telegram, Discord, Slack
    - Email (Gmail, Outlook, etc.)
    - SMS (Twilio, AWS SNS)
    - Webhook
    - 等等...

    兼容旧的 Pushover Notifier API
    """

    def __init__(self, config: dict):
        """
        Args:
            config: 通知配置
                {
                    "pushover": {
                        "user_key": "...",
                        "api_token": "...",
                        "enabled": true
                    },
                    "telegram": {  # 可选
                        "bot_token": "...",
                        "chat_id": "...",
                        "enabled": false
                    },
                    "email": {  # 可选
                        "smtp_server": "smtp.gmail.com",
                        "username": "...",
                        "password": "...",
                        "to": "...",
                        "enabled": false
                    }
                }
        """
        self.config = config
        self.apobj = Apprise()
        self.enabled = False

        # 加载所有启用的通知服务
        self._load_services()

    def _load_services(self):
        """加载所有启用的通知服务"""

        # Pushover（config 直接就是 pushover 配置）
        pushover_config = self.config
        if pushover_config.get("enabled", False):
            user_key = pushover_config.get("user_key", "")
            api_token = pushover_config.get("api_token", "")

            if user_key and api_token:
                # Apprise Pushover URL 格式: pover://user@token
                url = f'pover://{user_key}@{api_token}'
                result = self.apobj.add(url)

                if result:
                    self.enabled = True
                    logger.info("✅ Pushover notification enabled")
                else:
                    logger.error("❌ Failed to add Pushover service")
            else:
                logger.warning("Pushover enabled but credentials not provided")

        # Telegram (可选)
        telegram_config = self.config.get("telegram", {})
        if telegram_config.get("enabled", False):
            bot_token = telegram_config.get("bot_token", "")
            chat_id = telegram_config.get("chat_id", "")

            if bot_token and chat_id:
                # Apprise Telegram URL 格式: tgram://bottoken/ChatID
                self.apobj.add(f'tgram://{bot_token}/{chat_id}')
                self.enabled = True
                logger.info("Telegram notification enabled")

        # Email (可选)
        email_config = self.config.get("email", {})
        if email_config.get("enabled", False):
            smtp_server = email_config.get("smtp_server", "smtp.gmail.com")
            username = email_config.get("username", "")
            password = email_config.get("password", "")
            to_email = email_config.get("to", "")

            if username and password and to_email:
                # Apprise Email URL 格式: mailto://user:password@server/?to=recipient
                self.apobj.add(
                    f'mailto://{username}:{password}@{smtp_server}?to={to_email}'
                )
                self.enabled = True
                logger.info("Email notification enabled")

        # Discord (可选)
        discord_config = self.config.get("discord", {})
        if discord_config.get("enabled", False):
            webhook_url = discord_config.get("webhook_url", "")
            if webhook_url:
                # Discord webhook
                self.apobj.add(webhook_url)
                self.enabled = True
                logger.info("Discord notification enabled")

        # Slack (可选)
        slack_config = self.config.get("slack", {})
        if slack_config.get("enabled", False):
            webhook_url = slack_config.get("webhook_url", "")
            if webhook_url:
                # Slack webhook
                self.apobj.add(webhook_url)
                self.enabled = True
                logger.info("Slack notification enabled")

        # 自定义 Webhook (可选)
        webhook_config = self.config.get("webhook", {})
        if webhook_config.get("enabled", False):
            url = webhook_config.get("url", "")
            if url:
                # Generic webhook: json://hostname/path
                self.apobj.add(f'json://{url}')
                self.enabled = True
                logger.info("Custom webhook notification enabled")

        if not self.enabled:
            logger.info("No notification services enabled")

    async def send(
        self,
        message: str,
        title: Optional[str] = None,
        priority: int = 0,
        sound: Optional[str] = None,
        tag: Optional[str] = None
    ) -> bool:
        """
        发送通知到所有启用的服务

        Args:
            message: 消息内容
            title: 标题（可选）
            priority: 优先级 (-2到2, 0=正常, 1=高, 2=紧急)
            sound: 通知声音（Pushover专用，可选）
            tag: 只发送到特定标签的服务（可选）

        Returns:
            是否发送成功
        """
        if not self.enabled:
            logger.warning(f"Notifications disabled, skipping: {title or message[:50]}")
            return False

        # 映射优先级到 NotifyType
        notify_type = self._priority_to_notify_type(priority)

        try:
            # 发送通知
            success = await self.apobj.async_notify(
                title=title or 'Hedge Engine',
                body=message,
                notify_type=notify_type,
                tag=tag  # 只发送到特定服务
            )

            if success:
                logger.info(f"✅ Notification sent: {title}")
            else:
                logger.error(f"❌ Notification failed: {title}")

            return success

        except Exception as e:
            logger.error(f"❌ Error sending notification: {e}", exc_info=True)
            return False

    def _priority_to_notify_type(self, priority: int) -> NotifyType:
        """将优先级映射到 NotifyType"""
        if priority >= 2:
            return NotifyType.FAILURE  # 紧急/错误（红色）
        elif priority == 1:
            return NotifyType.WARNING  # 警告（黄色）
        elif priority <= -1:
            return NotifyType.INFO     # 信息（蓝色）
        else:
            return NotifyType.SUCCESS  # 正常（绿色）

    # ==================== 便捷方法 ====================

    async def alert_success(self, symbol: str, message: str):
        """发送成功通知"""
        await self.send(
            message=message,
            title=f"✅ {symbol} Success",
            priority=0
        )

    async def alert_warning(self, symbol: str, message: str):
        """发送警告通知"""
        await self.send(
            message=message,
            title=f"⚠️ {symbol} Warning",
            priority=1
        )

    async def alert_error(self, symbol: str, message: str):
        """发送错误通知"""
        await self.send(
            message=message,
            title=f"🚨 {symbol} Error",
            priority=2
        )

    async def alert_order_placed(self, symbol: str, side: str, quantity: float, price: float):
        """订单下单通知"""
        message = f"Order placed: {side.upper()} {quantity} {symbol} @ ${price:.2f}"
        await self.send(
            message=message,
            title=f"📝 {symbol} Order",
            priority=0
        )

    async def alert_order_filled(self, symbol: str, side: str, quantity: float, price: float):
        """订单成交通知"""
        message = f"Order filled: {side.upper()} {quantity} {symbol} @ ${price:.2f}"
        await self.send(
            message=message,
            title=f"✅ {symbol} Filled",
            priority=0
        )

    async def alert_order_cancelled(self, symbol: str, reason: str):
        """订单取消通知"""
        message = f"Order cancelled: {reason}"
        await self.send(
            message=message,
            title=f"❌ {symbol} Cancelled",
            priority=1
        )

    async def alert_threshold_exceeded(self, symbol: str, offset_usd: float, offset: float, current_price: float):
        """阈值超限通知"""
        message = f"偏移 ${abs(offset_usd):.2f} ({offset:+.4f} {symbol}) @ ${current_price:.2f}"
        await self.send(
            message=message,
            title=f"⚠️ {symbol} 超过阈值",
            priority=1
        )

    async def alert_force_close(self, symbol: str, size: float, side: str):
        """强制平仓通知"""
        side_cn = "卖出" if side.lower() == "sell" else "买入"
        message = f"强制平仓: {side_cn} {size:.4f} {symbol} (超时未成交)"
        await self.send(
            message=message,
            title=f"🚨 {symbol} 强制平仓",
            priority=2
        )

    async def alert_system_error(self, message: str):
        """系统错误通知"""
        await self.send(
            message=message,
            title="🚨 System Error",
            priority=2
        )
