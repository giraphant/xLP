FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖（git用于安装Lighter SDK，gcc用于编译）
RUN apt-get update && apt-get install -y \
    git \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制源代码
COPY src/ ./src/
COPY state_template.json .

# config.json是可选的（环境变量优先）
COPY config.json* ./ || true

# 创建状态文件目录（用于volume挂载）
RUN mkdir -p /app/data /app/logs

# 设置环境变量默认值
ENV PYTHONUNBUFFERED=1 \
    LOG_LEVEL=INFO \
    CHECK_INTERVAL_SECONDS=60

# 健康检查
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import json; print(json.load(open('/app/data/state.json'))['last_check'])" || exit 1

# 运行主程序
CMD ["python", "-u", "src/main.py"]
