#!/usr/bin/env python3
"""
Pool数据获取器 - 极简薄封装

职责：
- 调用池子计算函数获取ideal hedges
- 合并多个池子的数据

特点：
- 只做I/O操作（调用池子API）
- 无业务逻辑
- 无缓存（YAGNI原则）
"""

import logging
from typing import Dict, Callable

logger = logging.getLogger(__name__)


class PoolFetcher:
    """
    Pool数据获取器 - 极简版本

    替代原来散落在pipeline中的池子数据获取逻辑（~40行）
    """

    def __init__(self, pool_calculators: Dict[str, Callable]):
        """
        初始化Pool获取器

        Args:
            pool_calculators: {"jlp": jlp.calculate_hedge, "alp": alp.calculate_hedge}
        """
        self.calculators = pool_calculators

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
                for symbol, hedge_data in hedges.items():
                    # 提取amount字段（池子返回的是嵌套结构）
                    amount = hedge_data["amount"] if isinstance(hedge_data, dict) else hedge_data

                    # 累加对冲量（负数表示做空）
                    hedge_amount = -amount
                    all_hedges[symbol] = all_hedges.get(symbol, 0.0) + hedge_amount

                logger.info(f"✅ {pool_name}: {len(hedges)} symbols fetched")

            except Exception as e:
                logger.error(f"Failed to fetch {pool_name} hedges: {e}")
                raise

        logger.info(f"Pool hedges merged: {len(all_hedges)} symbols total")
        return all_hedges
