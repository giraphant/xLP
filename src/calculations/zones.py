"""
Zone calculation functions

Pure functions for calculating threshold zones based on USD offset values.
"""
from typing import Optional


def calculate_zone(
    offset_usd: float,
    min_threshold: float,
    max_threshold: float,
    step: float
) -> Optional[int]:
    """
    根据偏移USD绝对值计算所在区间

    Pure function extracted from DecisionEngine.get_zone()

    Args:
        offset_usd: 偏移USD价值（可以是正数或负数，会自动取绝对值）
        min_threshold: 最小阈值（USD）
        max_threshold: 最大阈值（USD）
        step: 区间步长（USD）

    Returns:
        None: 低于最低阈值（不需要操作）
        0-N: 区间编号（第N个区间）
        -1: 超过最高阈值（警报级别）

    Examples:
        >>> calculate_zone(3.0, 5.0, 20.0, 2.5)
        None  # Below min threshold

        >>> calculate_zone(7.5, 5.0, 20.0, 2.5)
        1  # In zone 1: (7.5 - 5.0) / 2.5 = 1

        >>> calculate_zone(25.0, 5.0, 20.0, 2.5)
        -1  # Above max threshold
    """
    abs_usd = abs(offset_usd)

    # 低于最低阈值 - 不需要操作
    if abs_usd < min_threshold:
        return None

    # 超过最高阈值 - 警报
    if abs_usd > max_threshold:
        return -1

    # 计算区间编号
    zone = int((abs_usd - min_threshold) / step)
    return zone
