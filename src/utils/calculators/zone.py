"""
Zone 计算模块 - 完整的独立单元

职责：
1. 从 offset_usd 计算 zone
2. 从订单信息计算 previous_zone
3. 从成交信息计算 previous_zone
4. 提供统一的接口给外部调用
"""
from typing import Optional, List, Dict
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


# ========== 核心函数：从 offset_usd 计算 zone ==========

def calculate_zone(
    offset_usd: float,
    min_threshold: float,
    max_threshold: float,
    step: float
) -> Optional[int]:
    """
    根据偏移USD绝对值计算所在区间（纯函数）

    Args:
        offset_usd: USD 偏移值
        min_threshold: 最小阈值
        max_threshold: 最大阈值
        step: 区间步长

    Returns:
        None: 低于最低阈值（安全区）
        0-N: 区间编号
        -1: 超过最高阈值（警报）

    Examples:
        >>> calculate_zone(150, 200, 4000, 100)
        None  # 低于阈值
        >>> calculate_zone(250, 200, 4000, 100)
        0  # 第一个区间
        >>> calculate_zone(350, 200, 4000, 100)
        1  # 第二个区间
        >>> calculate_zone(4500, 200, 4000, 100)
        -1  # 超过最高阈值
    """
    abs_usd = abs(offset_usd)

    if abs_usd < min_threshold:
        return None

    if abs_usd > max_threshold:
        return -1

    zone = int((abs_usd - min_threshold) / step)
    return zone


# ========== 辅助函数：从订单计算 previous_zone ==========

def calculate_previous_zone_from_order(
    order_size: float,
    order_price: float,
    close_ratio: float,
    threshold_min: float,
    threshold_max: float,
    threshold_step: float
) -> int:
    """
    从单个订单信息反推 previous_zone

    算法：
    1. order_size = offset * (close_ratio / 100)
    2. offset = order_size / (close_ratio / 100)
    3. offset_usd = offset * order_price
    4. zone = calculate_zone(offset_usd, ...)

    Args:
        order_size: 订单大小（币数量，绝对值）
        order_price: 订单价格
        close_ratio: 平仓比例（百分比，如 20.0 表示 20%）
        threshold_min: 最小阈值
        threshold_max: 最大阈值
        threshold_step: 阈值步长

    Returns:
        zone (int)，最小值为 0

    Examples:
        >>> # 0.314 SOL @ $191, close_ratio=20%
        >>> calculate_previous_zone_from_order(0.314, 191, 20.0, 200, 4000, 100)
        1  # offset = 0.314/0.2 = 1.57, offset_usd = 1.57*191 = 300, zone = (300-200)/100 = 1
    """
    # 反推 offset
    offset = order_size / (close_ratio / 100.0)

    # 计算 offset_usd
    offset_usd = offset * order_price

    # 计算 zone
    zone = calculate_zone(offset_usd, threshold_min, threshold_max, threshold_step)

    # DEBUG
    logger.debug(f"[calculate_previous_zone_from_order] order_size={order_size:.4f}, order_price={order_price:.2f}, close_ratio={close_ratio}")
    logger.debug(f"[calculate_previous_zone_from_order] offset={offset:.4f}, offset_usd={offset_usd:.2f}")
    logger.debug(f"[calculate_previous_zone_from_order] zone={zone}")

    # zone 至少为 0（如果是 None 或 -1，说明计算有问题，返回 0 兜底）
    if zone is None or zone == -1:
        logger.warning(f"[calculate_previous_zone_from_order] Unexpected zone={zone}, returning 0")
        return 0

    return zone


# ========== 辅助函数：从成交信息计算 previous_zone ==========

def calculate_previous_zone_from_fill(
    fill_size: float,
    fill_price: float,
    close_ratio: float,
    threshold_min: float,
    threshold_max: float,
    threshold_step: float
) -> int:
    """
    从单次成交信息反推 previous_zone

    算法：与订单相同
    1. fill_size = offset * (close_ratio / 100)
    2. offset = fill_size / (close_ratio / 100)
    3. offset_usd = offset * fill_price
    4. zone = calculate_zone(offset_usd, ...)

    Args:
        fill_size: 成交大小（币数量，绝对值）
        fill_price: 成交价格
        close_ratio: 平仓比例（百分比）
        threshold_min: 最小阈值
        threshold_max: 最大阈值
        threshold_step: 阈值步长

    Returns:
        zone (int)，最小值为 0
    """
    # 反推 offset
    offset = fill_size / (close_ratio / 100.0)

    # 计算 offset_usd
    offset_usd = offset * fill_price

    # 计算 zone
    zone = calculate_zone(offset_usd, threshold_min, threshold_max, threshold_step)

    # DEBUG
    logger.debug(f"[calculate_previous_zone_from_fill] fill_size={fill_size:.4f}, fill_price={fill_price:.2f}, close_ratio={close_ratio}")
    logger.debug(f"[calculate_previous_zone_from_fill] offset={offset:.4f}, offset_usd={offset_usd:.2f}")
    logger.debug(f"[calculate_previous_zone_from_fill] zone={zone}")

    # zone 至少为 0
    if zone is None or zone == -1:
        logger.warning(f"[calculate_previous_zone_from_fill] Unexpected zone={zone}, returning 0")
        return 0

    return zone


# ========== 统一接口：计算 previous_zone（三优先级） ==========

def calculate_previous_zone(
    active_orders: List[Dict],
    recent_fills: List[Dict],
    close_ratio: float,
    threshold_min: float,
    threshold_max: float,
    threshold_step: float,
    cooldown_minutes: float
) -> int:
    """
    计算 previous_zone（三优先级算法）

    优先级：
    1. 有活跃订单 → 从订单计算
    2. 冷却期内有成交 → 从最近成交计算
    3. 都没有 → 返回 0

    Args:
        active_orders: 活跃订单列表 [{"size": x, "price": y}, ...]
        recent_fills: 最近成交列表 [{"filled_size": x, "filled_price": y, "filled_at": datetime}, ...]
        close_ratio: 平仓比例（百分比）
        threshold_min: 最小阈值
        threshold_max: 最大阈值
        threshold_step: 阈值步长
        cooldown_minutes: 冷却期时长（分钟）

    Returns:
        previous_zone (int)，最小值为 0
    """
    # 优先级1: 有活跃订单
    if active_orders:
        order = active_orders[0]
        order_size = abs(order.get("size", 0))
        order_price = order.get("price", 0)

        if order_size > 0 and order_price > 0:
            zone = calculate_previous_zone_from_order(
                order_size, order_price, close_ratio,
                threshold_min, threshold_max, threshold_step
            )
            logger.debug(f"[calculate_previous_zone] Using active order, zone={zone}")
            return zone

    # 优先级2: 冷却期内有成交
    if recent_fills:
        # 过滤冷却期内的成交
        now = datetime.now()
        cutoff_time = now - timedelta(minutes=cooldown_minutes)

        fills_in_cooldown = [
            f for f in recent_fills
            if f.get("filled_at") and f["filled_at"] > cutoff_time
        ]

        if fills_in_cooldown:
            # 取最近的成交
            latest_fill = max(fills_in_cooldown, key=lambda x: x.get("filled_at", datetime.min))
            fill_size = abs(latest_fill.get("filled_size", 0))
            fill_price = latest_fill.get("filled_price", 0)

            if fill_size > 0 and fill_price > 0:
                zone = calculate_previous_zone_from_fill(
                    fill_size, fill_price, close_ratio,
                    threshold_min, threshold_max, threshold_step
                )
                logger.debug(f"[calculate_previous_zone] Using recent fill, zone={zone}")
                return zone

    # 优先级3: 默认值
    logger.debug("[calculate_previous_zone] No orders or fills, returning 0")
    return 0
