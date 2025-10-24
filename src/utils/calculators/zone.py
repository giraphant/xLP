"""
Zone 计算函数

根据 offset USD 值计算所在的 zone 区间
"""
from typing import Optional, List, Dict


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
        None: 低于最低阈值
        0-N: 区间编号
        -1: 超过最高阈值（警报）
    """
    abs_usd = abs(offset_usd)

    if abs_usd < min_threshold:
        return None

    if abs_usd > max_threshold:
        return -1

    zone = int((abs_usd - min_threshold) / step)
    return zone


def calculate_zone_from_orders(
    orders: List[Dict],
    current_price: float,
    threshold_min: float,
    threshold_step: float,
    close_ratio: float = 40.0
) -> Optional[int]:
    """
    从订单信息反推上次下单时的 zone（无状态）

    算法：
    1. 订单 size = offset * (close_ratio / 100)
    2. offset = order_size / (close_ratio / 100)
    3. offset_usd = offset * price
    4. zone = (offset_usd - threshold_min) / threshold_step

    Args:
        orders: 订单列表 [{"size": x, "price": y}, ...]
        current_price: 当前价格（用于fallback）
        threshold_min: 最小阈值
        threshold_step: 阈值步长
        close_ratio: 平仓比例（默认40%）

    Returns:
        zone (int) 或 None（无订单）
    """
    if not orders:
        return None

    # 取第一个订单（假设同一symbol的订单zone相同）
    order = orders[0]
    order_size = abs(order.get("size", 0))
    order_price = order.get("price", current_price)

    # DEBUG: 打印订单数据
    import logging
    logger = logging.getLogger(__name__)
    logger.debug(f"[calculate_zone_from_orders] order_size={order_size}, order_price={order_price}, close_ratio={close_ratio}")

    # 从订单 size 反推 offset
    # order_size = offset * (close_ratio / 100)
    # => offset = order_size / (close_ratio / 100)
    offset = order_size / (close_ratio / 100)

    # 计算 offset USD
    offset_usd = offset * order_price

    logger.debug(f"[calculate_zone_from_orders] offset={offset}, offset_usd={offset_usd}, threshold_min={threshold_min}, threshold_step={threshold_step}")

    # 反推 zone
    zone = int((offset_usd - threshold_min) / threshold_step)

    logger.debug(f"[calculate_zone_from_orders] calculated zone={zone}, returning max(zone, 1)={max(zone, 1)}")

    return max(zone, 1)  # zone 至少为 1
