#!/usr/bin/env python3
"""
对冲引擎异常定义

只保留实际使用的异常类，保持简洁
"""

from typing import Optional, Dict, Any


class HedgeEngineError(Exception):
    """对冲引擎基础异常"""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self):
        if self.details:
            return f"{self.message} - {self.details}"
        return self.message


class ConfigError(HedgeEngineError):
    """配置错误 - 严重，不可恢复"""
    pass


class InvalidConfigError(ConfigError):
    """配置值无效"""

    def __init__(self, field: str, value: Any, expected: str):
        super().__init__(
            f"Invalid config: {field}",
            {"field": field, "value": value, "expected": expected}
        )
