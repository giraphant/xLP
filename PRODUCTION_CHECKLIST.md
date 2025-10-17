# 生产环境部署清单

## 🔴 阶段 1：必须完成（Critical - 无法运行）

### 1.1 Lighter 交易所集成 ⚠️ **最高优先级**
**当前状态：** `src/exchange_interface.py` 中 LighterExchange 全是空实现

**需要实现：**
- [ ] Lighter API 客户端初始化
- [ ] 认证和签名机制
- [ ] `get_position()` - 获取持仓
- [ ] `get_price()` - 获取市场价格
- [ ] `place_limit_order()` - 下限价单
- [ ] `place_market_order()` - 下市价单
- [ ] `cancel_order()` - 撤单
- [ ] `get_order_status()` - 查询订单状态
- [ ] 错误处理和重试逻辑
- [ ] API 速率限制处理

**参考资源：**
- Lighter API 文档
- Lighter Python SDK（如果有）

### 1.2 环境配置系统
- [ ] 安装 python-dotenv: `pip install python-dotenv`
- [ ] 修改 `config.json` 支持环境变量
- [ ] 或创建新的配置加载器支持 .env
- [ ] 复制 `.env.example` 为 `.env` 并填写真实密钥
- [ ] 确保 `.env` 在 `.gitignore` 中

### 1.3 基础日志系统
- [ ] 添加 Python logging 配置
- [ ] 日志输出到文件（`logs/hedge_engine.log`）
- [ ] 日志级别配置（INFO/DEBUG/ERROR）
- [ ] 关键操作日志记录

**代码示例：**
```python
import logging
from logging.handlers import RotatingFileHandler

# 创建 logs 目录
Path("logs").mkdir(exist_ok=True)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(
            'logs/hedge_engine.log',
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        ),
        logging.StreamHandler()
    ]
)
```

---

## 🟡 阶段 2：重要（High Priority - 生产运行需要）

### 2.1 监控和告警增强
- [ ] 添加健康检查函数
- [ ] 资金安全检查（最大持仓限制）
- [ ] 异常情况 Pushover 告警
- [ ] 每日运行报告

### 2.2 错误处理加强
- [ ] 网络异常重试（指数退避）
- [ ] API 调用失败处理
- [ ] 状态文件损坏恢复
- [ ] 优雅降级机制

### 2.3 服务化部署
创建 systemd service 文件：

**`/etc/systemd/system/xlp-hedge.service`:**
```ini
[Unit]
Description=xLP Solana LP Hedge Engine
After=network.target

[Service]
Type=simple
User=xlp
WorkingDirectory=/opt/xLP
Environment="PATH=/opt/xLP/venv/bin:/usr/bin"
ExecStart=/opt/xLP/venv/bin/python src/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**部署步骤：**
```bash
# 1. 创建专用用户
sudo useradd -r -s /bin/bash xlp

# 2. 部署代码
sudo mkdir -p /opt/xLP
sudo cp -r /home/xLP/* /opt/xLP/
sudo chown -R xlp:xlp /opt/xLP

# 3. 安装依赖
cd /opt/xLP
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
sudo chmod 600 .env
# 编辑 .env 填入真实密钥

# 5. 启动服务
sudo systemctl daemon-reload
sudo systemctl enable xlp-hedge
sudo systemctl start xlp-hedge

# 6. 查看状态
sudo systemctl status xlp-hedge
sudo journalctl -u xlp-hedge -f
```

### 2.4 安全加固
- [ ] API Key 使用环境变量，不提交到 Git
- [ ] 文件权限设置（.env 设为 600）
- [ ] 运行时使用非 root 用户
- [ ] 审计日志（谁何时做了什么操作）

---

## 🟢 阶段 3：优化（Nice to Have - 提升可靠性）

### 3.1 性能优化
- [ ] 连接池管理
- [ ] 价格数据缓存（避免频繁请求）
- [ ] 批量操作优化

### 3.2 备份和恢复
- [ ] 定时备份 state.json
- [ ] 配置文件备份
- [ ] 灾难恢复脚本

### 3.3 监控仪表板（可选）
- [ ] Prometheus metrics 导出
- [ ] Grafana 可视化
- [ ] 告警规则配置

### 3.4 测试增强
- [ ] 集成测试（使用 Lighter testnet）
- [ ] 压力测试
- [ ] 故障注入测试

---

## 📋 上线前检查清单

### 环境检查
- [ ] Python 3.9+ 已安装
- [ ] 所有依赖已安装 (`pip install -r requirements.txt`)
- [ ] .env 文件已配置并包含所有必要密钥
- [ ] Lighter API 测试网测试通过
- [ ] Pushover 通知测试通过

### 功能检查
- [ ] JLP hedge 计算正确
- [ ] ALP hedge 计算正确
- [ ] 偏移追踪算法验证通过（运行测试套件）
- [ ] 订单下单/撤单正常
- [ ] 状态持久化正常

### 安全检查
- [ ] API keys 安全存储
- [ ] 文件权限正确设置
- [ ] 非 root 用户运行
- [ ] 日志不包含敏感信息

### 监控检查
- [ ] 日志系统正常工作
- [ ] Pushover 告警正常
- [ ] 进程监控配置（systemd）
- [ ] 磁盘空间监控

### 资金安全
- [ ] 初始测试使用小额资金
- [ ] 最大持仓限制已设置
- [ ] 紧急停止机制测试
- [ ] 回滚方案准备

---

## 🚀 快速启动（开发环境）

```bash
# 1. 克隆仓库
git clone https://github.com/giraphant/xLP.git
cd xLP

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境
cp .env.example .env
# 编辑 .env 填入配置

# 4. 运行测试
python tests/test_cost_tracking.py

# 5. 启动引擎（使用 Mock 交易所测试）
# 修改 config.json: "exchange": {"name": "mock"}
python src/main.py
```

---

## ⚠️ 风险提示

1. **交易所集成是最大风险点**
   - 必须在 testnet 充分测试
   - 确保订单逻辑正确
   - 错误处理要健壮

2. **资金安全**
   - 初期使用小额测试
   - 设置止损阈值
   - 24/7 监控

3. **API 限制**
   - 注意 Lighter API 速率限制
   - 实现请求队列
   - 避免被封禁

4. **状态一致性**
   - 确保 state.json 正确保存
   - 实现故障恢复
   - 定期备份

---

## 📞 需要帮助？

如果在部署过程中遇到问题：

1. 检查日志：`sudo journalctl -u xlp-hedge -n 100`
2. 查看状态：`sudo systemctl status xlp-hedge`
3. 验证配置：确保 .env 和 config.json 正确
4. 测试 API：单独测试 Lighter API 连接

**下一步行动：**
👉 **立即开始实现 LighterExchange 类**
