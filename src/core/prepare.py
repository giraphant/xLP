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
from typing import Dict, Any, Tuple
from datetime import datetime
from utils.offset import calculate_offset_and_cost

logger = logging.getLogger(__name__)


async def prepare_data(
    config: Dict[str, Any],
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
        "state_updates": state_updates
    }


async def _fetch_pool_data(
    config: Dict[str, Any],
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
        amount = config.get(f"{pool_type}_amount", 0)
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
    config: Dict[str, Any],
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
    initial_offset_config = config.get("initial_offset", {})

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
