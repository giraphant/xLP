# 日志、通知、报告系统优化建议

## 📊 当前状态分析

### ✅ 优点
- 完整的日志级别控制（LOG_LEVEL环境变量）
- 结构化的Pipeline日志（每步清晰）
- 多渠道通知（Pushover + Matsu监控）
- 详细的持仓报告（monitoring/reports.py）

### ⚠️ 发现的问题
1. **无日志轮转** - 长期运行会填满磁盘 ⚠️
2. **Pushover使用print** - 应该用logging统一管理 ⚠️
3. **缺少结构化数据** - 难以做日志聚合分析（如ELK）
4. **通知噪音** - Pushover可能发送过多通知

### ✅ 非问题（设计为Feature）
- **Emoji丰富** - 便于人工阅读和区分不同类型的日志 ✅
- **分隔线清晰** - 便于DEBUG时快速定位Pipeline各阶段 ✅

---

## 🎯 优化建议（按优先级）

### 🔴 P0 - 必须修复

#### 1. 添加日志轮转（防止磁盘填满）

**问题**：Docker容器日志无限增长

**方案**：
```python
# 已创建: src/utils/logging_config.py
# 使用 RotatingFileHandler
- 单文件最大 10MB
- 保留 5 个备份
- 自动压缩旧日志
```

**影响**：✅ 防止磁盘填满导致服务崩溃

---

#### 2. 修复Pushover使用logging（已修复 ✅）

**问题**：pushover.py使用`print()`而非`logging`

**修复**：
- ✅ 添加 `logger = logging.getLogger(__name__)`
- ✅ 替换所有`print()`为`logger.info/error()`
- ✅ 使通知日志可以被集中管理

---

### 🟡 P1 - 高优先级

#### 3. 添加结构化日志支持

**问题**：当前日志都是字符串，难以做分析

**建议**：添加可选的JSON日志格式

```python
# 环境变量控制
LOG_FORMAT=json  # 或 'text'（默认）

# JSON格式示例
{
  "timestamp": "2025-10-18T12:00:00Z",
  "level": "INFO",
  "logger": "core.pipeline",
  "message": "Pipeline completed",
  "extra": {
    "duration": 2.5,
    "success_count": 8,
    "error_count": 0,
    "symbols": ["SOL", "ETH", "BTC"]
  }
}
```

**好处**：
- ✅ 可以用ELK/Grafana Loki聚合
- ✅ 方便做监控告警
- ✅ 更容易debug历史问题

---


### 🟢 P2 - 中优先级

#### 4. 通知去重和聚合

**问题**：频繁操作可能导致Pushover通知轰炸

**建议**：
```python
class SmartNotifier:
    def __init__(self):
        self.notification_cache = {}  # 缓存最近通知
        self.min_interval = 300  # 同类通知最小间隔（秒）

    async def send_with_dedup(self, key: str, message: str):
        """带去重的通知发送"""
        last_sent = self.notification_cache.get(key)
        if last_sent and (time.time() - last_sent) < self.min_interval:
            logger.debug(f"Skip duplicate notification: {key}")
            return False

        # 发送并记录
        success = await self.send(message)
        if success:
            self.notification_cache[key] = time.time()
        return success
```

---

#### 5. 添加日志级别动态调整

**建议**：添加API或信号处理器动态调整日志级别

```python
# 不需要重启容器就能调整日志级别
import signal

def handle_sigusr1(signum, frame):
    """SIGUSR1 -> DEBUG level"""
    logging.getLogger().setLevel(logging.DEBUG)
    logger.info("Log level changed to DEBUG")

def handle_sigusr2(signum, frame):
    """SIGUSR2 -> INFO level"""
    logging.getLogger().setLevel(logging.INFO)
    logger.info("Log level changed to INFO")

signal.signal(signal.SIGUSR1, handle_sigusr1)
signal.signal(signal.SIGUSR2, handle_sigusr2)

# 使用：
# docker exec xLP-hedge-1 kill -SIGUSR1 1  # 开启DEBUG
# docker exec xLP-hedge-1 kill -SIGUSR2 1  # 恢复INFO
```

---

#### 6. 性能监控增强

**建议**：在Matsu上报中添加性能指标

```python
# 当前只上报：ideal/actual/cost_basis
# 可以添加：
data_points.append({
    "monitor_id": f"{pool_name}_pipeline_duration",
    "value": context.metadata.get("total_duration", 0),
})
data_points.append({
    "monitor_id": f"{pool_name}_error_count",
    "value": len(context.metadata.get("errors", [])),
})
```

---

### 🔵 P3 - 低优先级（Nice to have）

#### 7. 添加慢日志

**建议**：记录执行时间超过阈值的操作

```python
@log_slow_operations(threshold_seconds=2.0)
async def fetch_market_data():
    # 如果超过2秒，自动记录WARNING日志
    pass
```

---

#### 8. 报告生成优化

**当前**：每次Pipeline都生成详细报告

**建议**：
- 正常运行：只记录摘要
- 有变化时：记录详细报告
- 定时（如每小时）：记录完整报告

---

## 📝 推荐实施顺序

1. ✅ **立即实施**：
   - [x] 修复Pushover使用logging（已完成）
   - [ ] 添加日志轮转（防止磁盘满）

2. **本周内**：
   - [ ] 减少Pipeline日志冗余
   - [ ] 优化Emoji使用

3. **有空时**：
   - [ ] 添加结构化日志支持
   - [ ] 通知去重
   - [ ] 性能指标监控

---

## 🛠️ 实施方式

### 方案A：渐进式优化（推荐）
逐步实施，不影响现有功能

### 方案B：大重构
一次性重构所有日志系统（风险较高）

---

## ❓ 需要讨论的问题

1. **日志详细程度**：你更倾向于详细（便于debug）还是简洁（便于监控）？
2. **Emoji**：是否保留在系统日志中？
3. **结构化日志**：是否需要JSON格式（如果你用ELK/Loki）？
4. **通知频率**：Pushover通知是否过多？需要去重吗？

---

*生成时间：2025-10-18*
*基于代码库版本：4fbb3c6*
