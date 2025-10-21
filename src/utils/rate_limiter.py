#!/usr/bin/env python3
"""
速率限制器 - Token Bucket算法

职责：
- 限制API调用频率
- 防止超过交易所限制
- 平滑流量

特点：
- Token bucket算法
- 异步锁保护
- 自动恢复tokens
"""

import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    简单的Token Bucket速率限制器 - ~50行

    可选的注入到exchange_client中
    """

    def __init__(
        self,
        max_tokens: int = 10,
        refill_rate: float = 1.0
    ):
        """
        初始化速率限制器

        Args:
            max_tokens: 最大token数量（桶容量）
            refill_rate: 每秒恢复的token数量
        """
        self.max_tokens = max_tokens
        self.tokens = max_tokens
        self.refill_rate = refill_rate
        self.last_refill = datetime.now()
        self.lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1):
        """
        获取token（阻塞直到有足够的tokens）

        Args:
            tokens: 需要的token数量
        """
        async with self.lock:
            while True:
                # 恢复tokens
                self._refill()

                # 如果有足够的tokens，消耗并返回
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    logger.debug(f"Rate limit: acquired {tokens} tokens ({self.tokens} remaining)")
                    return

                # 计算需要等待的时间
                needed = tokens - self.tokens
                wait_time = needed / self.refill_rate

                logger.debug(f"Rate limit: waiting {wait_time:.2f}s for {needed} tokens")

                # 释放锁并等待
                self.lock.release()
                await asyncio.sleep(wait_time)
                await self.lock.acquire()

    def _refill(self):
        """内部方法：恢复tokens"""
        now = datetime.now()
        elapsed = (now - self.last_refill).total_seconds()

        # 计算应该恢复的tokens
        tokens_to_add = elapsed * self.refill_rate
        self.tokens = min(self.max_tokens, self.tokens + tokens_to_add)
        self.last_refill = now

    async def try_acquire(self, tokens: int = 1) -> bool:
        """
        尝试获取token（非阻塞）

        Args:
            tokens: 需要的token数量

        Returns:
            是否成功获取
        """
        async with self.lock:
            self._refill()

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True

            return False
