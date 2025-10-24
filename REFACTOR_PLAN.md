# LighterExchange 重构方案

## 问题分析

### 当前架构的混乱点

1. **Symbol 层级混乱**
   ```
   用户层: BONK → prepare/decide/execute 全部使用
   API层:  1000BONK → 只在 Lighter API 调用时使用
   ID层:   789 → market_id，API 参数
   ```

2. **映射字典职责不清**
   ```python
   # 当前代码
   self.symbol_to_market_id = {}      # 实际是 lighter_symbol → market_id
   self.market_id_to_symbol = {}      # 实际是 market_id → lighter_symbol
   self.lighter_to_user_symbol = {}   # lighter_symbol → user_symbol
   ```
   **问题**：需要三个映射才能完成 `user_symbol → market_id → user_symbol` 的转换

3. **_get_market_id() 名不副实**
   ```python
   def _get_market_id(self, symbol: str) -> str:  # 返回 str 不是 int！
       """Convert symbol to Lighter market symbol"""
       return self.SYMBOL_MAP.get(symbol.upper(), symbol.upper())
   ```
   **问题**：函数名说返回 market_id，实际返回 lighter_symbol

---

## 正确的设计原则

### 原则1：用户 Symbol 全局统一
- Pool calculators → 用户 symbol
- prepare.py → 用户 symbol
- decide.py → 用户 symbol
- execute.py → 用户 symbol
- **LighterExchange 对外接口** → 用户 symbol

### 原则2：Adapter 是唯一转换边界
```
外部调用 get_open_orders("BONK")
    ↓
adapter: BONK → 1000BONK → 789 → API 调用
    ↓
adapter: API 结果 → 转回 BONK
    ↓
外部接收 [{"symbol": "BONK", ...}]
```

### 原则3：最小化状态
- 只缓存必要的映射：`user_symbol → market_id`
- 其他转换都是计算，不存储

---

## 重构方案

### 步骤1：清理映射逻辑

```python
class LighterExchange(ExchangeInterface):
    # 类常量：用户 symbol → Lighter symbol
    SYMBOL_MAP = {
        "SOL": "SOL",
        "BTC": "BTC",
        "ETH": "ETH",
        "BONK": "1000BONK"
    }

    # 反向映射：Lighter symbol → 用户 symbol
    REVERSE_MAP = {
        "SOL": "SOL",
        "BTC": "BTC",
        "ETH": "ETH",
        "1000BONK": "BONK"
    }

    def __init__(self, config: dict):
        super().__init__(config)

        self.lighter_client = LighterOrderManager(...)

        # 唯一需要的运行时映射：用户 symbol → market_id
        self._market_id_cache: Dict[str, int] = {}
```

### 步骤2：统一转换接口

```python
async def _get_market_id(self, user_symbol: str) -> int:
    """
    获取 market_id（带缓存）

    Args:
        user_symbol: 用户 symbol (如 "BONK")

    Returns:
        market_id: 数字 ID (如 789)
    """
    # 缓存命中
    if user_symbol in self._market_id_cache:
        return self._market_id_cache[user_symbol]

    # 确保市场已加载
    await self.lighter_client._load_markets()

    # 转换：用户 symbol → Lighter symbol
    lighter_symbol = self.SYMBOL_MAP.get(user_symbol, user_symbol)

    # 查询：Lighter symbol → market_id
    market_id = self.lighter_client.symbol_to_market_id.get(lighter_symbol)

    if market_id is None:
        raise ValueError(
            f"Market not found for user symbol '{user_symbol}' "
            f"(lighter symbol: '{lighter_symbol}')"
        )

    # 缓存
    self._market_id_cache[user_symbol] = market_id

    return market_id

def _to_lighter_symbol(self, user_symbol: str) -> str:
    """用户 symbol → Lighter symbol"""
    return self.SYMBOL_MAP.get(user_symbol, user_symbol)

def _to_user_symbol(self, lighter_symbol: str) -> str:
    """Lighter symbol → 用户 symbol"""
    return self.REVERSE_MAP.get(lighter_symbol, lighter_symbol)
```

### 步骤3：简化 get_open_orders()

```python
async def get_open_orders(self, symbol: str = None) -> list:
    """
    获取活跃订单

    Args:
        symbol: 用户 symbol，None 表示全部

    Returns:
        订单列表，symbol 字段使用用户 symbol
    """
    try:
        if symbol:
            # 单个市场
            market_id = await self._get_market_id(symbol)

            response = await self.lighter_client.order_api.account_active_orders(
                account_index=self.lighter_client.account_index,
                market_id=market_id
            )

            orders = []
            if response and hasattr(response, 'orders'):
                for order in response.orders:
                    # 返回时使用输入的用户 symbol
                    orders.append(self._parse_order(order, symbol))

            return orders

        else:
            # 所有市场：递归调用
            all_orders = []
            for user_symbol in self.SYMBOL_MAP.keys():
                orders = await self.get_open_orders(user_symbol)
                all_orders.extend(orders)

            return all_orders

    except Exception as e:
        logger.error(f"Error fetching open orders for {symbol}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []
```

### 步骤4：简化 get_recent_fills()

```python
async def get_recent_fills(self, symbol: str = None, minutes_back: int = 10) -> list:
    """
    获取最近成交

    Args:
        symbol: 用户 symbol，None 表示全部

    Returns:
        成交列表，symbol 字段使用用户 symbol
    """
    try:
        cutoff_time = datetime.now() - timedelta(minutes=minutes_back)
        cutoff_timestamp_ms = int(cutoff_time.timestamp() * 1000)

        # 确定要查询的 market_id
        market_id = None
        if symbol:
            market_id = await self._get_market_id(symbol)

        # 调用 API
        response = await self.lighter_client.order_api.trades(
            sort_by="block_number",
            sort_dir="desc",
            limit=100,
            account_index=self.lighter_client.account_index,
            market_id=market_id,
            var_from=cutoff_timestamp_ms
        )

        # 解析成交
        fills = []
        if response and hasattr(response, 'data'):
            for trade in response.data:
                # 解析时间
                filled_at = None
                if hasattr(trade, 'timestamp') and trade.timestamp:
                    filled_at = datetime.fromtimestamp(trade.timestamp / 1000)

                if not filled_at:
                    continue

                # 从 trade.market_id 反查用户 symbol
                trade_user_symbol = None

                # 方法1：如果指定了 symbol，直接使用
                if symbol:
                    trade_user_symbol = symbol

                # 方法2：从 market_id 反查
                else:
                    for user_sym, cached_mid in self._market_id_cache.items():
                        if cached_mid == trade.market_id:
                            trade_user_symbol = user_sym
                            break

                if not trade_user_symbol:
                    continue

                # 构建成交记录
                fill = {
                    "order_id": str(trade.trade_id) if hasattr(trade, 'trade_id') else None,
                    "symbol": trade_user_symbol,
                    "side": "sell" if hasattr(trade, 'is_maker_ask') and trade.is_maker_ask else "buy",
                    "filled_size": float(trade.size) / 1000 if hasattr(trade, 'size') else 0,
                    "filled_price": float(trade.price) if hasattr(trade, 'price') else 0,
                    "filled_at": filled_at
                }
                fills.append(fill)

        return fills

    except Exception as e:
        logger.error(f"Error fetching recent fills for {symbol}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []
```

---

## 对比：重构前后

### 重构前（混乱）
```python
# 3个映射
self.symbol_to_market_id = {}        # lighter_symbol → market_id
self.market_id_to_symbol = {}        # market_id → lighter_symbol
self.lighter_to_user_symbol = {}     # lighter_symbol → user_symbol

# 转换链路
user_symbol → _get_market_id() → lighter_symbol
lighter_symbol → symbol_to_market_id.get() → market_id
market_id → market_id_to_symbol.get() → lighter_symbol
lighter_symbol → lighter_to_user_symbol.get() → user_symbol
```

### 重构后（清晰）
```python
# 1个缓存 + 2个常量映射
SYMBOL_MAP = {...}                   # 常量
REVERSE_MAP = {...}                  # 常量
self._market_id_cache = {}           # 运行时缓存

# 转换链路
user_symbol → _get_market_id() → market_id  (一步到位)
lighter_symbol → _to_user_symbol() → user_symbol  (纯函数)
```

---

## 重构步骤

1. ✅ 添加 REVERSE_MAP 常量
2. ✅ 重命名 symbol_to_market_id → _market_id_cache
3. ✅ 删除 market_id_to_symbol
4. ✅ 删除 lighter_to_user_symbol
5. ✅ 重写 _get_market_id() 返回 int
6. ✅ 添加 _to_lighter_symbol() 和 _to_user_symbol()
7. ✅ 简化 get_open_orders()
8. ✅ 简化 get_recent_fills()
9. ✅ 删除 _ensure_market_map()（逻辑合并到 _get_market_id()）

---

## 测试清单

- [ ] get_position() 正常工作
- [ ] get_price() 正常工作
- [ ] get_open_orders("SOL") 返回正确数据
- [ ] get_open_orders("BONK") 返回正确数据（测试转换）
- [ ] get_open_orders() 无参数返回所有市场
- [ ] get_recent_fills("SOL") 返回正确数据
- [ ] get_recent_fills() 无参数返回所有市场
- [ ] _parse_order() 字段解析正确
- [ ] 所有单元测试通过
- [ ] 集成测试通过
