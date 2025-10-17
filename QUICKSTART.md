# 🚀 xLP Quick Start Guide

## 一分钟了解项目

这是一个**Solana LP代币自动对冲引擎**，用于：
1. 从链上实时计算JLP/ALP的理想对冲量
2. 自动在Lighter交易所执行对冲平仓
3. 动态追踪加权平均成本
4. 区间触发平仓机制

## 📦 快速部署（Docker）

### 1. 克隆并配置

```bash
# 克隆项目
git clone https://github.com/giraphant/xLP.git
cd xLP

# 配置环境变量
cp .env.example .env
nano .env
```

### 2. 填写必要配置

编辑 `.env`：

```env
# Lighter Exchange
EXCHANGE_NAME=lighter
EXCHANGE_PRIVATE_KEY=你的Lighter私钥
EXCHANGE_ACCOUNT_INDEX=0
EXCHANGE_API_KEY_INDEX=0

# Pushover通知（可选）
PUSHOVER_USER_KEY=你的user_key
PUSHOVER_API_TOKEN=你的api_token

# 持仓量
JLP_AMOUNT=50000
ALP_AMOUNT=10000
```

### 3. 启动服务

```bash
# 创建数据目录
mkdir -p data logs

# 启动
docker-compose up -d

# 查看日志
docker-compose logs -f
```

## 🧪 测试 Lighter 集成

```bash
# 安装依赖
pip install -r requirements.txt

# 设置环境变量
export EXCHANGE_PRIVATE_KEY=你的私钥

# 运行测试
python test_lighter.py
```

**预期输出：**
```
✅ SOL Price: $200.00
✅ SOL Position: 0.0000
✅ All tests passed!
```

## 📊 核心功能

### 1. 链上数据解析
- **JLP Hedge**: 从 Jupiter LP 池解析持仓
- **ALP Hedge**: 从 Aster LP 池解析持仓（含JITOSOL转换）
- **零外部依赖**: 直接解析链上账户数据

### 2. 偏移追踪算法
```python
# 核心公式
new_cost = (old_offset × old_cost + delta_offset × price) / new_offset
```

**处理所有场景：**
- ✅ 首次建仓
- ✅ 敞口扩大（加权平均）
- ✅ 敞口缩小（成本调整）
- ✅ 完全平仓
- ✅ 多空反转

### 3. 区间触发机制

```
偏移百分比 < 1.0%    → 不触发
偏移百分比 1.0-1.2%  → 区间0，挂限价单
偏移百分比 1.2-1.4%  → 区间1，重新挂单
...
偏移百分比 > 2.0%    → 告警
```

**平仓逻辑：**
- 限价单：成本价 ± 0.2%
- 每次平仓：40% 的偏移量
- 超时强平：20分钟后市价单

### 4. Lighter 集成

**支持的操作：**
```python
# 获取持仓和价格
position = await exchange.get_position("SOL")
price = await exchange.get_price("SOL")

# 下单
order_id = await exchange.place_limit_order(
    symbol="SOL",
    side="sell",
    size=10.0,
    price=200.0
)

# 撤单
await exchange.cancel_order(order_id)
```

**市场映射：**
- SOL → SOL_USDC
- ETH → ETH_USDC
- BTC → BTC_USDC
- BONK → BONK_USDC

## 🔧 配置说明

### config.json

```json
{
  "jlp_amount": 50000,           // JLP持仓量
  "alp_amount": 10000,           // ALP持仓量
  "threshold_min": 1.0,          // 最小触发阈值 1%
  "threshold_max": 2.0,          // 最大告警阈值 2%
  "threshold_step": 0.2,         // 区间步长 0.2%
  "order_price_offset": 0.2,     // 挂单价格偏移 0.2%
  "close_ratio": 40.0,           // 每次平仓比例 40%
  "timeout_minutes": 20,         // 超时分钟数
  "check_interval_seconds": 60,  // 检查间隔（秒）

  "exchange": {
    "name": "lighter",           // 或 "mock" 用于测试
    "private_key": "",
    "account_index": 0,
    "api_key_index": 0
  }
}
```

### 环境变量优先级

```
环境变量 > config.json > 默认值
```

推荐：
- 敏感信息（私钥）→ 环境变量
- 策略参数 → config.json

## 📁 项目结构

```
xLP/
├── src/                        # 核心代码
│   ├── jlp_hedge.py           # JLP对冲计算
│   ├── alp_hedge.py           # ALP对冲计算
│   ├── offset_tracker.py      # 偏移追踪算法（原子模块）
│   ├── hedge_engine.py        # 对冲引擎
│   ├── lighter_integration.py # Lighter集成
│   ├── exchange_interface.py  # 交易所抽象
│   ├── notifier.py            # Pushover通知
│   └── main.py                # 主程序
│
├── tests/                      # 测试套件
│   ├── test_cost_tracking.py
│   ├── test_cost_detailed.py
│   └── test_10_steps.py
│
├── docs/                       # 文档
│   └── ARCHITECTURE.md
│
├── Dockerfile                  # Docker镜像
├── docker-compose.yml          # 部署配置
├── requirements.txt            # 依赖
├── config.json                 # 配置文件
├── .env.example               # 环境变量模板
│
└── README.md                   # 项目说明
```

## 🛡️ 安全建议

1. **私钥管理**
   ```bash
   # .env文件权限
   chmod 600 .env

   # 永不提交私钥
   git status | grep .env  # 应该看不到
   ```

2. **Testnet先测试**
   ```env
   EXCHANGE_BASE_URL=https://testnet.zklighter.elliot.ai
   ```

3. **小额开始**
   - 初始使用少量资金
   - 验证24小时稳定运行
   - 逐步增加规模

## 📊 运维命令

```bash
# 查看日志
docker-compose logs -f hedge-engine

# 查看状态
docker-compose ps

# 重启
docker-compose restart

# 停止
docker-compose down

# 更新代码
git pull origin master
docker-compose up -d --build

# 备份状态
cp data/state.json data/state.json.backup.$(date +%Y%m%d_%H%M%S)

# 查看容器资源
docker stats xlp-hedge-engine
```

## 🐛 故障排查

### 1. 容器启动失败

```bash
# 查看详细错误
docker-compose logs hedge-engine

# 验证配置
docker-compose config
```

### 2. Lighter连接失败

```bash
# 测试私钥
python test_lighter.py

# 检查网络
docker exec xlp-hedge-engine ping -c 3 mainnet.zklighter.elliot.ai
```

### 3. 状态文件问题

```bash
# 恢复备份
cp data/state.json.backup data/state.json
docker-compose restart
```

## 📈 监控指标

### 关键日志

```bash
# 查看偏移变化
docker logs xlp-hedge-engine | grep "offset="

# 查看订单
docker logs xlp-hedge-engine | grep "订单"

# 查看错误
docker logs xlp-hedge-engine | grep ERROR
```

### 状态检查

```bash
# 查看当前状态
cat data/state.json | jq .

# 查看最后检查时间
cat data/state.json | jq .last_check
```

## 🔗 相关链接

- **GitHub**: https://github.com/giraphant/xLP
- **Lighter官网**: https://lighter.xyz
- **参考项目**: https://github.com/your-quantguy/perp-dex-tools

## 📝 待办事项

- [ ] 完成Testnet测试
- [ ] 配置Pushover通知
- [ ] 设置监控告警
- [ ] 生产环境部署
- [ ] 性能优化

## 💡 最佳实践

1. **渐进式部署**
   - Testnet → 小额主网 → 全量

2. **定期检查**
   - 每日查看日志
   - 每周备份状态
   - 每月性能评估

3. **风险控制**
   - 设置止损阈值
   - 监控异常波动
   - 保持流动性储备

---

## ✅ 检查清单

上线前确认：

- [ ] Lighter私钥已配置
- [ ] 已在testnet测试通过
- [ ] Pushover通知正常
- [ ] 状态文件可读写
- [ ] 日志正常输出
- [ ] Docker容器健康
- [ ] 资金安全检查完成

**准备就绪？开始部署！** 🚀

```bash
docker-compose up -d
docker-compose logs -f
```
