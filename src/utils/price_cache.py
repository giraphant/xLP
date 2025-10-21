#!/usr/bin/env python3
"""
价格缓存 - 简单的TTL缓存

职责：
- 缓存价格数据（或任何数据）
- 自动过期机制
- 线程安全

特点：
- 内存缓存
- TTL自动清理
- 异步锁保护
"""

import asyncio
import logging
from typing import Any, Optional
from datetime import datetime, timedelta
from copy import deepcopy

logger = logging.getLogger(__name__)


class PriceCache:
    """
    简单的TTL缓存 - ~40行

    替代原来散落在各处的缓存逻辑
    """

    def __init__(self, default_ttl_seconds: int = 60):
        """
        初始化缓存

        Args:
            default_ttl_seconds: 默认TTL（秒）
        """
        self.data = {}
        self.lock = asyncio.Lock()
        self.default_ttl = default_ttl_seconds

    async def get(self, key: str) -> Optional[Any]:
        """
        获取缓存数据

        Args:
            key: 键

        Returns:
            数据（如果未过期），否则None
        """
        async with self.lock:
            if key not in self.data:
                return None

            entry = self.data[key]
            expires_at = entry["expires_at"]

            # 检查是否过期
            if datetime.now() > expires_at:
                del self.data[key]
                logger.debug(f"Cache expired: {key}")
                return None

            logger.debug(f"Cache hit: {key}")
            return deepcopy(entry["value"])

    async def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None):
        """
        设置缓存数据

        Args:
            key: 键
            value: 值
            ttl_seconds: TTL（秒），如果为None则使用默认值
        """
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        expires_at = datetime.now() + timedelta(seconds=ttl)

        async with self.lock:
            self.data[key] = {
                "value": deepcopy(value),
                "expires_at": expires_at
            }
            logger.debug(f"Cache set: {key} (TTL={ttl}s)")

    async def clear(self):
        """清空所有缓存"""
        async with self.lock:
            count = len(self.data)
            self.data.clear()
            logger.info(f"Cache cleared: {count} entries removed")

    async def cleanup_expired(self):
        """清理所有过期条目"""
        async with self.lock:
            now = datetime.now()
            expired_keys = [
                key for key, entry in self.data.items()
                if now > entry["expires_at"]
            ]

            for key in expired_keys:
                del self.data[key]

            if expired_keys:
                logger.debug(f"Cleaned up {len(expired_keys)} expired entries")
