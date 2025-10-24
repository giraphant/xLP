# PREPARE 模块结构分析

## 概述

PREPARE 模块职责：**从外部数据源获取原始数据，调用纯函数进行计算，返回完整的决策输入数据**

## 函数结构（8个函数）

```
prepare_data()  ← 主入口
├── _fetch_pool_data()          # 获取池子持仓
├── _calculate_ideal_hedges()   # 计算理想对冲（纯函数）
├── _fetch_market_data()        # 获取价格和持仓
├── _calculate_offsets()        # 计算偏移和成本（纯函数 + cost_history管理）
├── _calculate_zones()          # 计算zone（纯函数）
├── _fetch_order_status()       # 获取订单状态 + 计算 previous_zone
└── _fetch_last_fill_times()    # 获取最后成交时间
```

---

## 详细分析

### 1. prepare_data() - 主编排器

**职责**：按顺序调用子函数，组装最终数据字典

**依赖**：
- config: HedgeConfig 对象
- pool_calculators: {pool_type: async callable}
- exchange: ExchangeInterface 实现
- cost_history: {symbol: (offset, cost)} - 唯一的持久化状态

**返回**：
```python
{
    "symbols": ["SOL", "BTC", ...],
    "ideal_hedges": {"SOL": -10.5, ...},
    "positions": {"SOL": 100.0, ...},
    "prices": {"SOL": 150.0, ...},
    "offsets": {"SOL": (5.2, 148.5), ...},  # (offset, cost_basis)
    "zones": {"SOL": {"zone": 2, "offset_usd": 12.5}, ...},
    "order_status": {
        "SOL": {
            "has_order": True,
            "order_count": 2,
            "oldest_order_time": datetime(...),
            "orders": [...],
            "previous_zone": 1
        },
        ...
    },
    "last_fill_times": {"SOL": datetime(...), ...}
}
```

**逻辑**：
1. 获取池子数据
2. 计算理想对冲
3. 获取市场数据（价格、持仓）
4. 获取订单和成交状态（需要价格来计算 previous_zone）
5. 计算偏移和成本
6. 计算zones

**纯度**：❌ 不是纯函数（有I/O操作）

---

### 2. _fetch_pool_data() - 池子数据获取

**职责**：并发调用所有池子计算器获取持仓

**依赖**：
- pool_calculators: {pool_type: async callable}
- config.jlp_amount, config.alp_amount

**返回**：
```python
{
    "jlp": {"SOL": {"amount": 10.5}, "BTC": {"amount": 0.05}},
    "alp": {"SOL": {"amount": 5.2}}
}
```

**逻辑**：
```python
for pool_type, calculator in pool_calculators.items():
    amount = config.{pool_type}_amount
    if amount > 0:
        pool_data[pool_type] = await calculator(amount)
```

**纯度**：❌ 不是纯函数（异步I/O，调用RPC）

---

### 3. _calculate_ideal_hedges() - 理想对冲计算

**职责**：合并所有池子持仓，计算需要对冲的数量

**依赖**：
- pool_data: 来自 _fetch_pool_data()

**返回**：
```python
{"SOL": -15.7, "BTC": -0.05}  # 负值 = 做空对冲
```

**逻辑**：
```python
for pool_type, positions in pool_data.items():
    for symbol, data in positions.items():
        merged_hedges[symbol] += -data["amount"]  # 反向对冲
```

**纯度**：✅ 纯函数（无副作用，输出只取决于输入）

---

### 4. _fetch_market_data() - 市场数据获取

**职责**：并发查询价格和持仓，加上初始偏移量

**依赖**：
- **exchange.get_price(symbol)** ← 关键 API
- **exchange.get_position(symbol)** ← 关键 API
- config.initial_offset_{symbol}

**返回**：
```python
positions = {"SOL": 100.5, ...}  # 交易所持仓 + 初始偏移
prices = {"SOL": 150.0, ...}
```

**逻辑**：
```python
# 并发查询
price_tasks = {symbol: exchange.get_price(symbol) for symbol in symbols}
position_tasks = {symbol: exchange.get_position(symbol) for symbol in symbols}

prices = await asyncio.gather(*price_tasks.values())
positions = await asyncio.gather(*position_tasks.values())

# 加上初始偏移
positions[symbol] += config.initial_offset_{symbol}
```

**纯度**：❌ 不是纯函数（异步I/O，查询交易所）

---

### 5. _calculate_offsets() - 偏移和成本计算

**职责**：计算每个币种的偏移量和加权平均成本，并更新 cost_history

**依赖**：
- calculate_offset_and_cost() - 纯函数（来自 utils/calculators.py）
- cost_history - 读写

**返回**：
```python
{"SOL": (5.2, 148.5), ...}  # (offset, cost_basis)
```

**逻辑**：
```python
for symbol in ideal_hedges:
    old_offset, old_cost = cost_history.get(symbol, (0.0, 0.0))

    offset, cost = calculate_offset_and_cost(
        ideal_hedges[symbol],
        positions[symbol],
        prices[symbol],
        old_offset,
        old_cost
    )

    cost_history[symbol] = (offset, cost)  # 写回
    offsets[symbol] = (offset, cost)
```

**纯度**：⚠️ 半纯函数（计算是纯的，但会修改 cost_history）

**重要**：PREPARE 自己管理 cost_history 的读写

---

### 6. _calculate_zones() - Zone 计算

**职责**：根据 offset_usd 计算每个币种所在的 zone

**依赖**：
- calculate_zone() - 纯函数（来自 utils/calculators.py）

**返回**：
```python
{
    "SOL": {
        "zone": 2,  # None=阈值以下, 1/2/3=不同zone, -1=超阈值告警
        "offset_usd": 12.5
    },
    ...
}
```

**逻辑**：
```python
for symbol, (offset, cost) in offsets.items():
    offset_usd = abs(offset) * prices[symbol]

    zone = calculate_zone(
        offset_usd,
        config.threshold_min_usd,
        config.threshold_max_usd,
        config.threshold_step_usd
    )

    zones[symbol] = {"zone": zone, "offset_usd": offset_usd}
```

**纯度**：✅ 纯函数（无副作用，输出只取决于输入）

---

### 7. _fetch_order_status() - 订单状态获取

**职责**：查询活跃订单，计算 previous_zone

**依赖**：
- **exchange.get_open_orders()** ← 关键 API！
- calculate_zone_from_orders() - 纯函数

**返回**：
```python
{
    "SOL": {
        "has_order": True,
        "order_count": 2,
        "oldest_order_time": datetime(2025, 10, 24, 12, 30),
        "orders": [
            {
                "order_id": "12345",
                "symbol": "SOL",
                "side": "sell",
                "size": 5.0,
                "price": 150.5,
                "created_at": datetime(...)
            },
            ...
        ],
        "previous_zone": 1  # 从订单size反推的zone
    },
    ...
}
```

**逻辑**：
```python
all_orders = await exchange.get_open_orders()  # ← 关键！

for symbol in symbols:
    symbol_orders = [o for o in all_orders if o.get('symbol') == symbol]

    if symbol_orders:
        oldest_order = min(symbol_orders, key=lambda x: x.get('created_at'))

        previous_zone = calculate_zone_from_orders(
            symbol_orders,
            prices[symbol],
            config.threshold_min_usd,
            config.threshold_step_usd
        )

        order_status[symbol] = {
            "has_order": True,
            "order_count": len(symbol_orders),
            "oldest_order_time": oldest_order.get('created_at'),
            "orders": symbol_orders,
            "previous_zone": previous_zone
        }
```

**纯度**：❌ 不是纯函数（异步I/O，查询交易所）

**关键依赖**：
- exchange.get_open_orders() 必须返回正确的订单列表
- 每个订单必须包含：`symbol`, `created_at`, `size`, `side`, `price`

---

### 8. _fetch_last_fill_times() - 最后成交时间获取

**职责**：查询最近成交，提取每个币种的最后成交时间（用于冷却期判断）

**依赖**：
- **exchange.get_recent_fills(minutes_back)** ← 关键 API！

**返回**：
```python
{
    "SOL": datetime(2025, 10, 24, 12, 25),  # 最后成交时间
    "BTC": None,  # 没有成交
    ...
}
```

**逻辑**：
```python
recent_fills = await exchange.get_recent_fills(minutes_back=cooldown_minutes + 5)  # ← 关键！

for symbol in symbols:
    symbol_fills = [f for f in recent_fills if f.get('symbol') == symbol]

    if symbol_fills:
        latest_fill = max(symbol_fills, key=lambda x: x.get('filled_at'))
        last_fill_times[symbol] = latest_fill.get('filled_at')
    else:
        last_fill_times[symbol] = None
```

**纯度**：❌ 不是纯函数（异步I/O，查询交易所）

**关键依赖**：
- exchange.get_recent_fills() 必须返回正确的成交列表
- 每个成交必须包含：`symbol`, `filled_at`

---

## 关键依赖总结

### PREPARE 模块的外部依赖

| 依赖 | 类型 | 调用位置 | 期望返回 |
|-----|------|---------|---------|
| **pool_calculators** | 异步函数 | _fetch_pool_data:104 | `{symbol: {"amount": float}}` |
| **exchange.get_price()** | 异步方法 | _fetch_market_data:182 | `float` (价格) |
| **exchange.get_position()** | 异步方法 | _fetch_market_data:185 | `float` (持仓) |
| **exchange.get_open_orders()** | 异步方法 | _fetch_order_status:363 | `List[dict]` (订单列表) |
| **exchange.get_recent_fills()** | 异步方法 | _fetch_last_fill_times:423 | `List[dict]` (成交列表) |

### 关键数据字段要求

**get_open_orders() 返回格式**：
```python
[
    {
        "order_id": str,
        "symbol": str,  # 必须是用户 symbol（"BONK"，不是 "1000BONK"）
        "side": str,    # "buy" or "sell"
        "size": float,  # 订单数量
        "price": float,
        "created_at": datetime,  # 必须是 datetime 对象
        "status": str   # "open"
    },
    ...
]
```

**get_recent_fills() 返回格式**：
```python
[
    {
        "symbol": str,  # 必须是用户 symbol
        "filled_at": datetime,  # 必须是 datetime 对象
        "side": str,
        "filled_size": float,
        "filled_price": float
    },
    ...
]
```

---

## PREPARE 结构评估

### 优点

1. ✅ **职责清晰**：8个函数各司其职
2. ✅ **纯函数隔离**：计算逻辑（_calculate_ideal_hedges, _calculate_zones）是纯函数
3. ✅ **并发优化**：使用 asyncio.gather 并发查询
4. ✅ **错误处理**：每个I/O操作都有 try-except
5. ✅ **日志完善**：每个步骤都有详细日志

### 问题点（全部来自 exchange 依赖）

如果系统出现以下问题：
1. ❌ 重复下单 → **exchange.get_open_orders() 返回空或错误数据**
2. ❌ 冷却期不生效 → **exchange.get_recent_fills() 返回空或错误数据**
3. ❌ Zone 计算错误 → **订单的 size 字段错误**
4. ❌ 超时不触发 → **订单的 created_at 字段错误**

**结论**：PREPARE 本身结构清晰，问题一定在 exchange adapter 层

---

## 下一步：修复 Exchange Adapter

根据 REFACTOR_PLAN.md，需要：

1. **清理 Symbol 映射逻辑**
   - 移除混乱的三重映射
   - 统一使用用户 symbol 对外接口
   - adapter 内部转换 Lighter symbol

2. **修复 get_open_orders()**
   - 确保返回用户 symbol
   - 正确解析 Order 对象字段
   - 验证 created_at, size, side 字段

3. **修复 get_recent_fills()**
   - 确保返回用户 symbol
   - 正确解析 Trade 对象字段
   - 验证 filled_at 字段

4. **添加详细诊断日志**
   - 在 adapter 中打印原始 API 返回
   - 验证字段转换是否正确
