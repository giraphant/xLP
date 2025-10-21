# xLP Hedge Engine 重构方案 v4.0

**编写日期：** 2025-10-21
**状态：** 规划中
**目标：** 函数式、无状态、原子化架构

---

## 📋 目录

1. [当前问题总结](#1-当前问题总结)
2. [重构目标](#2-重构目标)
3. [核心原则](#3-核心原则)
4. [保留 vs 重构](#4-保留-vs-重构)
5. [分阶段执行计划](#5-分阶段执行计划)
6. [风险控制](#6-风险控制)
7. [验收标准](#7-验收标准)

---

## 1. 当前问题总结

### 1.1 架构问题

| 问题 | 现状 | 影响 |
|------|------|------|
| **Pipeline 耦合** | HedgePipeline 直接依赖 DecisionEngine/ActionExecutor | 难以单元测试 |
| **类过多** | 14个 Step 类，每个都是有状态的类 | 代码冗长，难以理解 |
| **状态管理混乱** | StateManager 存储了可以计算的状态 | 重启后状态丢失导致逻辑错误 |
| **冷却期实现复杂** | 依赖 last_fill_time + last_actual_position | 需要持久化，容易出错 |

### 1.2 可维护性问题

```
src/core/pipeline.py         - 1063 行 (太大！)
src/core/decision_engine.py  - 442 行
src/core/action_executor.py  - 428 行
```

**问题：**
- 单个文件过大，难以定位逻辑
- 类内部方法众多，职责不清晰
- 测试困难，需要 mock 大量依赖

### 1.3 用户之前的失败经验

**失败次数：** 3-4 次
**失败原因分析：**
1. **步子太大** - 一次性重构所有模块
2. **缺少验证** - 没有每一步的测试验证
3. **状态丢失** - 重构后关键状态逻辑缺失
4. **模块边界不清** - 不知道哪些必须保留

---

## 2. 重构目标

### 2.1 核心目标

```
✅ 函数式架构 - 计算逻辑全部提取为纯函数
✅ 最小化状态 - 只保留必要的状态（offset, cost_basis, monitoring）
✅ 无状态查询 - 能从交易所查询的就不存储
✅ 原子化函数 - 每个函数只做一件事
✅ 易于测试 - 纯函数无需 mock
```

### 2.2 目录结构目标

```
src/
├── calculations/           # 纯计算函数（无副作用）
│   ├── offset.py          # calculate_offset_and_cost() ← 已有
│   ├── zones.py           # calculate_zone()
│   ├── orders.py          # calculate_order_size(), calculate_order_price()
│   └── hedges.py          # calculate_ideal_hedges()
│
├── decisions/             # 决策逻辑（只读状态）
│   ├── actions.py         # decide_action() - 核心决策
│   └── cooldown.py        # analyze_cooldown_status()
│
├── execution/             # 副作用操作
│   ├── orders.py          # execute_limit_order(), execute_market_order()
│   ├── state.py           # update_offset_state(), update_order_state()
│   └── notifications.py   # send_alert()
│
├── services/              # 外部服务调用
│   ├── pool_service.py    # fetch_pool_data()
│   └── exchange_service.py # fetch_market_data()
│
├── core/                  # 保留的核心（最小化）
│   ├── state_manager.py   # 状态管理（简化）
│   └── exceptions.py      # 异常定义（保留）
│
├── engine.py              # 简化的引擎（编排函数调用）
└── main.py                # 主循环（保留）
```

---

## 3. 核心原则

### 3.1 函数式原则

```python
# ✅ 好的例子：纯函数
def calculate_zone(offset_usd: float, min_usd: float, max_usd: float, step: float) -> Optional[int]:
    """输入 → 输出，无副作用"""
    if offset_usd < min_usd:
        return None
    if offset_usd > max_usd:
        return -1
    return int((offset_usd - min_usd) / step)

# ❌ 坏的例子：有状态
class CalculateZonesStep:
    def __init__(self, config):
        self.config = config  # 依赖注入

    async def execute(self, context):
        # 修改 context（副作用）
        context.zones = {...}
```

### 3.2 状态最小化原则

**必须存储的状态（无法从外部查询）：**

```python
{
    "offset": 10.5,                    # ✅ 必须 - 加权成本计算需要
    "cost_basis": 148.50,              # ✅ 必须 - 加权成本基础
    "monitoring": {                    # ✅ 必须 - 订单追踪
        "active": True,
        "order_id": "order_123",
        "zone": 2,
        "started_at": "2025-10-21T10:00:00"
    }
}
```

**可以从交易所查询的（不存储）：**

```python
# ❌ 不存储 last_fill_time
# ✅ 改为查询 exchange.get_recent_fills(symbol, minutes=5)

# ❌ 不存储 last_actual_position
# ✅ 改为查询 exchange.get_position(symbol)
```

### 3.3 单一职责原则

```python
# ✅ 每个函数只做一件事
def calculate_close_size(offset: float, close_ratio: float) -> float:
    """计算平仓数量"""
    return abs(offset) * (close_ratio / 100.0)

def calculate_limit_price(offset: float, cost_basis: float, price_offset_pct: float) -> float:
    """计算限价单价格"""
    if offset > 0:  # LONG 敞口，需要卖出
        return cost_basis * (1 + price_offset_pct / 100)
    else:  # SHORT 敞口，需要买入
        return cost_basis * (1 - price_offset_pct / 100)
```

---

## 4. 保留 vs 重构

### 4.1 完全保留（不修改）

| 模块 | 理由 |
|------|------|
| `src/core/offset_tracker.py` | ✅ 已经是完美的纯函数 |
| `src/core/exceptions.py` | ✅ 异常定义，无需改动 |
| `src/core/state_manager.py` | ✅ 只需简化，不需要重写 |
| `src/exchanges/*` | ✅ 已经模块化完成（90f9034） |
| `src/pools/*` | ✅ 池子计算器，功能独立 |
| `src/notifications/*` | ✅ 通知系统，功能独立 |
| `src/monitoring/*` | ✅ 监控系统，功能独立 |
| `src/main.py` | ✅ 主循环和错误处理，保持稳定 |

### 4.2 需要重构（拆分为纯函数）

| 模块 | 当前状态 | 重构目标 |
|------|---------|---------|
| `src/core/pipeline.py` (1063行) | 14个 Step 类 | → 拆分为独立的纯函数 |
| `src/core/decision_engine.py` (442行) | DecisionEngine 类 | → decisions/actions.py (纯函数) |
| `src/core/action_executor.py` (428行) | ActionExecutor 类 | → execution/orders.py (分离副作用) |
| `src/hedge_engine.py` | 依赖 Pipeline 类 | → 简化为函数编排 |

### 4.3 新增模块

| 模块 | 用途 | 示例函数 |
|------|------|---------|
| `calculations/zones.py` | 区间计算 | `calculate_zone()` |
| `calculations/orders.py` | 订单计算 | `calculate_close_size()`, `calculate_limit_price()` |
| `calculations/hedges.py` | 对冲计算 | `calculate_ideal_hedges()` |
| `decisions/cooldown.py` | 冷却期决策 | `is_in_cooldown()`, `analyze_cooldown_status()` |
| `services/pool_service.py` | 池子服务 | `fetch_all_pool_data()` |
| `services/exchange_service.py` | 交易所服务 | `fetch_market_data()` |

---

## 5. 分阶段执行计划

### 阶段 0：准备工作（1天）

**目标：** 创建测试基础，确保重构可验证

```bash
# 1. 创建测试文件
tests/
├── test_calculations.py
├── test_decisions.py
├── test_execution.py
└── integration/
    └── test_full_cycle.py

# 2. 编写关键路径的集成测试
# 测试当前系统的完整周期，作为回归基准
```

**验收标准：**
- ✅ 至少 3 个集成测试覆盖主要流程
- ✅ 所有测试通过（基于当前代码）

---

### 阶段 1：提取计算函数（2天）⭐ 最安全

**目标：** 将纯计算逻辑提取到 `calculations/`，但**不删除原代码**

**步骤 1.1：创建 calculations/zones.py**

```python
# src/calculations/zones.py
def calculate_zone(
    offset_usd: float,
    min_threshold: float,
    max_threshold: float,
    step: float
) -> Optional[int]:
    """
    从 DecisionEngine.get_zone() 提取

    Returns:
        None: offset < min_threshold (不操作)
        0-N: 在第 N 区间
        -1: 超过 max_threshold (警报)
    """
    if offset_usd < min_threshold:
        return None
    if offset_usd > max_threshold:
        return -1
    return int((offset_usd - min_threshold) / step)
```

**步骤 1.2：创建 calculations/orders.py**

```python
# src/calculations/orders.py
def calculate_close_size(offset: float, close_ratio: float) -> float:
    """计算平仓数量"""
    return abs(offset) * (close_ratio / 100.0)

def calculate_limit_price(
    offset: float,
    cost_basis: float,
    price_offset_percent: float
) -> float:
    """计算限价单价格"""
    if offset > 0:
        return cost_basis * (1 + price_offset_percent / 100)
    else:
        return cost_basis * (1 - price_offset_percent / 100)
```

**步骤 1.3：创建 calculations/hedges.py**

```python
# src/calculations/hedges.py
def calculate_ideal_hedges(pool_data: Dict[str, Dict[str, Any]]) -> Dict[str, float]:
    """
    从 CalculateIdealHedgesStep 提取

    合并 JLP + ALP，规范化符号，返回理想对冲量
    """
    merged = {}
    for pool_type, positions in pool_data.items():
        for symbol, data in positions.items():
            # WBTC → BTC
            exchange_symbol = "BTC" if symbol == "WBTC" else symbol

            # 提取数量
            amount = data["amount"] if isinstance(data, dict) else data

            # 反向 (做空对冲)
            hedge_amount = -amount

            merged[exchange_symbol] = merged.get(exchange_symbol, 0) + hedge_amount

    return merged
```

**步骤 1.4：编写单元测试**

```python
# tests/test_calculations.py
def test_calculate_zone():
    assert calculate_zone(3.0, 5.0, 20.0, 2.5) is None
    assert calculate_zone(7.5, 5.0, 20.0, 2.5) == 1
    assert calculate_zone(25.0, 5.0, 20.0, 2.5) == -1

def test_calculate_close_size():
    assert calculate_close_size(10.0, 40.0) == 4.0
    assert calculate_close_size(-5.0, 100.0) == 5.0
```

**验收标准：**
- ✅ 所有新函数有单元测试
- ✅ 测试覆盖率 > 90%
- ✅ **原代码保持不变，系统正常运行**

---

### 阶段 2：提取决策逻辑（2天）

**目标：** 将决策逻辑提取到 `decisions/`

**步骤 2.1：创建 decisions/actions.py**

```python
# src/decisions/actions.py
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

class ActionType(Enum):
    PLACE_LIMIT_ORDER = "place_limit_order"
    PLACE_MARKET_ORDER = "place_market_order"
    CANCEL_ORDER = "cancel_order"
    NO_ACTION = "no_action"
    ALERT = "alert"

@dataclass
class TradingAction:
    type: ActionType
    symbol: str
    side: Optional[str] = None
    size: Optional[float] = None
    price: Optional[float] = None
    order_id: Optional[str] = None
    reason: str = ""
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

def decide_action(
    symbol: str,
    offset: float,
    cost_basis: float,
    current_price: float,
    zone: Optional[int],
    state: Dict[str, Any],
    config: Dict[str, Any]
) -> List[TradingAction]:
    """
    核心决策函数：根据当前状态决定需要执行的操作

    从 DecisionEngine.decide() 提取，完全是纯函数

    Args:
        symbol: 币种符号
        offset: 偏移量
        cost_basis: 成本基础
        current_price: 当前价格
        zone: 区间编号
        state: 币种状态（只读）
        config: 配置（只读）

    Returns:
        操作列表
    """
    actions = []

    # 1. 检查是否超过最大阈值
    if zone == -1:
        # 撤销订单 + 警报
        if state.get("monitoring", {}).get("order_id"):
            actions.append(TradingAction(
                type=ActionType.CANCEL_ORDER,
                symbol=symbol,
                order_id=state["monitoring"]["order_id"],
                reason="Exceeded max threshold"
            ))

        actions.append(TradingAction(
            type=ActionType.ALERT,
            symbol=symbol,
            reason=f"Threshold exceeded: ${abs(offset) * current_price:.2f}",
            metadata={"alert_type": "threshold_exceeded"}
        ))
        return actions

    # 2. 检查是否超时
    timeout_action = _check_timeout(symbol, offset, cost_basis, state, config)
    if timeout_action:
        return timeout_action

    # 3. 在阈值内
    if zone is None:
        if state.get("monitoring", {}).get("order_id"):
            actions.append(TradingAction(
                type=ActionType.CANCEL_ORDER,
                symbol=symbol,
                order_id=state["monitoring"]["order_id"],
                reason="Back within threshold"
            ))

        actions.append(TradingAction(
            type=ActionType.NO_ACTION,
            symbol=symbol,
            reason="Within threshold"
        ))
        return actions

    # 4. 超出阈值，需要下单
    from ..calculations.orders import calculate_close_size, calculate_limit_price

    close_size = calculate_close_size(offset, config.get("close_ratio", 40.0))
    side = "sell" if offset > 0 else "buy"
    limit_price = calculate_limit_price(
        offset, cost_basis, config.get("order_price_offset", 0.2)
    )

    # 如果已有订单，先撤销
    if state.get("monitoring", {}).get("order_id"):
        actions.append(TradingAction(
            type=ActionType.CANCEL_ORDER,
            symbol=symbol,
            order_id=state["monitoring"]["order_id"],
            reason=f"Zone changed to {zone}, re-ordering"
        ))

    # 下新订单
    actions.append(TradingAction(
        type=ActionType.PLACE_LIMIT_ORDER,
        symbol=symbol,
        side=side,
        size=close_size,
        price=limit_price,
        reason=f"Close offset in zone {zone}",
        metadata={"zone": zone, "offset": offset, "cost_basis": cost_basis}
    ))

    return actions

def _check_timeout(
    symbol: str,
    offset: float,
    cost_basis: float,
    state: Dict[str, Any],
    config: Dict[str, Any]
) -> Optional[List[TradingAction]]:
    """检查订单是否超时"""
    from datetime import datetime

    monitoring = state.get("monitoring", {})
    if not monitoring.get("active"):
        return None

    started_at = monitoring.get("started_at")
    if not started_at:
        return None

    elapsed_minutes = (datetime.now() - datetime.fromisoformat(started_at)).total_seconds() / 60
    timeout_minutes = config.get("timeout_minutes", 20)

    if elapsed_minutes < timeout_minutes:
        return None

    # 超时，强制市价平仓
    actions = []

    if monitoring.get("order_id"):
        actions.append(TradingAction(
            type=ActionType.CANCEL_ORDER,
            symbol=symbol,
            order_id=monitoring["order_id"],
            reason=f"Timeout after {elapsed_minutes:.1f} minutes"
        ))

    from ..calculations.orders import calculate_close_size

    close_size = calculate_close_size(offset, 100.0)  # 全部平仓
    side = "sell" if offset > 0 else "buy"

    actions.append(TradingAction(
        type=ActionType.PLACE_MARKET_ORDER,
        symbol=symbol,
        side=side,
        size=close_size,
        reason="Force close due to timeout",
        metadata={"force_close": True, "timeout_minutes": elapsed_minutes}
    ))

    return actions
```

**步骤 2.2：创建 decisions/cooldown.py**

```python
# src/decisions/cooldown.py
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

def is_in_cooldown(
    last_fill_time: Optional[datetime],
    cooldown_minutes: float
) -> Tuple[bool, float]:
    """
    判断是否在冷却期

    Returns:
        (is_in_cooldown, remaining_minutes)
    """
    if last_fill_time is None:
        return False, 0

    elapsed = (datetime.now() - last_fill_time).total_seconds() / 60
    in_cooldown = elapsed < cooldown_minutes
    remaining = max(0, cooldown_minutes - elapsed)

    return in_cooldown, remaining

def analyze_cooldown_status(
    state: Dict[str, Any],
    old_zone: Optional[int],
    new_zone: Optional[int],
    cooldown_minutes: float
) -> Tuple[str, str]:
    """
    分析冷却期状态

    Returns:
        (status, reason)
        - status: "normal" | "skip" | "cancel_only" | "re_order"
        - reason: 原因说明
    """
    last_fill_time = state.get("last_fill_time")
    in_cooldown, remaining = is_in_cooldown(last_fill_time, cooldown_minutes)

    if not in_cooldown:
        return "normal", "Not in cooldown"

    current_zone = state.get("monitoring", {}).get("zone")

    # 回到阈值内
    if new_zone is None:
        return "cancel_only", f"Back within threshold during cooldown ({remaining:.1f}min)"

    # 区间恶化
    if current_zone is not None and new_zone > current_zone:
        return "re_order", f"Zone worsened from {current_zone} to {new_zone}"

    # 区间改善或不变
    if current_zone is not None and new_zone <= current_zone:
        return "skip", f"Zone improved/stable, waiting ({remaining:.1f}min)"

    return "normal", "In cooldown, monitoring"

def should_skip_action(status: str) -> bool:
    """是否应该跳过操作"""
    return status == "skip"

def should_cancel_only(status: str) -> bool:
    """是否只需撤单"""
    return status == "cancel_only"
```

**验收标准：**
- ✅ 所有决策函数都是纯函数
- ✅ 单元测试覆盖 > 90%
- ✅ **原 DecisionEngine 保持不变，系统正常运行**

---

### 阶段 3：提取执行和服务层（2天）

**目标：** 分离副作用操作和外部服务调用

**步骤 3.1：创建 execution/orders.py**

```python
# src/execution/orders.py
import logging
from typing import Optional

logger = logging.getLogger(__name__)

async def execute_limit_order(
    exchange,
    symbol: str,
    side: str,
    size: float,
    price: float
) -> str:
    """
    执行限价单（副作用操作）

    Returns:
        order_id
    """
    logger.info(f"Placing limit order: {side} {size} {symbol} @ ${price:.2f}")

    order_id = await exchange.place_limit_order(symbol, side, size, price)

    logger.info(f"✅ Order placed: {order_id}")
    return order_id

async def execute_market_order(
    exchange,
    symbol: str,
    side: str,
    size: float
) -> str:
    """执行市价单"""
    logger.info(f"Placing market order: {side} {size} {symbol}")

    order_id = await exchange.place_market_order(symbol, side, size)

    logger.info(f"✅ Market order placed: {order_id}")
    return order_id

async def cancel_order(
    exchange,
    symbol: str,
    order_id: str
) -> bool:
    """撤销订单"""
    logger.info(f"Canceling order: {order_id} for {symbol}")

    success = await exchange.cancel_order(order_id)

    if success:
        logger.info(f"✅ Order canceled: {order_id}")
    else:
        logger.warning(f"❌ Failed to cancel order: {order_id}")

    return success
```

**步骤 3.2：创建 execution/state.py**

```python
# src/execution/state.py
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

async def update_order_state(
    state_manager,
    symbol: str,
    order_id: str,
    zone: int
):
    """更新订单监控状态"""
    await state_manager.update_symbol_state(symbol, {
        "monitoring": {
            "active": True,
            "order_id": order_id,
            "zone": zone,
            "started_at": datetime.now().isoformat()
        }
    })
    logger.debug(f"Updated order state for {symbol}")

async def update_offset_state(
    state_manager,
    symbol: str,
    offset: float,
    cost_basis: float
):
    """更新偏移和成本状态"""
    await state_manager.update_symbol_state(symbol, {
        "offset": offset,
        "cost_basis": cost_basis
    })
    logger.debug(f"Updated offset state for {symbol}")

async def clear_monitoring_state(
    state_manager,
    symbol: str
):
    """清除监控状态"""
    await state_manager.update_symbol_state(symbol, {
        "monitoring": {
            "active": False,
            "order_id": None
        }
    })
```

**步骤 3.3：创建 services/pool_service.py**

```python
# src/services/pool_service.py
from typing import Dict, Any
import asyncio

async def fetch_all_pool_data(
    config: Dict[str, Any],
    pool_calculators: Dict[str, callable]
) -> Dict[str, Dict[str, Any]]:
    """
    并发获取所有池子数据

    Returns:
        {
            "jlp": {symbol: amount, ...},
            "alp": {symbol: amount, ...}
        }
    """
    tasks = {}

    if config.get("jlp_amount", 0) > 0:
        tasks["jlp"] = pool_calculators["jlp"](config["jlp_amount"])

    if config.get("alp_amount", 0) > 0:
        tasks["alp"] = pool_calculators["alp"](config["alp_amount"])

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    pool_data = {}
    for pool_name, result in zip(tasks.keys(), results):
        if isinstance(result, Exception):
            raise result
        pool_data[pool_name] = result

    return pool_data
```

**验收标准：**
- ✅ 副作用操作都在 execution/ 下
- ✅ 外部调用都在 services/ 下
- ✅ 测试验证功能正确

---

### 阶段 4：创建新引擎（3天）⭐ 关键步骤

**目标：** 创建基于纯函数的新引擎，与旧引擎并存

**步骤 4.1：创建 src/engine_v2.py**

```python
# src/engine_v2.py
"""
新版对冲引擎 - 函数式架构
与旧版 hedge_engine.py 并存，逐步迁移
"""
import asyncio
import logging
from typing import Dict, Any

# 导入纯函数
from calculations.offset import calculate_offset_and_cost
from calculations.zones import calculate_zone
from calculations.hedges import calculate_ideal_hedges
from decisions.actions import decide_action, ActionType
from decisions.cooldown import analyze_cooldown_status, should_skip_action, should_cancel_only

# 导入副作用操作
from execution.orders import execute_limit_order, execute_market_order, cancel_order
from execution.state import update_order_state, update_offset_state, clear_monitoring_state

# 导入服务层
from services.pool_service import fetch_all_pool_data
from services.exchange_service import fetch_market_data

logger = logging.getLogger(__name__)

class HedgeEngineV2:
    """新版对冲引擎 - 纯函数编排"""

    def __init__(self, config: Dict[str, Any]):
        # 最小化依赖，只保留必要的组件
        self.config = config
        self.state_manager = ...  # 简化的状态管理器
        self.exchange = ...
        self.notifier = ...
        self.pool_calculators = {
            "jlp": jlp.calculate_hedge,
            "alp": alp.calculate_hedge
        }

    async def run_once(self):
        """
        执行一次检查周期 - 纯函数组合
        """
        logger.info("=" * 70)
        logger.info("🚀 HEDGE ENGINE V2 - Starting cycle")
        logger.info("=" * 70)

        # 1. 获取池子数据
        pool_data = await fetch_all_pool_data(self.config, self.pool_calculators)

        # 2. 计算理想对冲（纯函数）
        ideal_hedges = calculate_ideal_hedges(pool_data)
        logger.info(f"Ideal hedges: {ideal_hedges}")

        # 3. 获取市场数据
        positions, prices = await fetch_market_data(
            self.exchange,
            list(ideal_hedges.keys())
        )

        # 4. 计算偏移（纯函数 + 状态更新）
        offsets = await self._calculate_offsets(ideal_hedges, positions, prices)

        # 5. 决策（纯函数）
        actions = await self._decide_actions(offsets, prices)

        # 6. 执行（副作用）
        results = await self._execute_actions(actions)

        logger.info("=" * 70)
        logger.info(f"✅ Cycle completed: {len(results)} actions executed")
        logger.info("=" * 70)

    async def _calculate_offsets(self, ideal_hedges, positions, prices):
        """计算偏移（调用纯函数）"""
        offsets = {}

        for symbol in ideal_hedges:
            if symbol not in prices:
                continue

            # 获取旧状态
            state = await self.state_manager.get_symbol_state(symbol)
            old_offset = state.get("offset", 0.0)
            old_cost = state.get("cost_basis", 0.0)

            # 调用纯函数
            offset, cost = calculate_offset_and_cost(
                ideal_hedges[symbol],
                positions.get(symbol, 0.0),
                prices[symbol],
                old_offset,
                old_cost
            )

            offsets[symbol] = (offset, cost)

            # 更新状态
            await update_offset_state(self.state_manager, symbol, offset, cost)

        return offsets

    async def _decide_actions(self, offsets, prices):
        """决策（调用纯函数）"""
        all_actions = []

        for symbol, (offset, cost_basis) in offsets.items():
            if symbol not in prices:
                continue

            price = prices[symbol]
            offset_usd = abs(offset) * price

            # 计算区间（纯函数）
            zone = calculate_zone(
                offset_usd,
                self.config["threshold_min_usd"],
                self.config["threshold_max_usd"],
                self.config["threshold_step_usd"]
            )

            # 获取状态
            state = await self.state_manager.get_symbol_state(symbol)

            # 检查冷却期（纯函数）
            cooldown_status, reason = analyze_cooldown_status(
                state,
                state.get("monitoring", {}).get("zone"),
                zone,
                self.config.get("cooldown_after_fill_minutes", 5)
            )

            logger.info(f"{symbol}: zone={zone}, cooldown={cooldown_status}")

            # 根据冷却期状态处理
            if should_skip_action(cooldown_status):
                logger.info(f"  → SKIP: {reason}")
                continue

            if should_cancel_only(cooldown_status):
                # 只撤单
                if state.get("monitoring", {}).get("order_id"):
                    all_actions.append(TradingAction(
                        type=ActionType.CANCEL_ORDER,
                        symbol=symbol,
                        order_id=state["monitoring"]["order_id"],
                        reason=reason
                    ))
                logger.info(f"  → CANCEL_ONLY: {reason}")
                continue

            # 正常决策（纯函数）
            actions = decide_action(symbol, offset, cost_basis, price, zone, state, self.config)
            all_actions.extend(actions)

        return all_actions

    async def _execute_actions(self, actions):
        """执行操作（副作用）"""
        results = []

        for action in actions:
            try:
                if action.type == ActionType.PLACE_LIMIT_ORDER:
                    order_id = await execute_limit_order(
                        self.exchange,
                        action.symbol,
                        action.side,
                        action.size,
                        action.price
                    )
                    await update_order_state(
                        self.state_manager,
                        action.symbol,
                        order_id,
                        action.metadata.get("zone", 0)
                    )
                    results.append({"success": True})

                elif action.type == ActionType.CANCEL_ORDER:
                    success = await cancel_order(
                        self.exchange,
                        action.symbol,
                        action.order_id
                    )
                    if success:
                        await clear_monitoring_state(self.state_manager, action.symbol)
                    results.append({"success": success})

                # ... 其他操作类型

            except Exception as e:
                logger.error(f"Failed to execute {action.type}: {e}")
                results.append({"success": False, "error": str(e)})

        return results
```

**步骤 4.2：添加切换开关**

```python
# src/main.py 修改
class HedgeBot:
    def __init__(self, config_path: str = "config.json", use_v2: bool = False):
        self.use_v2 = use_v2
        # ...

    async def initialize(self):
        if self.use_v2:
            from engine_v2 import HedgeEngineV2
            self.engine = HedgeEngineV2(self.config_path)
        else:
            from hedge_engine import HedgeEngine
            self.engine = HedgeEngine(self.config_path)
```

**步骤 4.3：并行测试**

```bash
# 测试旧引擎
USE_V2=false python src/main.py

# 测试新引擎
USE_V2=true python src/main.py
```

**验收标准：**
- ✅ 新引擎完整实现所有功能
- ✅ 新旧引擎可以切换
- ✅ 新引擎测试通过
- ✅ 旧引擎依然可用（保险）

---

### 阶段 5：迁移和清理（1天）

**目标：** 完全切换到新引擎，删除旧代码

**步骤 5.1：切换默认引擎**

```python
# 修改 main.py 默认值
def __init__(self, config_path: str = "config.json", use_v2: bool = True):
```

**步骤 5.2：观察运行**

- 在生产环境运行 24 小时
- 监控错误日志
- 验证所有功能正常

**步骤 5.3：删除旧代码**

```bash
# 删除旧文件
git rm src/core/pipeline.py
git rm src/core/decision_engine.py
git rm src/core/action_executor.py
git rm src/hedge_engine.py

# 重命名新引擎
git mv src/engine_v2.py src/engine.py
```

**验收标准：**
- ✅ 新引擎运行稳定 24 小时
- ✅ 无严重错误
- ✅ 旧代码全部删除
- ✅ 代码库清爽

---

## 6. 风险控制

### 6.1 回退策略

每个阶段都有独立的回退点：

| 阶段 | 回退操作 | 耗时 |
|------|---------|------|
| 阶段 1 | 删除 calculations/ 目录，恢复导入 | 5 分钟 |
| 阶段 2 | 删除 decisions/ 目录 | 5 分钟 |
| 阶段 3 | 删除 execution/, services/ 目录 | 5 分钟 |
| 阶段 4 | 修改 use_v2=False，切回旧引擎 | 1 分钟 |
| 阶段 5 | git revert 提交，恢复旧代码 | 10 分钟 |

### 6.2 失败检测

**自动检测指标：**

```python
# 在 main.py 中添加健康检查
if self.error_count >= 5:
    logger.critical("连续错误过多，可能是新引擎问题")
    logger.critical("建议切换回旧引擎: USE_V2=false")
```

**手动检测：**

- 每天检查日志：`grep ERROR logs/hedge_engine.log`
- 检查订单成交率
- 检查偏移计算是否正确

### 6.3 分支管理

```bash
# 每个阶段创建独立分支
git checkout -b refactor-phase-1-calculations
# 完成后合并
git checkout main
git merge refactor-phase-1-calculations

# 主分支始终保持可运行状态
```

---

## 7. 验收标准

### 7.1 功能完整性

- ✅ 所有原有功能保持不变
- ✅ 偏移计算正确（与旧版结果一致）
- ✅ 订单下单/撤单正常
- ✅ 冷却期逻辑正确
- ✅ 超时强制平仓正常
- ✅ 警报通知正常

### 7.2 代码质量

- ✅ 核心计算逻辑全部是纯函数
- ✅ 单元测试覆盖率 > 90%
- ✅ 集成测试覆盖主要流程
- ✅ 无循环依赖
- ✅ 代码行数减少 > 30%

### 7.3 可维护性

- ✅ 新人能在 10 分钟内理解架构
- ✅ 添加新功能无需修改核心逻辑
- ✅ 调试时能快速定位问题
- ✅ 文档清晰完整

---

## 8. 时间估算

| 阶段 | 工作量 | 风险 | 优先级 |
|------|--------|------|--------|
| 阶段 0：准备测试 | 1 天 | 低 | P0 |
| 阶段 1：提取计算 | 2 天 | 极低 | P0 |
| 阶段 2：提取决策 | 2 天 | 低 | P0 |
| 阶段 3：提取执行 | 2 天 | 低 | P1 |
| 阶段 4：新引擎 | 3 天 | 中 | P1 |
| 阶段 5：迁移清理 | 1 天 | 中 | P2 |
| **总计** | **11 天** | | |

**缓冲时间：** +3 天（应对意外情况）
**总预估：** 14 天（2 周）

---

## 9. 成功标准

重构成功的标志：

```
✅ 代码库从 1933 行减少到 < 1200 行
✅ 纯函数占比 > 60%
✅ 状态管理代码 < 100 行
✅ 测试覆盖率 > 85%
✅ 运行稳定性 99.9% (一周内无宕机)
✅ 新增功能开发速度提升 50%
```

---

**编写者：** Claude Code
**审阅者：** [待用户确认]
**批准状态：** [待批准]
