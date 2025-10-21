"""
State update functions

Side-effect operations for updating state manager.
"""
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


async def update_order_state(
    state_manager,
    symbol: str,
    order_id: str,
    zone: int
):
    """
    更新订单监控状态（副作用操作）

    Extracted from ActionExecutor._execute_limit_order()

    Args:
        state_manager: 状态管理器
        symbol: 币种符号
        order_id: 订单ID
        zone: 区间编号
    """
    await state_manager.update_symbol_state(symbol, {
        "monitoring": {
            "active": True,
            "current_zone": zone,
            "order_id": order_id,
            "started_at": datetime.now().isoformat()
        }
    })
    logger.debug(f"✅ Updated order state for {symbol} (zone={zone}, order={order_id})")


async def update_offset_state(
    state_manager,
    symbol: str,
    offset: float,
    cost_basis: float
):
    """
    更新偏移和成本状态（副作用操作）

    Args:
        state_manager: 状态管理器
        symbol: 币种符号
        offset: 偏移量
        cost_basis: 成本基础
    """
    await state_manager.update_symbol_state(symbol, {
        "offset": offset,
        "cost_basis": cost_basis
    })
    logger.debug(f"✅ Updated offset state for {symbol} (offset={offset:.4f}, cost=${cost_basis:.2f})")


async def clear_monitoring_state(
    state_manager,
    symbol: str
):
    """
    清除监控状态（副作用操作）

    Extracted from ActionExecutor._execute_market_order() and _execute_cancel_order()

    Args:
        state_manager: 状态管理器
        symbol: 币种符号
    """
    await state_manager.update_symbol_state(symbol, {
        "monitoring": {
            "active": False,
            "started_at": None,
            "order_id": None
            # current_zone 保留用于 cooldown 判断
        }
    })
    logger.debug(f"✅ Cleared monitoring state for {symbol}")


async def update_fill_time(
    state_manager,
    symbol: str,
    fill_time: Optional[datetime] = None
):
    """
    更新最后成交时间（副作用操作）

    Args:
        state_manager: 状态管理器
        symbol: 币种符号
        fill_time: 成交时间（默认为当前时间）
    """
    if fill_time is None:
        fill_time = datetime.now()

    await state_manager.update_symbol_state(symbol, {
        "last_fill_time": fill_time.isoformat()
    })
    logger.debug(f"✅ Updated fill time for {symbol}")
