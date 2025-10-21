#!/usr/bin/env python3
"""
日志系统配置
使用 structlog 增强标准 logging，支持彩色输出、JSON 格式和日志轮转
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
    # 注意：移除了 CallsiteParameterAdder（文件名、行号、函数名）以提高可读性
    # 如果需要调试信息，可以临时启用或查看异常的 stack trace
    shared_processors = [
        # 添加日志级别
        structlog.stdlib.add_log_level,
        # 添加时间戳
        structlog.processors.TimeStamper(fmt="iso", utc=True),
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
