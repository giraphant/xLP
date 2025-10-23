"""
数据准备模块

职责：
1. 获取池子数据（调用 pools/）
2. 获取市场数据（调用 exchanges/）
3. 计算理想对冲
4. 计算偏移和成本

返回：准备好的完整数据字典
"""
import logging
import asyncio
from typing import Dict, Any, Tuple, List
from datetime import datetime, timedelta
from utils.offset import calculate_offset_and_cost
from utils.config import HedgeConfig

logger = logging.getLogger(__name__)


async def prepare_data(
    config: HedgeConfig,
    pool_calculators: Dict[str, callable],
    exchange,
    state_manager
) -> Dict[str, Any]:
    """
    准备所有需要的数据

    Args:
        config: 配置字典
        pool_calculators: {"jlp": callable, "alp": callable}
        exchange: 交易所接口
        state_manager: 状态管理器

    Returns:
        {
            "symbols": ["SOL", "BTC", ...],
            "ideal_hedges": {"SOL": -15.7, ...},
            "positions": {"SOL": 100.5, ...},
            "prices": {"SOL": 150.0, ...},
            "offsets": {"SOL": (10.5, 148.5), ...}  # (offset, cost_basis)
        }
    """
    # 1. 获取池子数据
    pool_data = await _fetch_pool_data(config, pool_calculators)

    # 2. 计算理想对冲
    ideal_hedges = _calculate_ideal_hedges(pool_data)

    # 3. 获取市场数据
    symbols = list(ideal_hedges.keys())
    positions, prices, position_updates = await _fetch_market_data(exchange, symbols, config, state_manager)

    # 3.5 获取订单和成交状态（新增）
    order_status = await _fetch_order_status(exchange, symbols)
    fill_history = await _fetch_fill_history(exchange, symbols, config.cooldown_after_fill_minutes)

    # 4. 计算偏移和成本
    offsets, offset_updates = await _calculate_offsets(
        ideal_hedges,
        positions,
        prices,
        state_manager
    )

    # 5. 合并状态更新（不在这里更新，而是传递给 execute）
    state_updates = {}
    for symbol in symbols:
        state_updates[symbol] = {}

        # 合并 position 相关更新
        if symbol in position_updates:
            state_updates[symbol].update(position_updates[symbol])

        # 合并 offset 相关更新
        if symbol in offset_updates:
            state_updates[symbol].update(offset_updates[symbol])

    return {
        "symbols": symbols,
        "ideal_hedges": ideal_hedges,
        "positions": positions,
        "prices": prices,
        "offsets": offsets,
        "order_status": order_status,  # 新增
        "fill_history": fill_history,  # 新增
        "state_updates": state_updates
    }


async def _fetch_pool_data(
    config: HedgeConfig,
    pool_calculators: Dict[str, callable]
) -> Dict[str, Dict[str, Any]]:
    """
    并发获取所有池子数据

    依赖：pools/ (jlp, alp)
    """
    pool_data = {}

    logger.info("=" * 50)
    logger.info("📊 FETCHING POOL DATA")
    logger.info("=" * 50)

    # 并发获取所有池子数据
    tasks = {}
    for pool_type, calculator in pool_calculators.items():
        amount = getattr(config, f"{pool_type}_amount", 0)
        if amount > 0:
            logger.info(f"🏊 {pool_type.upper()} Pool: Amount = {amount:,.2f}")
            tasks[pool_type] = calculator(amount)

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
                logger.info(f"     • {symbol}: {data['amount']:,.4f}")

    logger.info(f"✅ Fetched data from {len(pool_data)} pools")
    return pool_data


def _calculate_ideal_hedges(pool_data: Dict[str, Dict[str, Any]]) -> Dict[str, float]:
    """
    计算理想对冲量（纯函数）

    策略：
    - 合并 JLP 和 ALP 池子的持仓
    - 对冲方向为负（做空对冲多头敞口）
    """
    logger.info("=" * 50)
    logger.info("🎯 CALCULATING IDEAL HEDGES")
    logger.info("=" * 50)

    merged_hedges = {}

    for pool_type, positions in pool_data.items():
        logger.info(f"📈 {pool_type.upper()} Pool Contributions:")
        for symbol, data in positions.items():
            # 初始化
            if symbol not in merged_hedges:
                merged_hedges[symbol] = 0

            # 对冲方向为负（做空）
            hedge_amount = -data["amount"]

            # 累加
            merged_hedges[symbol] += hedge_amount

            logger.info(f"  • {symbol}: {hedge_amount:+.4f} (short)")

    # 显示最终的合并结果
    logger.info("📊 MERGED IDEAL POSITIONS:")
    for symbol, amount in sorted(merged_hedges.items()):
        logger.info(f"  💹 {symbol}: {amount:+.4f}")

    return merged_hedges


async def _fetch_market_data(
    exchange,
    symbols: list,
    config: HedgeConfig,
    state_manager
) -> Tuple[Dict[str, float], Dict[str, float], Dict[str, Dict[str, Any]]]:
    """
    并发获取市场数据（价格和持仓）

    依赖：exchanges/

    Returns:
        (positions, prices, position_updates)
        - positions: 实际持仓（含初始偏移）
        - prices: 当前价格
        - position_updates: 需要更新的状态信息
    """
    logger.info("=" * 50)
    logger.info("💹 FETCHING MARKET DATA")
    logger.info("=" * 50)

    # 并发获取价格
    price_tasks = {symbol: exchange.get_price(symbol) for symbol in symbols}

    # 并发获取持仓
    position_tasks = {symbol: exchange.get_position(symbol) for symbol in symbols}

    # 等待所有任务完成
    prices_results = await asyncio.gather(*price_tasks.values(), return_exceptions=True)
    positions_results = await asyncio.gather(*position_tasks.values(), return_exceptions=True)

    # 处理价格结果
    prices = {}
    logger.info("📈 CURRENT PRICES:")
    for symbol, price in zip(price_tasks.keys(), prices_results):
        if isinstance(price, Exception):
            logger.error(f"  ❌ {symbol}: Failed to get price - {price}")
            raise price
        prices[symbol] = price
        logger.info(f"  💵 {symbol}: ${price:,.2f}")

    # 处理持仓结果
    positions = {}
    position_updates = {}
    initial_offset_config = config.get_initial_offset()

    logger.info("📊 ACTUAL POSITIONS (Exchange + Initial Offset):")
    for symbol, position in zip(position_tasks.keys(), positions_results):
        if isinstance(position, Exception):
            logger.error(f"  ❌ {symbol}: Failed to get position - {position}")
            position = 0.0

        # 检查交易所持仓是否变化（只检测，不更新）
        state = state_manager.get_symbol_state(symbol)
        old_exchange_position = state.get("exchange_position", position)  # 首次默认为当前值

        position_changed = (position != old_exchange_position)
        if position_changed:
            logger.info(f"  🔄 {symbol}: Position changed {old_exchange_position:+.4f} → {position:+.4f} (fill detected)")

        # 收集需要更新的状态（不立即更新）
        position_updates[symbol] = {
            "exchange_position": position,
            "position_changed": position_changed
        }

        # 加上初始偏移量
        initial_offset = initial_offset_config.get(symbol, 0.0)
        total_position = position + initial_offset
        positions[symbol] = total_position

        if initial_offset != 0:
            logger.info(f"  📍 {symbol}: {total_position:+.4f} "
                       f"(exchange: {position:+.4f}, initial: {initial_offset:+.4f})")
        else:
            logger.info(f"  📍 {symbol}: {total_position:+.4f}")

    logger.info(f"✅ Fetched market data for {len(symbols)} symbols")
    return positions, prices, position_updates


async def _calculate_offsets(
    ideal_hedges: Dict[str, float],
    positions: Dict[str, float],
    prices: Dict[str, float],
    state_manager
) -> Tuple[Dict[str, Tuple[float, float]], Dict[str, Dict[str, Any]]]:
    """
    计算偏移和成本（纯函数，不更新状态）

    依赖：utils/offset.py

    Returns:
        (offsets, offset_updates)
        - offsets: {symbol: (offset, cost_basis)}
        - offset_updates: 需要更新的状态信息
    """
    logger.info("=" * 50)
    logger.info("🧮 CALCULATING OFFSETS")
    logger.info("=" * 50)

    offsets = {}
    offset_updates = {}

    for symbol in ideal_hedges:
        if symbol not in prices:
            logger.warning(f"  ⚠️  {symbol}: No price data, skipping")
            continue

        # 获取旧状态（只读）
        state = state_manager.get_symbol_state(symbol)
        old_offset = state.get("offset", 0.0)
        old_cost = state.get("cost_basis", 0.0)

        # 调用纯函数计算
        offset, cost = calculate_offset_and_cost(
            ideal_hedges[symbol],
            positions.get(symbol, 0.0),
            prices[symbol],
            old_offset,
            old_cost
        )

        offsets[symbol] = (offset, cost)

        # 收集需要更新的状态（不立即更新）
        offset_updates[symbol] = {
            "offset": offset,
            "cost_basis": cost
        }

        # 日志输出
        offset_usd = abs(offset) * prices[symbol]
        direction = "LONG" if offset > 0 else ("SHORT" if offset < 0 else "BALANCED")
        logger.info(f"  • {symbol}: {direction} offset={offset:+.4f} "
                   f"(${offset_usd:.2f}) cost=${cost:.2f}")

    return offsets, offset_updates


async def _fetch_order_status(exchange, symbols: List[str]) -> Dict[str, Dict]:
    """
    获取所有币种的订单状态

    Returns:
        {
            "SOL": {
                "has_order": bool,
                "order_count": int,
                "oldest_order_time": datetime or None,
                "orders": [...]
            },
            ...
        }
    """
    logger.info("=" * 50)
    logger.info("📋 FETCHING ORDER STATUS")
    logger.info("=" * 50)

    order_status = {}

    # 批量获取所有活跃订单
    try:
        all_orders = await exchange.get_open_orders()
    except Exception as e:
        logger.error(f"Failed to fetch open orders: {e}")
        all_orders = []

    # 按币种整理订单
    for symbol in symbols:
        symbol_orders = [o for o in all_orders if o.get('symbol') == symbol]

        if symbol_orders:
            # 找到最早的订单
            oldest_order = min(symbol_orders, key=lambda x: x.get('created_at', datetime.now()))
            order_status[symbol] = {
                "has_order": True,
                "order_count": len(symbol_orders),
                "oldest_order_time": oldest_order.get('created_at'),
                "orders": symbol_orders
            }
            logger.info(f"  • {symbol}: {len(symbol_orders)} open orders, "
                       f"oldest from {oldest_order.get('created_at', 'unknown')}")
        else:
            order_status[symbol] = {
                "has_order": False,
                "order_count": 0,
                "oldest_order_time": None,
                "orders": []
            }
            logger.debug(f"  • {symbol}: No open orders")

    return order_status


async def _fetch_fill_history(exchange, symbols: List[str], cooldown_minutes: int) -> Dict[str, Dict]:
    """
    获取成交历史

    Returns:
        {
            "SOL": {
                "has_recent_fill": bool,
                "latest_fill_time": datetime or None,
                "fills": [...]
            },
            ...
        }
    """
    logger.info("=" * 50)
    logger.info("📜 FETCHING FILL HISTORY")
    logger.info("=" * 50)

    fill_history = {}

    # 获取最近的成交记录（多查询5分钟以确保覆盖）
    try:
        recent_fills = await exchange.get_recent_fills(minutes_back=cooldown_minutes + 5)
    except Exception as e:
        logger.error(f"Failed to fetch recent fills: {e}")
        recent_fills = []

    # 按币种整理成交
    for symbol in symbols:
        symbol_fills = [f for f in recent_fills if f.get('symbol') == symbol]

        if symbol_fills:
            latest_fill = max(symbol_fills, key=lambda x: x.get('filled_at', datetime.min))
            fill_history[symbol] = {
                "has_recent_fill": True,
                "latest_fill_time": latest_fill.get('filled_at'),
                "fills": symbol_fills
            }
            logger.info(f"  • {symbol}: Last fill at {latest_fill.get('filled_at', 'unknown')}")
        else:
            fill_history[symbol] = {
                "has_recent_fill": False,
                "latest_fill_time": None,
                "fills": []
            }
            logger.debug(f"  • {symbol}: No recent fills")

    return fill_history
