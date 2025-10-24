"""
核心类型定义

集中定义所有 core 模块使用的数据类型和枚举
遵循原则：
- 只导入标准库
- 纯数据类型，不包含业务逻辑
- 避免循环导入
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, List
from datetime import datetime


# ========== 操作类型 ==========

class ActionType(Enum):
    """交易操作类型"""
    PLACE_LIMIT_ORDER = "place_limit_order"
    PLACE_MARKET_ORDER = "place_market_order"
    CANCEL_ORDER = "cancel_order"
    NO_ACTION = "no_action"
    ALERT = "alert"


@dataclass
class TradingAction:
    """交易操作"""
    type: ActionType
    symbol: str
    side: Optional[str] = None  # buy/sell
    size: Optional[float] = None
    price: Optional[float] = None
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


# ========== 数据结构 ==========

@dataclass
class OrderInfo:
    """订单信息"""
    has_order: bool
    order_count: int
    oldest_order_time: Optional[datetime]
    orders: List[Dict]
    previous_zone: int  # 最小值为 0


@dataclass
class ZoneInfo:
    """Zone 信息"""
    zone: Optional[int]  # None=安全区, 0-N=区间, -1=超阈值
    offset_usd: float


@dataclass
class PreparedData:
    """
    准备好的完整数据结构

    由 prepare_data() 返回，传递给 decide_actions()
    """
    symbols: List[str]
    prices: Dict[str, float]
    offsets: Dict[str, tuple]  # {symbol: (offset, cost_basis)}
    zones: Dict[str, ZoneInfo]
    order_status: Dict[str, OrderInfo]
    last_fill_times: Dict[str, Optional[datetime]]
