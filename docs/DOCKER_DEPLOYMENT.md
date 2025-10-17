# Docker 部署指南

## 📦 快速开始

### 1. 准备环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑.env填入真实配置
nano .env
```

**必须配置的变量：**
```env
# Lighter Exchange
EXCHANGE_NAME=lighter
EXCHANGE_API_KEY=your_api_key_here
EXCHANGE_API_SECRET=your_api_secret_here
EXCHANGE_TESTNET=true

# Pushover
PUSHOVER_USER_KEY=your_user_key
PUSHOVER_API_TOKEN=your_api_token

# JLP/ALP
JLP_AMOUNT=50000
ALP_AMOUNT=10000
```

### 2. 创建数据目录

```bash
# 创建持久化目录
mkdir -p data logs

# 初始化状态文件
cp state_template.json data/state.json
```

### 3. 构建并启动

```bash
# 构建镜像
docker-compose build

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f hedge-engine
```

---

## 🔧 配置说明

### 配置优先级

1. **环境变量** - 最高优先级（Docker推荐）
2. **config.json** - 静态配置
3. **默认值** - 代码中的默认值

### config.json vs 环境变量

**config.json** - 用于：
- 复杂的嵌套配置
- 多环境配置模板
- 版本控制的默认值

**环境变量** - 用于：
- 敏感信息（API keys）
- 部署特定配置
- 运行时参数

### 支持的环境变量

```bash
# Exchange
EXCHANGE_NAME=lighter|mock
EXCHANGE_API_KEY=xxx
EXCHANGE_API_SECRET=xxx
EXCHANGE_TESTNET=true|false

# Pushover
PUSHOVER_USER_KEY=xxx
PUSHOVER_API_TOKEN=xxx

# Holdings
JLP_AMOUNT=50000
ALP_AMOUNT=10000

# Thresholds
THRESHOLD_MIN=1.0
THRESHOLD_MAX=2.0
THRESHOLD_STEP=0.2
ORDER_PRICE_OFFSET=0.2
CLOSE_RATIO=40.0
TIMEOUT_MINUTES=20

# Runtime
CHECK_INTERVAL_SECONDS=60
LOG_LEVEL=INFO|DEBUG|ERROR
```

---

## 📊 日志管理

### 查看实时日志

```bash
# 查看所有日志
docker-compose logs -f

# 只看最近100行
docker-compose logs --tail=100 hedge-engine

# 查看特定时间范围
docker logs --since 30m xlp-hedge-engine
```

### 日志策略

**stdout/stderr（Docker收集）：**
- 实时运行状态
- INFO级别日志
- 适合 `docker logs` 查看

**文件日志（Volume持久化）：**
- 审计日志（所有交易操作）
- ERROR日志
- 保存在 `./logs/` 目录

### 日志轮转配置

Docker日志自动轮转（docker-compose.yml已配置）：
```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"    # 单文件最大10MB
    max-file: "3"       # 保留3个文件
```

---

## 💾 数据持久化

### Volume映射

```yaml
volumes:
  - ./data:/app/data        # 状态文件
  - ./logs:/app/logs        # 日志文件
  - ./config.json:/app/config.json:ro  # 只读配置
```

### 状态文件

**位置：** `./data/state.json`

**备份策略：**
```bash
# 手动备份
cp data/state.json data/state.json.backup.$(date +%Y%m%d_%H%M%S)

# 定时备份（crontab）
0 */6 * * * cp /path/to/xLP/data/state.json /path/to/backups/state.json.$(date +\%Y\%m\%d_\%H\%M\%S)
```

---

## 🚀 运维命令

### 启动/停止

```bash
# 启动
docker-compose up -d

# 停止
docker-compose down

# 重启
docker-compose restart

# 重新构建并启动
docker-compose up -d --build
```

### 健康检查

```bash
# 查看容器状态
docker-compose ps

# 查看健康状态
docker inspect xlp-hedge-engine | jq '.[0].State.Health'

# 手动健康检查
docker exec xlp-hedge-engine python -c "import json; print(json.load(open('/app/data/state.json'))['last_check'])"
```

### 进入容器调试

```bash
# 进入容器shell
docker exec -it xlp-hedge-engine bash

# 查看Python进程
docker exec xlp-hedge-engine ps aux

# 查看文件
docker exec xlp-hedge-engine ls -la /app/data/
```

---

## 🔄 更新部署

### 代码更新流程

```bash
# 1. 拉取最新代码
git pull origin main

# 2. 停止服务
docker-compose down

# 3. 重新构建
docker-compose build --no-cache

# 4. 启动服务
docker-compose up -d

# 5. 验证
docker-compose logs -f hedge-engine
```

### 配置更新

**环境变量更新：**
```bash
# 1. 修改.env
nano .env

# 2. 重启服务
docker-compose restart
```

**config.json更新：**
```bash
# 1. 修改config.json
nano config.json

# 2. 重启服务（配置是只读挂载，需要重启）
docker-compose restart
```

---

## 🛡️ 安全最佳实践

### 1. 环境变量安全

```bash
# .env文件权限
chmod 600 .env

# 永不提交.env到Git
git ls-files | grep .env  # 应该为空

# 使用Docker secrets（生产环境）
docker secret create lighter_api_key ./api_key.txt
```

### 2. 容器安全

```bash
# 以非root用户运行（修改Dockerfile）
RUN useradd -m -u 1000 xlp
USER xlp

# 只读文件系统
docker run --read-only -v /app/data:/app/data ...
```

### 3. 网络隔离

```yaml
# docker-compose.yml
networks:
  xlp-net:
    driver: bridge
    internal: true  # 隔离外部网络（如果不需要出站）
```

---

## 📈 监控集成

### Prometheus Metrics（可选）

```python
# 在代码中添加metrics导出
from prometheus_client import start_http_server, Counter, Gauge

orders_total = Counter('xlp_orders_total', 'Total orders placed')
offset_gauge = Gauge('xlp_offset', 'Current offset', ['symbol'])

# 启动metrics服务器
start_http_server(9100)
```

```yaml
# docker-compose.yml添加
ports:
  - "9100:9100"  # Prometheus metrics
```

### 告警示例

```bash
# 简单的健康监控脚本
#!/bin/bash
if ! docker-compose ps | grep -q "Up"; then
    curl -X POST https://api.pushover.net/1/messages.json \
        -d "token=$PUSHOVER_TOKEN" \
        -d "user=$PUSHOVER_USER" \
        -d "message=xLP Hedge Engine is DOWN!"
fi
```

---

## 🐛 故障排查

### 常见问题

**1. 容器启动失败**
```bash
# 查看详细错误
docker-compose logs hedge-engine

# 检查配置文件
docker-compose config
```

**2. 状态文件损坏**
```bash
# 恢复备份
cp data/state.json.backup data/state.json
docker-compose restart
```

**3. API连接失败**
```bash
# 测试网络
docker exec xlp-hedge-engine ping -c 3 lighter.xyz

# 测试API（如果有测试脚本）
docker exec xlp-hedge-engine python scripts/test_api.py
```

**4. 内存/CPU过高**
```bash
# 查看资源使用
docker stats xlp-hedge-engine

# 限制资源
docker-compose.yml:
  deploy:
    resources:
      limits:
        cpus: '1.0'
        memory: 512M
```

---

## 🎯 生产环境部署

### 完整部署流程

```bash
# 1. 准备服务器
ssh user@production-server
sudo apt-get update && sudo apt-get install docker.io docker-compose

# 2. 克隆代码
git clone https://github.com/giraphant/xLP.git
cd xLP

# 3. 配置环境
cp .env.example .env
nano .env  # 填入生产配置

# 4. 创建数据目录
mkdir -p data logs
cp state_template.json data/state.json

# 5. 构建并启动
docker-compose up -d --build

# 6. 验证
docker-compose logs -f

# 7. 设置开机自启
sudo systemctl enable docker
```

### 监控和告警

```bash
# 设置定时检查（crontab）
*/5 * * * * /path/to/check_health.sh

# 日志监控
*/30 * * * * docker logs --since 30m xlp-hedge-engine | grep ERROR | mail -s "xLP Errors" admin@example.com
```

---

## 📝 总结

**优点：**
- ✅ 环境一致性
- ✅ 快速部署
- ✅ 易于扩展
- ✅ 日志集中管理
- ✅ 资源隔离

**注意事项：**
- ⚠️ 确保状态文件持久化
- ⚠️ 定期备份配置和状态
- ⚠️ 监控容器健康状态
- ⚠️ 保护敏感环境变量

**下一步：**
1. 完成 Lighter Exchange 集成
2. Testnet 测试
3. 生产环境部署
