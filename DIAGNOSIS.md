# 系统诊断框架

## 数据流和职责边界

```
┌─────────────────────────────────────────────────────────────┐
│ 1. PREPARE (数据准备层)                                      │
│    输入：pool_calculators, exchange, cost_history           │
│    输出：data = {                                            │
│        "symbols": ["SOL", "BTC", ...],                      │
│        "prices": {symbol: float},                           │
│        "offsets": {symbol: (offset, cost)},                 │
│        "zones": {symbol: {"zone": int, "offset_usd": float}},│
│        "order_status": {symbol: {...}},                     │
│        "last_fill_times": {symbol: datetime}                │
│    }                                                         │
│    依赖：exchange.get_price()                               │
│          exchange.get_position()                            │
│          exchange.get_open_orders()  ← 关键！               │
│          exchange.get_recent_fills() ← 关键！               │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. DECIDE (决策层 - 纯函数)                                  │
│    输入：data (from prepare), config                        │
│    输出：actions = [TradingAction, ...]                     │
│    逻辑：超阈值？超时？Zone恶化？冷却期？                     │
│    依赖：NONE（只读取 data）                                 │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. EXECUTE (执行层)                                          │
│    输入：actions, exchange, notifier, config                │
│    输出：results = [{"action": ..., "success": bool}, ...]  │
│    依赖：exchange.place_limit_order()                       │
│          exchange.place_market_order()                      │
│          exchange.cancel_all_orders()                       │
│          notifier.send()                                    │
└─────────────────────────────────────────────────────────────┘
```

---

## 问题定位矩阵

### 问题1：系统认为没有活跃订单，重复下单

| 可能的问题层 | 检查点 | 验证方法 |
|------------|-------|---------|
| **PREPARE层** | `exchange.get_open_orders()` 返回空 | 在 prepare.py 第363行后打印 `all_orders` |
| **PREPARE层** | 订单有，但 symbol 不匹配 | 打印 `symbol_orders = [o for o in all_orders if o.get('symbol') == symbol]` |
| **DECIDE层** | `order_status[symbol]["has_order"]` 永远是 False | 打印 decide.py 的输入 `data["order_status"]` |
| **EXCHANGE层** | API 调用失败（缺 await） | 已修复 |
| **EXCHANGE层** | API 返回数据但解析错误 | 打印 `orders_response.orders` 的原始数据 |

### 问题2：冷却期不生效，连续成交

| 可能的问题层 | 检查点 | 验证方法 |
|------------|-------|---------|
| **PREPARE层** | `exchange.get_recent_fills()` 返回空 | 在 prepare.py 第423行后打印 `recent_fills` |
| **PREPARE层** | 成交有，但 symbol 不匹配 | 打印 `symbol_fills` |
| **PREPARE层** | `filled_at` 字段解析错误 | 打印每个 fill 的 `filled_at` |
| **DECIDE层** | `last_fill_time` 没传进来 | 打印 decide.py 的输入 `data["last_fill_times"]` |
| **DECIDE层** | 冷却期判断逻辑错误 | 打印 `_check_cooldown()` 的返回值 |

### 问题3：Zone 计算错误

| 可能的问题层 | 检查点 | 验证方法 |
|------------|-------|---------|
| **PREPARE层** | `previous_zone` 计算依赖订单 size | 打印订单的 `size` 字段值 |
| **PREPARE层** | `calculate_zone_from_orders()` 输入错误 | 打印传入的 `symbol_orders` 和 `price` |
| **EXCHANGE层** | `_parse_order()` 的 size 字段错误 | 打印原始 `order.base_size` 和解析后的 `size` |

---

## DECIDE 模块是纯函数吗？

### 分析

```python
async def decide_actions(
    data: Dict[str, Any],  # 只读
    config: HedgeConfig     # 只读
) -> List[TradingAction]:
    # 只做决策逻辑，不调用任何 I/O
    # 只读取 data 和 config
    # 只输出 actions
```

**结论**：✅ **DECIDE 是纯函数**（除了日志）

- 不依赖外部状态
- 不修改输入参数
- 输出只取决于输入

**可能的问题**：
- ❌ 逻辑本身没问题（测试全过）
- ✅ **输入数据（data）有问题**

---

## PREPARE 模块会有问题吗？

### 分析

```python
async def prepare_data(
    config: HedgeConfig,
    pool_calculators: Dict[str, callable],
    exchange,
    cost_history: Dict[str, Tuple[float, float]]
) -> Dict[str, Any]:
    # 调用多个异步 API
    all_orders = await exchange.get_open_orders()      # ← I/O
    recent_fills = await exchange.get_recent_fills()   # ← I/O
```

**结论**：❌ **PREPARE 不是纯函数**（有 I/O）

**可能的问题**：
1. ✅ **API 调用失败或返回空**
   - `get_open_orders()` 返回 `[]`
   - `get_recent_fills()` 返回 `[]`

2. ✅ **数据解析错误**
   - 订单的 `symbol` 字段不匹配（"1000BONK" vs "BONK"）
   - 订单的 `created_at` 字段错误
   - 成交的 `filled_at` 字段错误

3. ✅ **数据过滤错误**
   - `symbol_orders = [o for o in all_orders if o.get('symbol') == symbol]` 匹配失败

---

## EXECUTE 模块会有问题吗？

### 分析

```python
async def execute_actions(
    actions: List[TradingAction],
    exchange,
    notifier,
    config
) -> List[Dict[str, Any]]:
    if config.dry_run:
        logger.info("[DRY RUN] Would place order...")
        return {"success": True, "order_id": "DRY_RUN_ORDER"}
    else:
        order_id = await exchange.place_limit_order(...)
```

**结论**：❌ **EXECUTE 不是纯函数**（有 I/O）

**Dry Run 模式下**：
- ✅ 不会真实下单
- ✅ 不会影响交易所状态
- ✅ 只记录日志

**可能的问题**：
- ❌ Dry run 模式下执行层没问题
- ✅ **PREPARE 层仍然会查询真实数据**

---

## 诊断结论

### 最可能的问题：**PREPARE 层数据获取错误**

1. **get_open_orders() 可能问题**：
   - API 调用失败（已修复 await）
   - 返回数据但 symbol 字段不匹配
   - 订单存在但被过滤掉

2. **get_recent_fills() 可能问题**：
   - API 调用失败（已修复 await）
   - 返回数据但 symbol 字段不匹配
   - 成交存在但被过滤掉
   - `filled_at` 字段解析错误

### 诊断方法

**在 Dry Run 模式下**，在 prepare.py 添加详细日志：

```python
# prepare.py:363
all_orders = await exchange.get_open_orders()
logger.info(f"[DIAGNOSIS] get_open_orders() returned {len(all_orders)} orders")
for order in all_orders:
    logger.info(f"[DIAGNOSIS] Order: symbol={order.get('symbol')}, "
                f"order_id={order.get('order_id')}, "
                f"size={order.get('size')}, "
                f"created_at={order.get('created_at')}")

# prepare.py:370
symbol_orders = [o for o in all_orders if o.get('symbol') == symbol]
logger.info(f"[DIAGNOSIS] Filtered orders for {symbol}: {len(symbol_orders)} orders")

# prepare.py:423
recent_fills = await exchange.get_recent_fills(minutes_back=cooldown_minutes + 5)
logger.info(f"[DIAGNOSIS] get_recent_fills() returned {len(recent_fills)} fills")
for fill in recent_fills:
    logger.info(f"[DIAGNOSIS] Fill: symbol={fill.get('symbol')}, "
                f"filled_at={fill.get('filled_at')}, "
                f"filled_size={fill.get('filled_size')}")
```

---

## 下一步

1. ✅ 添加诊断日志到 prepare.py
2. ✅ 在 Dry Run 模式下运行
3. ✅ 观察日志，确认：
   - `get_open_orders()` 是否返回数据？
   - 返回的 `symbol` 字段是什么？（SOL? 1000BONK?）
   - 过滤后还剩多少订单？
   - `get_recent_fills()` 是否返回数据？
   - `filled_at` 字段是否正确？
