# syntax=docker/dockerfile:1
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖（git用于安装Lighter SDK，gcc用于编译，procps用于健康检查）
# 添加重试逻辑以应对网络不稳定
RUN apt-get update --fix-missing || apt-get update && \
    apt-get install -y --no-install-recommends \
    git \
    gcc \
    procps \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖（使用缓存挂载加速二次构建）
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# 复制源代码
COPY src/ ./src/

# 创建必要的目录（用于volume挂载）
RUN mkdir -p /app/logs

# 设置环境变量默认值
ENV PYTHONUNBUFFERED=1 \
    LOG_LEVEL=INFO \
    CHECK_INTERVAL_SECONDS=60

# 运行主程序
CMD ["python", "-u", "src/main.py"]
