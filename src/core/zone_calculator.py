#!/usr/bin/env python3
"""
Zone计算器 - 纯函数

根据偏移USD值计算所在的Zone编号。
零依赖，100%可测试。
"""


def calculate_zone(
    offset_usd: float,
    threshold_min: float,
    threshold_max: float,
    threshold_step: float
) -> int | None:
    """
    根据偏移USD绝对值计算所在区间

    Args:
        offset_usd: 偏移USD价值（可以是正数或负数）
        threshold_min: 最小阈值 (例如: 5.0)
        threshold_max: 最大阈值 (例如: 20.0)
        threshold_step: 区间步长 (例如: 2.5)

    Returns:
        None: 偏移在最小阈值内，无需操作
        0-N: Zone编号 (0表示刚超过最小阈值, N表示接近最大阈值)
        -1: 超过最大阈值，需要警报

    Examples:
        >>> calculate_zone(3.0, 5.0, 20.0, 2.5)
        None  # 3.0 < 5.0, within threshold

        >>> calculate_zone(6.5, 5.0, 20.0, 2.5)
        0  # (6.5 - 5.0) / 2.5 = 0.6 -> zone 0

        >>> calculate_zone(10.0, 5.0, 20.0, 2.5)
        2  # (10.0 - 5.0) / 2.5 = 2.0 -> zone 2

        >>> calculate_zone(25.0, 5.0, 20.0, 2.5)
        -1  # 25.0 > 20.0, exceeded max threshold
    """
    # 使用绝对值（支持正负偏移）
    abs_usd = abs(offset_usd)

    # 情况1: 在最小阈值内
    if abs_usd < threshold_min:
        return None

    # 情况2: 超过最大阈值
    if abs_usd > threshold_max:
        return -1

    # 情况3: 计算zone编号
    # 例如: offset_usd=10, min=5, step=2.5
    # zone = (10 - 5) / 2.5 = 2
    zone = int((abs_usd - threshold_min) / threshold_step)

    return zone


def get_zone_range(
    zone: int,
    threshold_min: float,
    threshold_step: float
) -> tuple[float, float]:
    """
    获取指定zone的USD范围

    Args:
        zone: Zone编号
        threshold_min: 最小阈值
        threshold_step: 区间步长

    Returns:
        (range_start, range_end): Zone的USD范围

    Examples:
        >>> get_zone_range(0, 5.0, 2.5)
        (5.0, 7.5)

        >>> get_zone_range(2, 5.0, 2.5)
        (10.0, 12.5)
    """
    if zone < 0:
        raise ValueError(f"Invalid zone: {zone} (must be non-negative)")

    range_start = threshold_min + zone * threshold_step
    range_end = range_start + threshold_step

    return (range_start, range_end)
