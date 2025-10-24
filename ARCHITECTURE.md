# xLP 系统架构分析

## 核心问题：Symbol 映射混乱

### 三层 Symbol 定义

1. **用户配置层** (系统内部统一使用)
   - SOL, BTC, ETH, **BONK**
   - 来源：池子计算器、配置文件
   - 使用范围：prepare, decide, execute, report

2. **Lighter API 层** (仅在 API 调用时使用)
   - SOL, BTC, ETH, **1000BONK**
   - 来源：Lighter 交易所 API
   - 使用范围：仅在 lighter_client 内部

3. **Market ID 层** (数字标识)
   - 123 (SOL), 456 (BTC), 789 (1000BONK)
   - 来源：Lighter API order_books()
   - 使用范围：API 调用参数

---

## 当前实现的问题

### 问题1：映射字典的键值混乱

```python
# 当前代码（no-state 分支）
class LighterExchange:
    def __init__(self):
        # 这三个映射的键值到底是什么？
        self.symbol_to_market_id = {}      # ??? → market_id
        self.market_id_to_symbol = {}      # market_id → ???
        self.lighter_to_user_symbol = {}   # Lighter symbol → 用户 symbol
```

**实际填充**：
```python
# _ensure_market_map()
self.symbol_to_market_id = self.lighter_client.symbol_to_market_id.copy()
# 来自 lighter_client：{"SOL": 123, "1000BONK": 789}
# 键是 Lighter symbol！

self.market_id_to_symbol = {mid: sym for sym, mid in self.symbol_to_market_id.items()}
# {123: "SOL", 789: "1000BONK"}
# 值是 Lighter symbol！

self.lighter_to_user_symbol = {v: k for k, v in self.SYMBOL_MAP.items()}
# {"SOL": "SOL", "1000BONK": "BONK"}
```

**导致的混乱**：
- 变量名说是 `symbol_to_market_id`，但实际是 `lighter_symbol_to_market_id`
- `market_id_to_symbol` 返回 Lighter symbol，不是用户 symbol
- 每次使用都要多一次转换

### 问题2：get_open_orders() 的逻辑混乱

```python
async def get_open_orders(self, symbol: str = None):
    # 输入：用户 symbol（"BONK"）

    if symbol:
        # 转换：BONK → 1000BONK
        lighter_symbol = self._get_market_id(symbol)
        # 查询映射：1000BONK → market_id
        market_id = self.symbol_to_market_id.get(lighter_symbol)

        # 调用 API
        orders = api.account_active_orders(market_id=market_id)

        # 返回：使用输入的 symbol
        return [self._parse_order(order, symbol)]  # symbol="BONK" ✓

    else:
        # 无参数：遍历所有市场
        for lighter_symbol, market_id in self.symbol_to_market_id.items():
            # lighter_symbol = "1000BONK"

            # 转换回用户 symbol
            user_symbol = self.lighter_to_user_symbol.get(lighter_symbol)
            # user_symbol = "BONK" ✓

            # 返回
            return [self._parse_order(order, user_symbol)]
```

**问题**：
- 需要维护两个映射才能完成一次转换
- 逻辑分散在多个地方
- 容易出错

### 问题3：_parse_order() 的字段访问

```python
def _parse_order(self, order, symbol: str):
    # Order 对象的字段：
    # - timestamp? created_at? 哪个存在？
    # - base_size? remaining_base_amount? 哪个优先？
    # - is_ask? ask_filter? 用哪个？

    # 当前代码：hasattr 判断一大堆
    if hasattr(order, 'timestamp') and order.timestamp:
        ...
    elif hasattr(order, 'created_at') and order.created_at:
        ...
    else:
        created_at = datetime.now()  # 降级方案
```

**问题**：
- 不知道 Order 对象的真实结构
- 降级逻辑可能导致错误数据
- 没有验证数据完整性

---

## 正确的架构应该是

### 原则1：系统内部统一使用用户 symbol

```
Pool Calculator → "BONK"
    ↓
prepare.py → "BONK"
    ↓
decide.py → "BONK"
    ↓
execute.py → "BONK"
    ↓
adapter.py → 转换 → "1000BONK" → Lighter API
               ↑ 结果转回 ↓
            "BONK" ← 订单数据
```

### 原则2：Adapter 是唯一的转换边界

```python
class LighterExchange(ExchangeInterface):
    """
    职责：
    1. 接收用户 symbol 输入
    2. 转换成 Lighter symbol 调用 API
    3. 将 API 结果转回用户 symbol 返回
    """

    def __init__(self):
        # 只需要一个映射：用户 symbol → Lighter symbol
        self.SYMBOL_MAP = {
            "SOL": "SOL",
            "BTC": "BTC",
            "ETH": "ETH",
            "BONK": "1000BONK"
        }

        # 反向映射
        self.REVERSE_MAP = {
            "SOL": "SOL",
            "BTC": "BTC",
            "ETH": "ETH",
            "1000BONK": "BONK"
        }

        # 用户 symbol → market_id（懒加载）
        self.user_symbol_to_market_id = {}

    async def _ensure_market_map(self):
        """加载市场映射：用户 symbol → market_id"""
        if self.user_symbol_to_market_id:
            return

        await self.lighter_client._load_markets()

        # 构建映射：用户 symbol → market_id
        for user_sym, lighter_sym in self.SYMBOL_MAP.items():
            market_id = self.lighter_client.symbol_to_market_id.get(lighter_sym)
            if market_id:
                self.user_symbol_to_market_id[user_sym] = market_id
```

### 原则3：明确 API 对象结构

```python
# 需要先探查 Lighter API 返回的真实对象结构
# 方法：打印所有字段和值，写成文档

"""
Order 对象结构（待确认）：
- order_index: int
- timestamp: int (毫秒)
- price: str
- base_size: str | None
- remaining_base_amount: int | None
- is_ask: bool
"""

def _parse_order(self, order, user_symbol: str):
    """严格解析，缺少必要字段就报错"""
    if not hasattr(order, 'order_index'):
        raise ValueError(f"Order missing order_index: {order}")

    if not hasattr(order, 'timestamp'):
        raise ValueError(f"Order missing timestamp: {order}")

    # ... 严格验证
```

---

## 下一步行动

1. **探查 API 对象结构**
   - 在真实环境中打印 Order, Trade 对象的所有字段
   - 记录到文档
   - 编写严格的解析逻辑

2. **重构 Adapter 映射**
   - 移除混乱的 symbol_to_market_id（Lighter symbol）
   - 只保留 user_symbol_to_market_id（用户 symbol）
   - 简化转换逻辑

3. **添加验证和错误处理**
   - API 调用失败要明确记录
   - 字段缺失要报错而不是降级
   - 数据异常要告警

4. **编写诊断工具**
   - 单独脚本测试 get_open_orders()
   - 打印所有中间变量
   - 验证映射是否正确
