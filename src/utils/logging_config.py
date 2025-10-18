#!/usr/bin/env python3
"""
日志配置模块 - 统一管理日志格式和轮转
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(
    log_level: str = "INFO",
    log_file: str = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    enable_console: bool = True
):
    """
    配置日志系统

    Args:
        log_level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: 日志文件路径（可选）
        max_bytes: 单个日志文件最大大小
        backup_count: 保留的备份文件数量
        enable_console: 是否输出到控制台
    """
    # 解析日志级别
    level = getattr(logging, log_level.upper(), logging.INFO)

    # 创建根logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 清除现有handlers
    root_logger.handlers.clear()

    # 日志格式
    # 简化格式：移除过多emoji，保持可读性
    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 控制台输出
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # 文件输出（带轮转）
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            filename=log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # 禁用第三方库的DEBUG日志
    for lib in ["httpcore", "httpx", "urllib3", "lighter"]:
        logging.getLogger(lib).setLevel(logging.WARNING)

    return root_logger


def get_structured_logger(name: str):
    """
    获取结构化logger（预留，未来可添加JSON格式）

    Args:
        name: Logger名称

    Returns:
        logging.Logger
    """
    return logging.getLogger(name)
