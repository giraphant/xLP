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
        self.apobj = Apprise()  # priority=0（默认）
        self.apobj_high = Apprise()  # priority=1（高优先级）
        self.apobj_emergency = Apprise()  # priority=2（紧急）
        self.enabled = False

        # 通知冷却：记录上次发送时间 {alert_key: timestamp}
        self._last_sent = {}
        # 不同优先级的默认冷却时间（秒）
        self._cooldown_by_priority = {
            0: 300,   # priority=0 (强制平仓等): 5 分钟
            1: 120,   # priority=1 (超阈值): 2 分钟
            2: 30     # priority=2 (Emergency): 30 秒
        }

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
                # 添加 3 个不同优先级的 Pushover 服务
                # Apprise Pushover URL 格式: pover://user@token?priority=X

                # priority=0 (默认)
                url_normal = f'pover://{user_key}@{api_token}?priority=0'
                # priority=1 (高)
                url_high = f'pover://{user_key}@{api_token}?priority=1'
                # priority=2 (紧急)
                url_emergency = f'pover://{user_key}@{api_token}?priority=2'

                result1 = self.apobj.add(url_normal)
                result2 = self.apobj_high.add(url_high)
                result3 = self.apobj_emergency.add(url_emergency)

                if result1 and result2 and result3:
                    self.enabled = True
                    logger.info("✅ Pushover notification enabled (3 priority levels)")
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
            priority: 优先级 (0=正常, 1=高, 2=紧急)
            sound: 通知声音（Pushover专用，可选）
            tag: 只发送到特定标签的服务（可选）

        Returns:
            是否发送成功
        """
        if not self.enabled:
            logger.warning(f"Notifications disabled, skipping: {title or message[:50]}")
            return False

        # 根据优先级选择对应的 Apprise 对象
        if priority >= 2:
            apobj = self.apobj_emergency  # priority=2 (紧急)
        elif priority == 1:
            apobj = self.apobj_high  # priority=1 (高)
        else:
            apobj = self.apobj  # priority=0 (默认)

        try:
            # 发送通知
            success = await apobj.async_notify(
                title=title or 'Hedge Engine',
                body=message,
                notify_type=NotifyType.INFO,  # 类型不重要，Pushover 由 URL priority 控制
                tag=tag
            )

            if success:
                logger.info(f"✅ Notification sent (priority={priority}): {title}")
            else:
                logger.error(f"❌ Notification failed: {title}")

            return success

        except Exception as e:
            logger.error(f"❌ Error sending notification: {e}", exc_info=True)
            return False

    def _should_send(self, alert_key: str, priority: int = 0) -> bool:
        """
        检查是否应该发送通知（冷却检查）

        Args:
            alert_key: 通知标识 (如 "threshold_exceeded:SOL")
            priority: 优先级 (0/1/2)

        Returns:
            是否应该发送
        """
        import time

        # 获取该优先级的冷却时间
        cooldown_seconds = self._cooldown_by_priority.get(priority, 60)

        now = time.time()
        last_sent = self._last_sent.get(alert_key, 0)

        if now - last_sent >= cooldown_seconds:
            self._last_sent[alert_key] = now
            return True
        return False

    # ==================== 通知方法 ====================

    async def alert_threshold_exceeded(self, symbol: str, offset_usd: float, offset: float, current_price: float):
        """阈值超限通知（2分钟冷却）"""
        alert_key = f"threshold_exceeded:{symbol}"

        if not self._should_send(alert_key, priority=1):
            logger.debug(f"Skipping threshold alert for {symbol} (cooling down)")
            return

        message = f"偏移 ${abs(offset_usd):.2f} ({offset:+.4f} {symbol}) @ ${current_price:.2f}"
        await self.send(
            message=message,
            title=f"⚠️ {symbol} 超过阈值",
            priority=1  # 高优先级（2分钟冷却）
        )

    async def alert_force_close(self, symbol: str, size: float, side: str):
        """强制平仓通知（5分钟冷却）"""
        alert_key = f"force_close:{symbol}"

        if not self._should_send(alert_key, priority=0):
            logger.debug(f"Skipping force close alert for {symbol} (cooling down)")
            return

        side_cn = "卖出" if side.lower() == "sell" else "买入"
        message = f"强制平仓: {side_cn} {size:.4f} {symbol} (超时未成交)"
        await self.send(
            message=message,
            title=f"⏱️ {symbol} 强制平仓",
            priority=0  # 普通优先级（5分钟冷却）
        )

    async def alert_system_error(self, message: str):
        """系统错误通知（30秒冷却）"""
        alert_key = "system_error"

        if not self._should_send(alert_key, priority=2):
            logger.debug(f"Skipping system error alert (cooling down)")
            return

        await self.send(
            message=message,
            title="🚨 System Error",
            priority=2  # Emergency（30秒冷却）
        )
