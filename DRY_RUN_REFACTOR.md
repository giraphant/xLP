# DRY RUN 代码重构方案

## 当前问题

### 1. DRY RUN 逻辑散落在多处

**问题代码位置**：

```python
# execute.py - 重复的 dry_run 检查（4处）
if config.dry_run:
    logger.info("[DRY RUN] Would place limit order...")
    result["success"] = True
    result["order_id"] = "DRY_RUN_ORDER"
else:
    # 真实执行逻辑
    order_id = await _execute_limit_order(...)
```

**问题**：
- ✗ 每个操作类型都有重复的 `if config.dry_run` 检查
- ✗ DRY RUN 日志格式不统一（`[DRY RUN]` vs `🔍 DRY RUN MODE`）
- ✗ 返回值格式硬编码（`"DRY_RUN_ORDER"`, `"DRY_RUN_MARKET"`）
- ✗ 真实执行函数（`_execute_limit_order` 等）不知道 dry_run 状态

### 2. 日志输出混乱

```python
# execute.py:42 - 开始时提示
if config.dry_run:
    logger.info("🔍 DRY RUN MODE - No real trades will be executed")

# execute.py:58 - 限价单
logger.info(f"[DRY RUN] Would place limit order: ...")

# execute.py:112 - 结束时提示
if config.dry_run:
    logger.info("🔍 DRY RUN MODE - No trades were actually executed")
```

**问题**：
- ✗ 2 种日志格式（`🔍 DRY RUN MODE` vs `[DRY RUN]`）
- ✗ 重复提示（开始和结束都说明 dry run）
- ✗ 不够醒目（实战时容易忘记关闭 dry run）

### 3. 配置不清晰

```python
# config.py:97
dry_run: bool = Field(default=False, alias="DRY_RUN")
```

**问题**：
- ✗ 默认值 `False` 不够安全（应该默认 True，防止误操作）
- ✗ 没有警告信息（启用时应该醒目提示）

---

## 优化方案

### 方案 1: 装饰器模式（推荐）

**核心思想**：创建一个装饰器，自动处理 dry run 逻辑

```python
# src/core/execute.py

from functools import wraps

def dry_run_safe(operation_name: str):
    """
    Dry run 装饰器：自动处理 dry_run 模式

    Args:
        operation_name: 操作名称（用于日志）
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(action: TradingAction, exchange, *args, config=None, **kwargs):
            # 检查 dry_run 模式
            if config and config.dry_run:
                logger.info(f"[DRY RUN] {operation_name}: {action.symbol} "
                           f"{getattr(action, 'side', '')} "
                           f"{getattr(action, 'size', '')} "
                           f"@ ${getattr(action, 'price', 'market')}")

                # 返回模拟结果
                return f"DRY_RUN_{operation_name.upper().replace(' ', '_')}"

            # 真实执行
            return await func(action, exchange, *args, **kwargs)

        return wrapper
    return decorator


# 使用装饰器
@dry_run_safe("place limit order")
async def _execute_limit_order(action: TradingAction, exchange) -> str:
    """执行限价单"""
    logger.info(f"📤 Placing limit order: {action.symbol} {action.side} "
               f"{action.size:.4f} @ ${action.price:.2f}")

    order_id = await exchange.place_limit_order(...)
    logger.info(f"✅ Limit order placed: {action.symbol} (ID: {order_id})")
    return order_id


@dry_run_safe("place market order")
async def _execute_market_order(action: TradingAction, exchange, notifier) -> str:
    """执行市价单"""
    # ... 实现
    pass


@dry_run_safe("cancel orders")
async def _execute_cancel_order(action: TradingAction, exchange) -> bool:
    """撤销订单"""
    # ... 实现
    pass
```

**优势**：
- ✅ 消除重复代码（4 处 if 检查 → 1 个装饰器）
- ✅ 统一日志格式
- ✅ 真实执行函数更清晰（无需关心 dry_run）
- ✅ 易于扩展新的操作类型

**劣势**：
- ⚠️ 需要修改函数签名（传入 config）

---

### 方案 2: 策略模式

**核心思想**：创建 DryRunExecutor 和 RealExecutor 两个执行器

```python
# src/core/executors.py

class ExecutorInterface:
    """执行器接口"""

    async def place_limit_order(self, action: TradingAction) -> str:
        raise NotImplementedError

    async def place_market_order(self, action: TradingAction) -> str:
        raise NotImplementedError

    async def cancel_orders(self, action: TradingAction) -> bool:
        raise NotImplementedError


class DryRunExecutor(ExecutorInterface):
    """Dry Run 执行器（模拟）"""

    async def place_limit_order(self, action: TradingAction) -> str:
        logger.info(f"[DRY RUN] Would place limit order: {action.symbol} ...")
        return "DRY_RUN_LIMIT_ORDER"

    async def place_market_order(self, action: TradingAction) -> str:
        logger.info(f"[DRY RUN] Would place market order: {action.symbol} ...")
        return "DRY_RUN_MARKET_ORDER"

    async def cancel_orders(self, action: TradingAction) -> bool:
        logger.info(f"[DRY RUN] Would cancel orders: {action.symbol}")
        return True


class RealExecutor(ExecutorInterface):
    """真实执行器"""

    def __init__(self, exchange, notifier):
        self.exchange = exchange
        self.notifier = notifier

    async def place_limit_order(self, action: TradingAction) -> str:
        logger.info(f"📤 Placing limit order: {action.symbol} ...")
        order_id = await self.exchange.place_limit_order(...)
        logger.info(f"✅ Limit order placed (ID: {order_id})")
        return order_id

    # ... 其他方法


# execute.py 中使用
async def execute_actions(actions, exchange, notifier, config):
    # 选择执行器
    executor = DryRunExecutor() if config.dry_run else RealExecutor(exchange, notifier)

    for action in actions:
        if action.type == ActionType.PLACE_LIMIT_ORDER:
            order_id = await executor.place_limit_order(action)
        elif action.type == ActionType.PLACE_MARKET_ORDER:
            order_id = await executor.place_market_order(action)
        # ...
```

**优势**：
- ✅ 完全分离 dry_run 和真实执行逻辑
- ✅ 易于测试（可以直接测试 DryRunExecutor）
- ✅ 符合 OOP 设计原则

**劣势**：
- ⚠️ 代码量较大（需要新建文件和类）
- ⚠️ 两个执行器需要保持接口一致

---

### 方案 3: 简化版（最小改动）

**核心思想**：提取 dry_run 检查到辅助函数

```python
# src/core/execute.py

def _should_execute(config) -> bool:
    """检查是否应该真实执行（非 dry run）"""
    return not config.dry_run


def _log_dry_run(action_desc: str):
    """统一的 dry run 日志"""
    logger.info(f"🔍 [DRY RUN] {action_desc}")


async def execute_actions(actions, exchange, notifier, config):
    # 开始提示
    logger.info("=" * 50)
    logger.info("⚡ EXECUTING ACTIONS")
    if not _should_execute(config):
        logger.warning("⚠️  DRY RUN MODE - No real trades will be executed")
    logger.info("=" * 50)

    for action in actions:
        if action.type == ActionType.PLACE_LIMIT_ORDER:
            if _should_execute(config):
                order_id = await _execute_limit_order(action, exchange)
                result["order_id"] = order_id
            else:
                _log_dry_run(f"Place limit order: {action.symbol} ...")
                result["order_id"] = "DRY_RUN"
            result["success"] = True

        # ... 其他操作类型

    # 结束提示
    if not _should_execute(config):
        logger.warning("⚠️  DRY RUN MODE - No trades were executed")
```

**优势**：
- ✅ 改动最小
- ✅ 统一日志格式
- ✅ 易于理解

**劣势**：
- ⚠️ 仍然有重复的 if 检查
- ⚠️ 不够优雅

---

## 推荐方案

**推荐使用：方案 3（简化版）**

**理由**：
1. **改动最小** - 不需要大幅重构，适合快速迭代
2. **风险最低** - 不改变函数签名和调用方式
3. **立即可用** - 可以马上部署到实战环境

**实施步骤**：

1. ✅ 提取辅助函数（`_should_execute`, `_log_dry_run`）
2. ✅ 统一日志格式（使用 `🔍 [DRY RUN]` 前缀）
3. ✅ 增强开始/结束提示（使用 `logger.warning`，更醒目）
4. ✅ 统一返回值（所有 dry run 都返回 `"DRY_RUN"`）

**后续优化**（可选）：
- 如果代码继续复杂化，再考虑方案 1（装饰器）或方案 2（策略模式）

---

## 配置优化

### 1. 更安全的默认值

```python
# config.py

# ❌ 当前（默认 False，容易误操作）
dry_run: bool = Field(default=False, alias="DRY_RUN")

# ✅ 建议（默认 True，更安全）
dry_run: bool = Field(default=True, alias="DRY_RUN")
```

### 2. 启动时醒目提示

```python
# main.py 或 run.py

config = load_config()

if config.dry_run:
    logger.warning("=" * 70)
    logger.warning("⚠️  DRY RUN MODE ENABLED - NO REAL TRADES WILL BE EXECUTED")
    logger.warning("⚠️  Set DRY_RUN=false in .env to enable real trading")
    logger.warning("=" * 70)
else:
    logger.warning("=" * 70)
    logger.warning("🔴 REAL TRADING MODE - ACTUAL TRADES WILL BE EXECUTED")
    logger.warning("🔴 Make sure you understand the risks before proceeding")
    logger.warning("=" * 70)

    # 可选：要求确认
    # input("Press Enter to continue with REAL trading...")
```

---

## 优先级

| 优化项 | 优先级 | 改动量 | 效果 |
|--------|--------|--------|------|
| 统一日志格式 | P0（高） | 小 | 立即改善可读性 |
| 提取辅助函数 | P0（高） | 小 | 减少重复代码 |
| 启动时醒目提示 | P0（高） | 小 | 防止误操作 |
| 统一返回值格式 | P1（中） | 小 | 代码一致性 |
| 默认值改为 True | P2（低） | 小 | 更安全，但可能打断习惯 |

---

## 测试验证

重构后需验证：

1. ✅ DRY RUN 模式下不执行真实交易
2. ✅ 日志输出清晰醒目
3. ✅ 非 DRY RUN 模式下正常执行
4. ✅ 所有操作类型都正确处理 dry_run

测试用例：
```bash
# 测试 1: DRY RUN 模式
DRY_RUN=true python src/main.py
# 期望：看到 [DRY RUN] 日志，没有真实交易

# 测试 2: 真实模式
DRY_RUN=false python src/main.py
# 期望：看到真实交易日志
```
