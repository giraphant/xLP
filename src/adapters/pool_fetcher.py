#!/usr/bin/env python3
"""
Pool数据获取器 - 薄封装

职责：
- 调用池子计算函数获取ideal hedges
- 合并多个池子的数据
- 可选的结果缓存

特点：
- 只做I/O操作（调用池子API）
- 无业务逻辑
- 可插拔缓存
"""

import logging
from typing import Dict, Callable, Optional, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class PoolFetcher:
    """
    Pool数据获取器 - 替代原来散落在pipeline中的池子数据获取逻辑

    简化为~60行的薄封装
    """

    def __init__(
        self,
        pool_calculators: Dict[str, Callable],
        cache: Optional[Any] = None
    ):
        """
        初始化Pool获取器

        Args:
            pool_calculators: {"jlp": jlp.calculate_hedge, "alp": alp.calculate_hedge}
            cache: 可选的缓存实例（需要有get/set方法）
        """
        self.calculators = pool_calculators
        self.cache = cache

    async def fetch_pool_hedges(
        self,
        pool_configs: Dict[str, dict]
    ) -> Dict[str, float]:
        """
        获取所有池子的ideal hedges并合并

        Args:
            pool_configs: {"jlp": {"amount": 1000}, "alp": {"amount": 500}}

        Returns:
            合并后的hedges: {"SOL": -50.5, "BTC": 0.15, ...}
        """
        all_hedges = {}

        for pool_name, config in pool_configs.items():
            # 跳过amount为0的池子
            amount = config.get("amount", 0)
            if amount == 0:
                logger.debug(f"Skipping {pool_name} (amount=0)")
                continue

            # 获取池子数据
            try:
                calculator = self.calculators.get(pool_name)
                if not calculator:
                    logger.warning(f"No calculator found for pool: {pool_name}")
                    continue

                # 调用池子计算函数
                logger.debug(f"Fetching {pool_name} hedges (amount={amount})")
                hedges = await calculator(amount)

                # 合并到总hedges中
                for symbol, hedge_amount in hedges.items():
                    all_hedges[symbol] = all_hedges.get(symbol, 0.0) + hedge_amount

                logger.info(f"✅ {pool_name}: {len(hedges)} symbols fetched")

            except Exception as e:
                logger.error(f"Failed to fetch {pool_name} hedges: {e}")
                raise

        logger.info(f"Pool hedges merged: {len(all_hedges)} symbols total")
        return all_hedges

    async def fetch_pool_data_with_cache(
        self,
        pool_configs: Dict[str, dict],
        cache_ttl_seconds: int = 60
    ) -> Dict[str, float]:
        """
        获取池子数据（带缓存）

        Args:
            pool_configs: 池子配置
            cache_ttl_seconds: 缓存TTL（秒）

        Returns:
            合并后的hedges
        """
        if not self.cache:
            # 无缓存，直接获取
            return await self.fetch_pool_hedges(pool_configs)

        # 尝试从缓存获取
        cache_key = "pool_hedges"
        cached = await self.cache.get(cache_key)

        if cached:
            cached_time = cached.get("timestamp")
            cached_data = cached.get("data")

            if cached_time and cached_data:
                age = (datetime.now() - datetime.fromisoformat(cached_time)).total_seconds()
                if age < cache_ttl_seconds:
                    logger.debug(f"Cache hit (age={age:.1f}s)")
                    return cached_data

        # 缓存未命中，重新获取
        logger.debug("Cache miss, fetching fresh data")
        hedges = await self.fetch_pool_hedges(pool_configs)

        # 写入缓存
        await self.cache.set(cache_key, {
            "timestamp": datetime.now().isoformat(),
            "data": hedges
        })

        return hedges
