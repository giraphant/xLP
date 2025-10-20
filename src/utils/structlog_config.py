#!/usr/bin/env python3
"""
Structlog 配置 - 结构化日志系统
增强标准 logging，支持 JSON 格式和上下文绑定
"""

import sys
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler

import structlog


def setup_structlog(
    log_level: str = "INFO",
    log_file: str = None,
    use_json: bool = False,
    rotation_type: str = "time",
    retention_days: int = 7,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    enable_console: bool = True
):
    """
    配置 Structlog 结构化日志系统

    Args:
        log_level: 日志级别
        log_file: 日志文件路径（可选）
        use_json: 是否使用 JSON 格式输出
        rotation_type: 轮转类型 ("time" 或 "size")
        retention_days: 时间轮转模式下保留天数
        max_bytes: 大小轮转模式下的最大字节数
        backup_count: 备份文件数量
        enable_console: 是否输出到控制台
    """

    # 解析日志级别
    level = getattr(logging, log_level.upper(), logging.INFO)

    # ==================== 配置标准 logging ====================

    # 清除现有配置
    logging.root.handlers.clear()
    logging.root.setLevel(level)

    # 创建 handlers
    handlers = []

    # 控制台 handler
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        handlers.append(console_handler)

    # 文件 handler（带轮转）
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        if rotation_type == "time":
            file_handler = TimedRotatingFileHandler(
                filename=log_file,
                when='midnight',
                interval=1,
                backupCount=retention_days,
                encoding='utf-8',
                utc=True
            )
        else:
            file_handler = RotatingFileHandler(
                filename=log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )

        file_handler.setLevel(level)
        handlers.append(file_handler)

    # ==================== 配置 Structlog ====================

    # 选择渲染器
    if use_json:
        # JSON 格式 - 适合日志聚合系统（ELK, Loki）
        renderer = structlog.processors.JSONRenderer()
    else:
        # 人类可读格式 - 适合开发和调试
        renderer = structlog.dev.ConsoleRenderer(
            colors=True if enable_console else False
        )

    # 配置 Structlog 处理器
    shared_processors = [
        # 添加日志级别
        structlog.stdlib.add_log_level,
        # 添加时间戳
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        # 添加调用者信息（文件名、行号、函数名）
        structlog.processors.CallsiteParameterAdder(
            [
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.LINENO,
                structlog.processors.CallsiteParameter.FUNC_NAME,
            ]
        ),
        # 添加异常信息
        structlog.processors.format_exc_info,
        # 添加栈信息（仅在异常时）
        structlog.processors.StackInfoRenderer(),
    ]

    # 配置 Structlog
    structlog.configure(
        processors=shared_processors + [
            # 传递给标准 logging
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # 配置标准 logging 使用 Structlog 格式化
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            # 移除 _record 和 _from_structlog
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            # 渲染输出
            renderer,
        ],
    )

    # 应用格式化到所有 handlers
    for handler in handlers:
        handler.setFormatter(formatter)
        logging.root.addHandler(handler)

    # 禁用第三方库的 DEBUG 日志
    for lib in ["httpcore", "httpx", "urllib3", "lighter", "apprise"]:
        logging.getLogger(lib).setLevel(logging.WARNING)

    # 返回一个 structlog logger 示例
    logger = structlog.get_logger()
    logger.info(
        "structlog_configured",
        log_level=log_level,
        use_json=use_json,
        log_file=log_file
    )

    return logger


def get_logger(name: str = None):
    """
    获取 Structlog logger

    Args:
        name: Logger 名称（可选）

    Returns:
        Structlog logger 实例

    Example:
        logger = get_logger(__name__)
        logger.info("order_placed", symbol="SOL", quantity=10.5)
    """
    return structlog.get_logger(name)


def bind_context(**kwargs):
    """
    绑定全局上下文

    所有后续日志都会自动包含这些字段

    Example:
        bind_context(service="hedge_engine", version="2.0")
        logger.info("started")  # 自动包含 service 和 version
    """
    logger = structlog.get_logger()
    return logger.bind(**kwargs)


# ==================== 便捷的日志函数 ====================

def log_order(symbol: str, side: str, quantity: float, price: float, **extra):
    """记录订单日志"""
    logger = get_logger()
    logger.info(
        "order_event",
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        **extra
    )


def log_error(error_type: str, message: str, **extra):
    """记录错误日志"""
    logger = get_logger()
    logger.error(
        "error_event",
        error_type=error_type,
        message=message,
        **extra
    )


def log_metric(metric_name: str, value: float, **labels):
    """记录指标日志"""
    logger = get_logger()
    logger.debug(
        "metric_event",
        metric=metric_name,
        value=value,
        **labels
    )
