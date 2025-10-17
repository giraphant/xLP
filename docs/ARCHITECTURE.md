# Solana LP Hedge System - 架构说明

## 系统概述

这是一个用于自动对冲 Solana LP 代币（JLP 和 ALP）的系统。系统通过链上数据计算理想对冲量，并自动执行平仓逻辑来维护对冲平衡。

## 核心模块

### 1. 数据获取层

#### `JLP_Hedge.py`
- 从 Solana 链上直接解析 JLP 池数据
- 计算每个资产的理想对冲量
- 输出格式：8位小数精度

#### `ALP_Hedge.py`
- 从 Solana 链上直接解析 ALP 池数据
- 包含 JITOSOL → SOL 转换逻辑
- 使用 Oracle 获取价格数据
- 输出格式：8位小数精度

### 2. 原子算法层

#### `offset_tracker.py` ⭐ **核心原子模块**
这是整个系统最关键的算法模块，完全独立，无副作用。

**主要功能：**
```python
calculate_offset_and_cost(
    ideal_position: float,
    actual_position: float,
    current_price: float,
    old_offset: float,
    old_cost: float
) -> Tuple[float, float]
```

**统一公式：**
```
new_cost = (old_offset × old_cost + delta_offset × current_price) / new_offset
```

这个公式自动处理所有场景：
- ✅ 首次建仓
- ✅ 敞口扩大（加权平均）
- ✅ 敞口缩小（成本调整，反映已实现盈亏）
- ✅ 完全平仓（归零）
- ✅ 反转（从多头敞口变空头敞口，或反之）

**辅助功能：**
- `analyze_offset_change()` - 分析偏移变化性质
- `calculate_pnl()` - 计算浮动盈亏
- `calculate_realized_pnl()` - 计算已实现盈亏

### 3. 对冲引擎层

#### `HedgeEngine.py`
核心引擎，协调所有模块。

**主要职责：**
1. 获取 JLP 和 ALP 的理想对冲量
2. 按币种合并对冲量（统一追踪 SOL、ETH、BTC、BONK）
3. 使用 `offset_tracker` 计算偏移和成本
4. 根据区间阈值触发平仓逻辑
5. 管理限价单和超时强平

**关键方法：**
- `get_ideal_hedges()` - 获取理想对冲量，WBTC→BTC 转换
- `process_symbol()` - 处理单个币种的对冲逻辑
- `run_once()` - 执行一次完整检查循环

### 4. 交易所接口层

#### `exchange_interface.py`
抽象交易所接口，支持多个交易所。

**当前实现：**
- `ExchangeInterface` - 抽象基类
- `MockExchange` - 测试用模拟交易所
- `LighterExchange` - Lighter 交易所（待实现）

**接口方法：**
- `get_position()` - 获取持仓
- `get_price()` - 获取价格
- `place_limit_order()` - 限价单
- `place_market_order()` - 市价单
- `cancel_order()` - 撤单

### 5. 通知层

#### `notifier.py`
Pushover 通知集成。

**通知类型：**
- 超阈值警报
- 强制平仓通知
- 订单执行通知（可选）

## 配置文件

### `config.json`
统一配置，按币种管理（不再区分 JLP/ALP）。

**关键参数：**
```json
{
  "jlp_amount": 50000,
  "alp_amount": 10000,
  "threshold_min": 1.0,      // 最小阈值 1%
  "threshold_max": 2.0,      // 最大阈值 2%
  "threshold_step": 0.2,     // 区间步长 0.2%
  "order_price_offset": 0.2, // 挂单价格偏移 0.2%
  "close_ratio": 40.0,       // 每次平仓比例 40%
  "timeout_minutes": 20      // 超时强平 20 分钟
}
```

### `state.json`
运行时状态，按币种追踪。

**状态结构：**
```json
{
  "symbols": {
    "SOL": {
      "offset": 609.24,
      "cost_basis": 200.0,
      "last_updated": "2025-10-16T23:21:40",
      "monitoring": {
        "active": false,
        "current_zone": null,
        "order_id": null
      }
    }
  }
}
```

## 测试套件

### `test_cost_tracking.py`
基础成本追踪测试，12轮场景验证。

### `test_cost_detailed.py`
详细测试，包含5个案例：
1. 多头敞口建立和平仓
2. 空头敞口建立和平仓
3. 极端价格波动案例
4. 多空反转
5. 分批平仓盈亏追踪

### `test_10_steps.py`
完整的10步演示，展示每步的：
- 市场状态
- 偏移分析
- 详细计算过程
- 成本解读
- 盈亏计算

### `offset_tracker.py` (自测试)
模块内置简单测试，验证5个基础场景。

## 数据流

```
1. 链上数据
   ↓
2. JLP_Hedge.py / ALP_Hedge.py
   ↓ (计算理想对冲量)
3. HedgeEngine.py
   ↓ (合并、获取实际持仓)
4. offset_tracker.py ⭐
   ↓ (计算偏移和成本)
5. HedgeEngine.py
   ↓ (判断区间、触发平仓)
6. exchange_interface.py
   ↓ (执行交易)
7. notifier.py
   (通知)
```

## 关键设计原则

### 1. **原子化**
`offset_tracker.py` 是完全独立的原子模块：
- 无外部依赖
- 纯函数，无副作用
- 可单独测试
- 可在其他项目复用

### 2. **统一追踪**
按币种（SOL、ETH、BTC、BONK）统一追踪，不区分来源（JLP或ALP）。

### 3. **零外部依赖**
JLP 和 ALP 数据完全从链上解析，不依赖任何第三方 API。

### 4. **交易所无关**
通过抽象接口支持多个交易所。

### 5. **可观测性**
- 详细日志
- Pushover 通知
- 状态持久化

## 未来扩展

1. **Lighter 交易所集成** - 实现 `LighterExchange` 类
2. **更多交易所** - 添加 Binance、OKX 等
3. **日志系统** - 结构化日志用于监控
4. **风控模块** - 添加额外的风控检查
5. **回测系统** - 基于历史数据测试策略

## 版本历史

### v1.0 (Current)
- ✅ JLP 和 ALP 对冲计算
- ✅ 统一偏移追踪算法
- ✅ 区间触发平仓逻辑
- ✅ 模块化架构
- ✅ 原子化成本追踪模块
- ✅ 完整测试套件

## 维护者

本系统由 AI (Claude) 协助用户构建，用于生产环境的 LP 对冲自动化。
