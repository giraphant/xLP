#!/usr/bin/env python3
"""
错误处理分层机制
定义不同级别的异常，便于精确处理各种错误情况
"""

from typing import Optional, Dict, Any
from enum import Enum


class ErrorSeverity(Enum):
    """错误严重程度"""
    LOW = "low"        # 可忽略，不影响运行
    MEDIUM = "medium"  # 需要重试
    HIGH = "high"      # 需要人工干预
    CRITICAL = "critical"  # 需要停机


class HedgeEngineError(Exception):
    """
    对冲引擎基础异常类

    所有自定义异常都应继承此类
    """

    severity: ErrorSeverity = ErrorSeverity.MEDIUM
    retry_after: int = 5  # 默认重试延迟（秒）
    max_retries: int = 3  # 最大重试次数
    should_notify: bool = False  # 是否需要通知

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self):
        if self.details:
            return f"{self.message} - Details: {self.details}"
        return self.message


# ==================== 链上数据相关异常 ====================

class ChainError(HedgeEngineError):
    """链上操作基础异常"""
    severity = ErrorSeverity.MEDIUM
    retry_after = 10


class ChainConnectionError(ChainError):
    """链连接错误"""
    retry_after = 15
    max_retries = 5

    def __init__(self, rpc_url: str, original_error: Optional[Exception] = None):
        details = {"rpc_url": rpc_url}
        if original_error:
            details["original_error"] = str(original_error)
        super().__init__(f"Failed to connect to RPC: {rpc_url}", details)


class ChainReadError(ChainError):
    """链上数据读取错误"""
    retry_after = 5

    def __init__(self, account: str, reason: str, original_error: Optional[Exception] = None):
        details = {
            "account": account,
            "reason": reason
        }
        if original_error:
            details["original_error"] = str(original_error)
        super().__init__(f"Failed to read chain data for {account}: {reason}", details)


class InvalidChainDataError(ChainError):
    """链上数据无效"""
    severity = ErrorSeverity.HIGH
    should_notify = True
    max_retries = 1

    def __init__(self, data_type: str, value: Any, expected: str):
        super().__init__(
            f"Invalid chain data for {data_type}",
            {"type": data_type, "value": value, "expected": expected}
        )


# ==================== 交易所相关异常 ====================

class ExchangeError(HedgeEngineError):
    """交易所操作基础异常"""
    severity = ErrorSeverity.MEDIUM
    retry_after = 5


class ExchangeConnectionError(ExchangeError):
    """交易所连接错误"""
    retry_after = 10
    max_retries = 5

    def __init__(self, exchange: str, endpoint: str, original_error: Optional[Exception] = None):
        details = {
            "exchange": exchange,
            "endpoint": endpoint
        }
        if original_error:
            details["original_error"] = str(original_error)
        super().__init__(f"Failed to connect to {exchange}", details)


class OrderPlacementError(ExchangeError):
    """订单下单失败"""
    should_notify = True

    def __init__(self, symbol: str, side: str, size: float, reason: str):
        super().__init__(
            f"Failed to place order for {symbol}",
            {
                "symbol": symbol,
                "side": side,
                "size": size,
                "reason": reason
            }
        )


class OrderCancellationError(ExchangeError):
    """订单撤销失败"""
    retry_after = 3
    max_retries = 2

    def __init__(self, order_id: str, reason: str):
        super().__init__(
            f"Failed to cancel order {order_id}",
            {"order_id": order_id, "reason": reason}
        )


class InsufficientBalanceError(ExchangeError):
    """余额不足"""
    severity = ErrorSeverity.HIGH
    should_notify = True
    retry_after = 60
    max_retries = 1

    def __init__(self, symbol: str, required: float, available: float):
        super().__init__(
            f"Insufficient balance for {symbol}",
            {
                "symbol": symbol,
                "required": required,
                "available": available,
                "shortfall": required - available
            }
        )


class RateLimitError(ExchangeError):
    """请求频率限制"""
    severity = ErrorSeverity.LOW
    retry_after = 30

    def __init__(self, exchange: str, limit: Optional[int] = None):
        details = {"exchange": exchange}
        if limit:
            details["limit"] = limit
        super().__init__(f"Rate limited by {exchange}", details)


# ==================== 计算相关异常 ====================

class CalculationError(HedgeEngineError):
    """计算错误基础异常"""
    severity = ErrorSeverity.HIGH
    should_notify = True


class InvalidOffsetError(CalculationError):
    """无效的偏移量计算"""
    max_retries = 1

    def __init__(self, symbol: str, ideal: float, actual: float, offset: float):
        super().__init__(
            f"Invalid offset calculated for {symbol}",
            {
                "symbol": symbol,
                "ideal_position": ideal,
                "actual_position": actual,
                "calculated_offset": offset
            }
        )


class InvalidCostBasisError(CalculationError):
    """无效的成本基础"""
    max_retries = 1

    def __init__(self, symbol: str, cost: float, reason: str):
        super().__init__(
            f"Invalid cost basis for {symbol}: {cost}",
            {
                "symbol": symbol,
                "cost_basis": cost,
                "reason": reason
            }
        )


# ==================== 配置相关异常 ====================

class ConfigError(HedgeEngineError):
    """配置错误基础异常"""
    severity = ErrorSeverity.CRITICAL
    max_retries = 0  # 配置错误不重试


class MissingConfigError(ConfigError):
    """缺少必要配置"""

    def __init__(self, field: str, description: Optional[str] = None):
        message = f"Missing required configuration: {field}"
        if description:
            message += f" ({description})"
        super().__init__(message, {"field": field})


class InvalidConfigError(ConfigError):
    """配置值无效"""

    def __init__(self, field: str, value: Any, expected: str):
        super().__init__(
            f"Invalid configuration for {field}",
            {
                "field": field,
                "value": value,
                "expected": expected
            }
        )


# ==================== 状态相关异常 ====================

class StateError(HedgeEngineError):
    """状态管理错误"""
    severity = ErrorSeverity.HIGH


class StateCorruptionError(StateError):
    """状态文件损坏"""
    severity = ErrorSeverity.CRITICAL
    should_notify = True
    max_retries = 0

    def __init__(self, file_path: str, reason: str):
        super().__init__(
            f"State file corrupted: {file_path}",
            {"file_path": file_path, "reason": reason}
        )


class StateLockError(StateError):
    """状态锁定错误"""
    retry_after = 2
    max_retries = 5

    def __init__(self, operation: str):
        super().__init__(
            f"Failed to acquire state lock for: {operation}",
            {"operation": operation}
        )


# ==================== 严重错误 ====================

class CriticalError(HedgeEngineError):
    """
    严重错误 - 需要立即停机

    这类错误表示系统处于不一致状态，继续运行可能导致资金损失
    """
    severity = ErrorSeverity.CRITICAL
    should_notify = True
    max_retries = 0


class SystemInconsistencyError(CriticalError):
    """系统不一致错误"""

    def __init__(self, component: str, description: str):
        super().__init__(
            f"System inconsistency detected in {component}",
            {
                "component": component,
                "description": description
            }
        )


class SecurityError(CriticalError):
    """安全相关错误"""

    def __init__(self, issue: str):
        super().__init__(
            f"Security issue detected: {issue}",
            {"security_issue": issue}
        )


# ==================== 可恢复错误 ====================

class RecoverableError(HedgeEngineError):
    """
    可恢复错误 - 可以通过重试解决

    这类错误通常是临时性的，如网络问题、临时的服务不可用等
    """
    severity = ErrorSeverity.LOW
    retry_after = 5
    max_retries = 3


class TemporaryNetworkError(RecoverableError):
    """临时网络错误"""
    retry_after = 3

    def __init__(self, service: str, original_error: Optional[Exception] = None):
        details = {"service": service}
        if original_error:
            details["original_error"] = str(original_error)
        super().__init__(f"Temporary network error with {service}", details)


class ServiceUnavailableError(RecoverableError):
    """服务临时不可用"""
    retry_after = 10

    def __init__(self, service: str, estimated_recovery: Optional[int] = None):
        details = {"service": service}
        if estimated_recovery:
            details["estimated_recovery_seconds"] = estimated_recovery
            self.retry_after = estimated_recovery
        super().__init__(f"Service temporarily unavailable: {service}", details)


# ==================== 工具函数 ====================

def classify_exception(exception: Exception) -> HedgeEngineError:
    """
    将普通异常分类为对冲引擎异常

    Args:
        exception: 原始异常

    Returns:
        分类后的HedgeEngineError
    """
    # 如果已经是HedgeEngineError，直接返回
    if isinstance(exception, HedgeEngineError):
        return exception

    # 根据异常类型和消息进行分类
    exception_str = str(exception).lower()

    # 网络相关
    if any(keyword in exception_str for keyword in ["connection", "timeout", "network"]):
        return TemporaryNetworkError("unknown", exception)

    # 权限相关
    if any(keyword in exception_str for keyword in ["permission", "forbidden", "unauthorized"]):
        return SecurityError(str(exception))

    # JSON解析相关
    if "json" in exception_str:
        return StateCorruptionError("unknown", str(exception))

    # 默认作为可恢复错误处理
    return RecoverableError(f"Unclassified error: {exception}")


def should_retry(exception: HedgeEngineError, attempt: int) -> bool:
    """
    判断是否应该重试

    Args:
        exception: 异常对象
        attempt: 当前尝试次数（从1开始）

    Returns:
        是否应该重试
    """
    return attempt <= exception.max_retries


def get_retry_delay(exception: HedgeEngineError, attempt: int) -> int:
    """
    获取重试延迟（秒）

    使用指数退避策略

    Args:
        exception: 异常对象
        attempt: 当前尝试次数（从1开始）

    Returns:
        延迟秒数
    """
    base_delay = exception.retry_after
    # 指数退避，但有上限
    return min(base_delay * (2 ** (attempt - 1)), 300)  # 最大5分钟