"""
Pool service functions

External service calls for fetching pool data.
"""
import logging
import asyncio
from typing import Dict, Any

logger = logging.getLogger(__name__)


async def fetch_all_pool_data(
    config: Dict[str, Any],
    pool_calculators: Dict[str, callable]
) -> Dict[str, Dict[str, Any]]:
    """
    并发获取所有池子数据（外部服务调用）

    Extracted from FetchPoolDataStep

    Args:
        config: 配置字典
            {
                "jlp_amount": float,
                "alp_amount": float
            }
        pool_calculators: 池子计算器字典
            {
                "jlp": async callable,
                "alp": async callable
            }

    Returns:
        池子数据字典
            {
                "jlp": {symbol: {"amount": float}, ...},
                "alp": {symbol: {"amount": float}, ...}
            }

    Raises:
        Exception: 如果任何池子数据获取失败
    """
    pool_data = {}

    logger.info("=" * 50)
    logger.info("📊 FETCHING POOL DATA")
    logger.info("=" * 50)

    # 并发获取所有池子数据
    tasks = {}
    for pool_type, calculator in pool_calculators.items():
        amount = config.get(f"{pool_type}_amount", 0)
        if amount > 0:
            logger.info(f"🏊 {pool_type.upper()} Pool: Amount = {amount:,.2f}")
            tasks[pool_type] = calculator(amount)

    # 等待所有任务完成
    if tasks:
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        for pool_type, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                logger.error(f"❌ Failed to fetch {pool_type} data: {result}")
                raise result

            pool_data[pool_type] = result

            # 详细显示每个池子的持仓
            logger.info(f"  └─ Positions in {pool_type.upper()}:")
            for symbol, data in result.items():
                amount_value = data["amount"] if isinstance(data, dict) else data
                logger.info(f"     • {symbol}: {amount_value:,.4f}")

    logger.info(f"✅ Fetched data from {len(pool_data)} pools")
    return pool_data
