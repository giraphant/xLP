#!/usr/bin/env python3
"""
极简异常处理 - Linus风格

只需要3个异常类：
1. HedgeError - 业务逻辑错误
2. ExchangeError - 交易所API错误
3. ConfigError - 配置错误

不需要40个异常类的继承层次！
"""


class HedgeError(Exception):
    """业务逻辑错误"""
    pass


class ExchangeError(Exception):
    """交易所API错误"""
    pass


class ConfigError(Exception):
    """配置错误"""
    pass
