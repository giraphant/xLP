"""
Exchange service functions

External service calls for fetching market data from exchange.
"""
import logging
import asyncio
from typing import Dict, List, Tuple, Any

logger = logging.getLogger(__name__)


async def fetch_market_data(
    exchange,
    symbols: List[str],
    config: Dict[str, Any] = None
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """
    并发获取市场数据（价格和持仓）

    Extracted from FetchMarketDataStep

    Args:
        exchange: 交易所接口
        symbols: 币种列表
        config: 配置字典（可选）
            {
                "initial_offset": {
                    "SOL": 0.0,
                    "BTC": 0.0,
                    ...
                }
            }

    Returns:
        (positions, prices)
        - positions: {symbol: position_amount}
        - prices: {symbol: price}

    Raises:
        Exception: 如果关键数据获取失败
    """
    if config is None:
        config = {}

    logger.info("=" * 50)
    logger.info("💹 FETCHING MARKET DATA")
    logger.info("=" * 50)

    # 并发获取价格
    price_tasks = {
        symbol: exchange.get_price(symbol)
        for symbol in symbols
    }

    # 并发获取持仓
    position_tasks = {
        symbol: exchange.get_position(symbol)
        for symbol in symbols
    }

    # 等待所有任务完成
    prices_results = await asyncio.gather(*price_tasks.values(), return_exceptions=True)
    positions_results = await asyncio.gather(*position_tasks.values(), return_exceptions=True)

    # 处理价格结果
    prices = {}
    logger.info("📈 CURRENT PRICES:")
    for symbol, price in zip(price_tasks.keys(), prices_results):
        if isinstance(price, Exception):
            logger.error(f"  ❌ {symbol}: Failed to get price - {price}")
            # 价格获取失败是严重问题，抛出异常
            raise price
        else:
            prices[symbol] = price
            logger.info(f"  💵 {symbol}: ${price:,.2f}")

    # 处理持仓结果
    positions = {}
    initial_offset_config = config.get("initial_offset", {})

    logger.info("📊 ACTUAL POSITIONS (Exchange + Initial Offset):")
    for symbol, position in zip(position_tasks.keys(), positions_results):
        if isinstance(position, Exception):
            logger.error(f"  ❌ {symbol}: Failed to get position - {position}")
            position = 0.0  # 默认为0

        # 加上初始偏移量（如果配置了）
        initial_offset = initial_offset_config.get(symbol, 0.0)
        total_position = position + initial_offset

        positions[symbol] = total_position

        if initial_offset != 0:
            logger.info(f"  📍 {symbol}: {total_position:+.4f} "
                       f"(exchange: {position:+.4f}, initial: {initial_offset:+.4f})")
        else:
            logger.info(f"  📍 {symbol}: {total_position:+.4f}")

    logger.info(f"✅ Fetched market data for {len(symbols)} symbols")

    return positions, prices


async def get_recent_fills(
    exchange,
    symbol: str,
    minutes: int = 5
) -> List[Dict[str, Any]]:
    """
    获取最近的成交记录

    用于无状态冷却期检测（未来实现）

    Args:
        exchange: 交易所接口
        symbol: 币种符号
        minutes: 查询最近N分钟的成交

    Returns:
        成交记录列表
            [
                {
                    "order_id": str,
                    "time": datetime,
                    "size": float,
                    "price": float
                },
                ...
            ]
    """
    # TODO: 需要在 ExchangeInterface 中实现此方法
    # 这里先返回空列表
    logger.debug(f"Getting recent fills for {symbol} (last {minutes} minutes)")
    return []
