#!/usr/bin/env python3
"""
通知器 - 发送重要事件通知

职责：
- 发送错误通知
- 发送警报
- 可选的推送服务集成

特点：
- 异步发送
- 失败不影响主流程
- 可插拔通知服务
"""

import asyncio
import logging
from typing import Optional, Callable, Any

logger = logging.getLogger(__name__)


class Notifier:
    """
    通知器 - ~40行

    替代原来的Notifier，简化为回调模式
    """

    def __init__(
        self,
        send_func: Optional[Callable] = None,
        enabled: bool = True
    ):
        """
        初始化通知器

        Args:
            send_func: 实际发送通知的函数（例如apprise_notifier.send）
            enabled: 是否启用
        """
        self.send_func = send_func
        self.enabled = enabled

    async def notify_error(self, error: str, **kwargs):
        """
        发送错误通知

        Args:
            error: 错误信息
            **kwargs: 额外信息
        """
        if not self.enabled or not self.send_func:
            return

        message = f"❌ Error: {error}"
        if "symbol" in kwargs:
            message = f"❌ Error [{kwargs['symbol']}]: {error}"

        await self._send(message, **kwargs)

    async def notify_decision(self, symbol: str, decision: Any, **kwargs):
        """
        发送决策通知（仅重要决策）

        Args:
            symbol: 币种符号
            decision: 决策对象
            **kwargs: 额外信息
        """
        if not self.enabled or not self.send_func:
            return

        # 仅通知重要决策（alert, market_order）
        if decision.action in ["alert", "market_order"]:
            message = f"⚠️ {symbol}: {decision.action} - {decision.reason}"
            await self._send(message, **kwargs)

    async def _send(self, message: str, **kwargs):
        """发送通知（失败不抛异常）"""
        try:
            if asyncio.iscoroutinefunction(self.send_func):
                await self.send_func(message)
            else:
                self.send_func(message)
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
