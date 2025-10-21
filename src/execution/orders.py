"""
Order execution functions

Side-effect operations for executing orders with exchange.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def execute_limit_order(
    exchange,
    symbol: str,
    side: str,
    size: float,
    price: float
) -> str:
    """
    执行限价单（副作用操作）

    Extracted from ActionExecutor._execute_limit_order()

    Args:
        exchange: 交易所接口
        symbol: 币种符号
        side: 方向 (buy/sell)
        size: 数量
        price: 价格

    Returns:
        order_id

    Raises:
        Exception: 如果下单失败
    """
    logger.info(f"📤 Placing limit order: {symbol} {side} {size:.4f} @ ${price:.2f}")

    try:
        order_id = await exchange.place_limit_order(symbol, side, size, price)
        logger.info(f"✅ Limit order placed: {symbol} (ID: {order_id})")
        return order_id

    except Exception as e:
        logger.error(f"❌ Failed to place limit order for {symbol}: {e}")
        raise


async def execute_market_order(
    exchange,
    symbol: str,
    side: str,
    size: float
) -> str:
    """
    执行市价单（副作用操作）

    Extracted from ActionExecutor._execute_market_order()

    Args:
        exchange: 交易所接口
        symbol: 币种符号
        side: 方向 (buy/sell)
        size: 数量

    Returns:
        order_id

    Raises:
        Exception: 如果下单失败
    """
    logger.info(f"📤 Placing market order: {symbol} {side} {size:.4f}")

    try:
        order_id = await exchange.place_market_order(symbol, side, size)
        logger.info(f"✅ Market order placed: {symbol} (ID: {order_id})")
        return order_id

    except Exception as e:
        logger.error(f"❌ Failed to place market order for {symbol}: {e}")
        raise


async def cancel_order(
    exchange,
    symbol: str,
    order_id: str
) -> bool:
    """
    撤销订单（副作用操作）

    Extracted from ActionExecutor._execute_cancel_order()

    Args:
        exchange: 交易所接口
        symbol: 币种符号
        order_id: 订单ID

    Returns:
        是否成功撤销
    """
    logger.info(f"🚫 Canceling order: {symbol} (ID: {order_id})")

    try:
        success = await exchange.cancel_order(order_id)

        if success:
            logger.info(f"✅ Order canceled: {symbol} (ID: {order_id})")
        else:
            logger.warning(f"⚠️  Failed to cancel order: {symbol} (ID: {order_id})")

        return success

    except Exception as e:
        logger.error(f"❌ Error canceling order for {symbol}: {e}")
        # 撤单失败不抛出异常，返回 False
        return False
