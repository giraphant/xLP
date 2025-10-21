"""
Cooldown logic functions

Pure functions for analyzing cooldown status and determining appropriate actions.
"""
from datetime import datetime
from typing import Optional, Tuple, Dict, Any


def is_in_cooldown(
    last_fill_time: Optional[datetime],
    cooldown_minutes: float
) -> Tuple[bool, float]:
    """
    判断是否在冷却期内

    Pure function for cooldown detection

    Args:
        last_fill_time: 最后成交时间
        cooldown_minutes: 冷却期时长（分钟）

    Returns:
        (is_in_cooldown, remaining_minutes)

    Examples:
        >>> from datetime import datetime, timedelta
        >>> last_fill = datetime.now() - timedelta(minutes=3)
        >>> is_in_cooldown(last_fill, 5.0)
        (True, 2.0)

        >>> last_fill = datetime.now() - timedelta(minutes=6)
        >>> is_in_cooldown(last_fill, 5.0)
        (False, 0.0)
    """
    if last_fill_time is None:
        return False, 0.0

    elapsed = (datetime.now() - last_fill_time).total_seconds() / 60
    in_cooldown = elapsed < cooldown_minutes
    remaining = max(0, cooldown_minutes - elapsed)

    return in_cooldown, remaining


def analyze_cooldown_status(
    current_zone: Optional[int],
    new_zone: Optional[int],
    in_cooldown: bool,
    cooldown_remaining: float
) -> Tuple[str, str]:
    """
    分析冷却期状态并决定处理策略

    Pure function for cooldown status analysis

    Args:
        current_zone: 当前区间（订单下单时的区间）
        new_zone: 新区间（当前计算的区间）
        in_cooldown: 是否在冷却期内
        cooldown_remaining: 剩余冷却时间（分钟）

    Returns:
        (status, reason)
        - status: "normal" | "skip" | "cancel_only" | "re_order"
        - reason: 原因说明

    Status meanings:
        - normal: 正常处理（不在冷却期或zone未变化）
        - skip: 跳过操作（zone改善，等待自然回归）
        - cancel_only: 只撤单（回到阈值内）
        - re_order: 重新下单（zone恶化）

    Examples:
        >>> # Not in cooldown
        >>> analyze_cooldown_status(1, 2, False, 0)
        ('normal', 'Not in cooldown')

        >>> # In cooldown, zone worsened
        >>> analyze_cooldown_status(1, 2, True, 2.5)
        ('re_order', 'Zone worsened from 1 to 2 during cooldown')

        >>> # In cooldown, zone improved
        >>> analyze_cooldown_status(2, 1, True, 2.5)
        ('skip', 'Zone improved from 2 to 1 during cooldown, waiting (2.5min remaining)')

        >>> # In cooldown, back within threshold
        >>> analyze_cooldown_status(1, None, True, 2.5)
        ('cancel_only', 'Back within threshold during cooldown (2.5min remaining)')
    """
    if not in_cooldown:
        return "normal", "Not in cooldown"

    # 情况1: 回到阈值内 (Zone → None)
    if new_zone is None:
        return "cancel_only", f"Back within threshold during cooldown ({cooldown_remaining:.1f}min remaining)"

    # 情况2: Zone恶化 (增大)
    if current_zone is not None and new_zone is not None and new_zone > current_zone:
        return "re_order", f"Zone worsened from {current_zone} to {new_zone} during cooldown"

    # 情况3: Zone改善 (减小)
    if current_zone is not None and new_zone is not None and new_zone < current_zone:
        return "skip", f"Zone improved from {current_zone} to {new_zone} during cooldown, waiting ({cooldown_remaining:.1f}min remaining)"

    # 情况4: Zone不变或其他情况
    return "normal", f"In cooldown, monitoring ({cooldown_remaining:.1f}min remaining)"


def should_skip_action(status: str) -> bool:
    """
    判断是否应该跳过操作

    Args:
        status: analyze_cooldown_status 返回的状态

    Returns:
        是否应该跳过所有操作
    """
    return status == "skip"


def should_cancel_only(status: str) -> bool:
    """
    判断是否只需要撤单

    Args:
        status: analyze_cooldown_status 返回的状态

    Returns:
        是否只需要撤单（不下新单）
    """
    return status == "cancel_only"


def should_reorder(status: str) -> bool:
    """
    判断是否需要重新下单

    Args:
        status: analyze_cooldown_status 返回的状态

    Returns:
        是否需要撤销旧单并下新单
    """
    return status == "re_order"
