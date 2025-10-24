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
from typing import Dict, Any, Tuple, List, Optional
from datetime import datetime, timedelta
from utils.calculators import calculate_offset_and_cost, calculate_zone, calculate_zone_from_orders
from utils.config import HedgeConfig

logger = logging.getLogger(__name__)


async def prepare_data(
    config: HedgeConfig,
    pool_calculators: Dict[str, callable],
    exchange,
    cost_history: Dict[str, Tuple[float, float]]
) -> Dict[str, Any]:
    """
    准备所有需要的数据（三阶段流程）

    阶段1: 数据获取 (I/O 并发)
    阶段2: 核心计算 (纯函数)
    阶段3: 数据组装

    Args:
        config: 配置字典
        pool_calculators: {"jlp": callable, "alp": callable}
        exchange: 交易所接口
        cost_history: 成本历史 {symbol: (offset, cost_basis)}

    Returns:
        {
            "symbols": ["SOL", "BTC", ...],
            "ideal_hedges": {"SOL": -15.7, ...},
            "positions": {"SOL": 100.5, ...},
            "prices": {"SOL": 150.0, ...},
            "offsets": {"SOL": (10.5, 148.5), ...}  # (offset, cost_basis)
        }
    """
    # ========== 阶段1: 数据获取 (I/O 并发) ==========
    logger.info("=" * 50)
    logger.info("🔄 STAGE 1: DATA FETCHING")
    logger.info("=" * 50)

    # 1.1 获取池子数据
    pool_data = await _fetch_pool_data(config, pool_calculators)

    # 1.2 计算理想对冲（轻量计算，用于获取 symbols）
    ideal_hedges = _calculate_ideal_hedges(pool_data)
    symbols = list(ideal_hedges.keys())

    # 1.3 获取市场数据
    positions, prices = await _fetch_market_data(exchange, symbols, config)

    # 1.4 先获取成交历史（用于计算 previous_zone）
    recent_fills = await _fetch_recent_fills(exchange, symbols, config.cooldown_after_fill_minutes)

    # 1.5 获取订单状态（传入成交历史用于计算 previous_zone）
    order_status = await _fetch_order_status(exchange, symbols, prices, recent_fills, config)

    # 1.6 从成交历史提取最后成交时间
    last_fill_times = _extract_last_fill_times(recent_fills, symbols)

    # ========== 阶段2: 核心计算 (纯函数) ==========
    logger.info("=" * 50)
    logger.info("🧮 STAGE 2: CALCULATIONS")
    logger.info("=" * 50)

    # 2.1 计算偏移和成本
    offsets = await _calculate_offsets(
        ideal_hedges,
        positions,
        prices,
        cost_history
    )

    # 2.2 计算 zones
    zones = _calculate_zones(offsets, prices, config)

    # ========== 阶段3: 数据组装 ==========
    logger.info("=" * 50)
    logger.info("📦 STAGE 3: DATA ASSEMBLY")
    logger.info("=" * 50)
    logger.info(f"✅ Prepared data for {len(symbols)} symbols: {', '.join(symbols)}")

    return {
        "symbols": symbols,
        "ideal_hedges": ideal_hedges,
        "positions": positions,
        "prices": prices,
        "offsets": offsets,
        "zones": zones,
        "order_status": order_status,
        "last_fill_times": last_fill_times
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
    config: HedgeConfig
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """
    并发获取市场数据（价格和持仓）

    依赖：exchanges/

    Returns:
        (positions, prices)
        - positions: 实际持仓（含初始偏移）
        - prices: 当前价格
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
    initial_offset_config = config.get_initial_offset()

    logger.info("📊 ACTUAL POSITIONS (Exchange + Initial Offset):")
    for symbol, position in zip(position_tasks.keys(), positions_results):
        if isinstance(position, Exception):
            logger.error(f"  ❌ {symbol}: Failed to get position - {position}")
            position = 0.0

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
    return positions, prices


async def _calculate_offsets(
    ideal_hedges: Dict[str, float],
    positions: Dict[str, float],
    prices: Dict[str, float],
    cost_history: Dict[str, Tuple[float, float]]
) -> Dict[str, Tuple[float, float]]:
    """
    计算偏移和成本（prepare 自己读写 cost_history）

    依赖：utils/offset.py

    Args:
        cost_history: {symbol: (offset, cost_basis)} - prepare 会读和写

    Returns:
        offsets: {symbol: (offset, cost_basis)}
    """
    logger.info("=" * 50)
    logger.info("🧮 CALCULATING OFFSETS")
    logger.info("=" * 50)

    offsets = {}

    for symbol in ideal_hedges:
        if symbol not in prices:
            logger.warning(f"  ⚠️  {symbol}: No price data, skipping")
            continue

        # 从 cost_history 读取历史值
        old_offset, old_cost = cost_history.get(symbol, (0.0, 0.0))

        # 调用纯函数计算
        offset, cost = calculate_offset_and_cost(
            ideal_hedges[symbol],
            positions.get(symbol, 0.0),
            prices[symbol],
            old_offset,
            old_cost
        )

        # 立即写回 cost_history（prepare 自己管理）
        cost_history[symbol] = (offset, cost)

        offsets[symbol] = (offset, cost)

        # 日志输出
        offset_usd = abs(offset) * prices[symbol]
        direction = "LONG" if offset > 0 else ("SHORT" if offset < 0 else "BALANCED")
        logger.info(f"  • {symbol}: {direction} offset={offset:+.4f} "
                   f"(${offset_usd:.2f}) cost=${cost:.2f}")

    return offsets


def _calculate_zones(
    offsets: Dict[str, Tuple[float, float]],
    prices: Dict[str, float],
    config
) -> Dict[str, Dict[str, Optional[int]]]:
    """
    计算所有 zone 信息（prepare 负责数据准备）

    Returns:
        {
            "SOL": {
                "zone": 2,  # 当前应该在的 zone
                "offset_usd": 12.5  # USD 偏移值
            },
            ...
        }
    """
    logger.info("=" * 50)
    logger.info("🎯 CALCULATING ZONES")
    logger.info("=" * 50)

    zones = {}

    for symbol, (offset, cost) in offsets.items():
        if symbol not in prices:
            continue

        # 计算 offset_usd
        offset_usd = abs(offset) * prices[symbol]

        # 计算当前 zone
        zone = calculate_zone(
            offset_usd,
            config.threshold_min_usd,
            config.threshold_max_usd,
            config.threshold_step_usd
        )

        zones[symbol] = {
            "zone": zone,
            "offset_usd": offset_usd
        }

        # 日志
        if zone is None:
            logger.info(f"  • {symbol}: Below threshold (${offset_usd:.2f})")
        elif zone == -1:
            logger.warning(f"  ⚠️  {symbol}: ALERT - Exceeded max threshold (${offset_usd:.2f})")
        else:
            logger.info(f"  • {symbol}: Zone {zone} (${offset_usd:.2f})")

    return zones


async def _fetch_order_status(
    exchange,
    symbols: List[str],
    prices: Dict[str, float],
    recent_fills: Dict[str, List[Dict]],
    config
) -> Dict[str, Dict]:
    """
    获取所有币种的订单状态并计算 previous_zone

    previous_zone 计算逻辑（优先级）：
    1. 有活跃订单 → 从订单计算 zone
    2. 冷却期内有成交 → 从最近成交计算 zone
    3. 都没有 → 0

    Returns:
        {
            "SOL": {
                "has_order": bool,
                "order_count": int,
                "oldest_order_time": datetime or None,
                "orders": [...],
                "previous_zone": int  # 注意：不再是 Optional，最小值是 0
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
        symbol_fills = recent_fills.get(symbol, [])
        price = prices.get(symbol, 0)

        # 计算 previous_zone（三优先级）
        previous_zone = 0  # 默认值

        if symbol_orders:
            # 优先级1: 有活跃订单 → 从订单计算
            previous_zone = calculate_zone_from_orders(
                symbol_orders,
                price,
                config.threshold_min_usd,
                config.threshold_step_usd,
                config.close_ratio
            )
            source = "active_order"
        elif symbol_fills:
            # 优先级2: 冷却期内有成交 → 从最近成交计算
            latest_fill = max(symbol_fills, key=lambda x: x.get('filled_at', datetime.min))
            fill_size = abs(latest_fill.get('filled_size', 0))
            fill_price = latest_fill.get('filled_price', price)
            fill_offset_usd = fill_size * fill_price

            from utils.calculators import calculate_zone
            previous_zone = calculate_zone(
                fill_offset_usd,
                config.threshold_min_usd,
                config.threshold_max_usd,
                config.threshold_step_usd
            ) or 0  # None 转为 0
            source = "recent_fill"
        else:
            # 优先级3: 都没有 → 0
            source = "default"

        if symbol_orders:
            # 有订单
            oldest_order = min(symbol_orders, key=lambda x: x.get('created_at', datetime.now()))
            order_status[symbol] = {
                "has_order": True,
                "order_count": len(symbol_orders),
                "oldest_order_time": oldest_order.get('created_at'),
                "orders": symbol_orders,
                "previous_zone": previous_zone
            }
            logger.info(f"  • {symbol}: {len(symbol_orders)} open orders, "
                       f"previous_zone={previous_zone} (from {source})")
        else:
            # 无订单
            order_status[symbol] = {
                "has_order": False,
                "order_count": 0,
                "oldest_order_time": None,
                "orders": [],
                "previous_zone": previous_zone
            }
            if previous_zone > 0:
                logger.info(f"  • {symbol}: No open orders, previous_zone={previous_zone} (from {source})")
            else:
                logger.debug(f"  • {symbol}: No open orders, previous_zone=0")

    return order_status


async def _fetch_recent_fills(exchange, symbols: List[str], cooldown_minutes: int) -> Dict[str, List[Dict]]:
    """
    获取最近成交记录（完整数据）

    Returns:
        {symbol: [fill1, fill2, ...]}
    """
    logger.info("=" * 50)
    logger.info("📜 FETCHING RECENT FILLS")
    logger.info("=" * 50)

    recent_fills = {}

    try:
        all_fills = await exchange.get_recent_fills(minutes_back=cooldown_minutes + 5)
    except Exception as e:
        logger.error(f"Failed to fetch recent fills: {e}")
        all_fills = []

    # 按币种整理成交
    for symbol in symbols:
        symbol_fills = [f for f in all_fills if f.get('symbol') == symbol]
        recent_fills[symbol] = symbol_fills

        if symbol_fills:
            logger.debug(f"  • {symbol}: {len(symbol_fills)} recent fills")
        else:
            logger.debug(f"  • {symbol}: No recent fills")

    return recent_fills


def _extract_last_fill_times(recent_fills: Dict[str, List[Dict]], symbols: List[str]) -> Dict[str, Optional[datetime]]:
    """
    从成交记录中提取最后成交时间

    Returns:
        {symbol: datetime or None}
    """
    last_fill_times = {}

    for symbol in symbols:
        symbol_fills = recent_fills.get(symbol, [])
        if symbol_fills:
            latest_fill = max(symbol_fills, key=lambda x: x.get('filled_at', datetime.min))
            last_fill_times[symbol] = latest_fill.get('filled_at')
        else:
            last_fill_times[symbol] = None

    return last_fill_times


async def _fetch_last_fill_times(exchange, symbols: List[str], cooldown_minutes: int) -> Dict[str, Optional[datetime]]:
    """
    获取最后成交时间（简化版）

    Returns:
        {symbol: datetime or None}
        例如：{"SOL": datetime(...), "BTC": None, ...}
    """
    logger.info("=" * 50)
    logger.info("📜 FETCHING LAST FILL TIMES")
    logger.info("=" * 50)

    last_fill_times = {}

    # 获取最近的成交记录（多查询5分钟以确保覆盖）
    try:
        recent_fills = await exchange.get_recent_fills(minutes_back=cooldown_minutes + 5)
    except Exception as e:
        logger.error(f"Failed to fetch recent fills: {e}")
        recent_fills = []

    # 按币种整理成交，只提取最后成交时间
    for symbol in symbols:
        symbol_fills = [f for f in recent_fills if f.get('symbol') == symbol]

        if symbol_fills:
            latest_fill = max(symbol_fills, key=lambda x: x.get('filled_at', datetime.min))
            last_fill_time = latest_fill.get('filled_at')
            last_fill_times[symbol] = last_fill_time
            logger.info(f"  • {symbol}: Last fill at {last_fill_time}")
        else:
            last_fill_times[symbol] = None
            logger.debug(f"  • {symbol}: No recent fills")

    return last_fill_times
