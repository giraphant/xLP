#!/usr/bin/env python3
"""
熔断器机制 - 防止级联失败
当某个服务连续失败时，自动熔断，避免持续请求失败的服务
"""

import asyncio
import time
import logging
from enum import Enum
from typing import Any, Callable, Optional, Dict
from datetime import datetime, timedelta
from collections import deque

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"      # 正常工作
    OPEN = "open"          # 熔断开启，拒绝所有请求
    HALF_OPEN = "half_open"  # 半开状态，允许少量测试请求


class CircuitBreakerError(Exception):
    """熔断器异常基类"""
    pass


class CircuitOpenError(CircuitBreakerError):
    """熔断器开启异常"""

    def __init__(self, service: str, retry_after: Optional[int] = None):
        self.service = service
        self.retry_after = retry_after
        message = f"Circuit breaker is OPEN for {service}"
        if retry_after:
            message += f" (retry after {retry_after}s)"
        super().__init__(message)


class CircuitBreaker:
    """
    熔断器实现

    特性：
    - 三种状态：关闭（正常）、开启（熔断）、半开（测试）
    - 自动状态转换
    - 失败率统计
    - 指数退避重试
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        timeout: int = 60,
        half_open_timeout: int = 30,
        failure_rate_threshold: float = 0.5,
        min_calls: int = 10
    ):
        """
        Args:
            name: 熔断器名称（通常是服务名）
            failure_threshold: 连续失败次数阈值
            success_threshold: 半开状态下成功次数阈值
            timeout: 开启状态持续时间（秒）
            half_open_timeout: 半开状态超时时间（秒）
            failure_rate_threshold: 失败率阈值（0-1）
            min_calls: 计算失败率的最小调用次数
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.timeout = timeout
        self.half_open_timeout = half_open_timeout
        self.failure_rate_threshold = failure_rate_threshold
        self.min_calls = min_calls

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.last_success_time = None
        self.state_changed_at = time.time()

        # 统计窗口（用于计算失败率）
        self.call_results = deque(maxlen=100)  # 最近100次调用结果
        self.half_open_start = None

        # 状态变化回调
        self.state_listeners = []

        logger.info(f"Circuit breaker '{name}' initialized with threshold={failure_threshold}, timeout={timeout}s")

    @property
    def is_closed(self) -> bool:
        """是否处于关闭状态（正常）"""
        return self.state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        """是否处于开启状态（熔断）"""
        return self.state == CircuitState.OPEN

    @property
    def is_half_open(self) -> bool:
        """是否处于半开状态（测试）"""
        return self.state == CircuitState.HALF_OPEN

    def _calculate_failure_rate(self) -> float:
        """计算失败率"""
        if len(self.call_results) < self.min_calls:
            return 0.0

        failures = sum(1 for result in self.call_results if not result)
        return failures / len(self.call_results)

    def _should_open(self) -> bool:
        """判断是否应该开启熔断"""
        # 连续失败次数检查
        if self.failure_count >= self.failure_threshold:
            return True

        # 失败率检查
        failure_rate = self._calculate_failure_rate()
        if len(self.call_results) >= self.min_calls and failure_rate >= self.failure_rate_threshold:
            return True

        return False

    def _should_attempt_reset(self) -> bool:
        """判断是否应该尝试重置（从开启转为半开）"""
        if self.state != CircuitState.OPEN:
            return False

        elapsed = time.time() - self.state_changed_at
        return elapsed >= self.timeout

    def _should_close(self) -> bool:
        """判断是否应该关闭（从半开转为关闭）"""
        if self.state != CircuitState.HALF_OPEN:
            return False

        return self.success_count >= self.success_threshold

    def _should_reopen(self) -> bool:
        """判断是否应该重新开启（从半开转回开启）"""
        if self.state != CircuitState.HALF_OPEN:
            return False

        # 半开状态下任何失败都重新开启
        if self.failure_count > 0:
            return True

        # 半开状态超时
        if self.half_open_start:
            elapsed = time.time() - self.half_open_start
            if elapsed >= self.half_open_timeout:
                return True

        return False

    def _change_state(self, new_state: CircuitState, reason: str = ""):
        """改变状态"""
        old_state = self.state
        self.state = new_state
        self.state_changed_at = time.time()

        if new_state == CircuitState.HALF_OPEN:
            self.half_open_start = time.time()
            self.success_count = 0
            self.failure_count = 0
        elif new_state == CircuitState.CLOSED:
            self.success_count = 0
            self.failure_count = 0
            self.half_open_start = None
        elif new_state == CircuitState.OPEN:
            self.half_open_start = None

        logger.info(f"Circuit breaker '{self.name}' state changed: {old_state.value} -> {new_state.value} ({reason})")

        # 通知监听器
        for listener in self.state_listeners:
            try:
                listener(self.name, old_state, new_state)
            except Exception as e:
                logger.error(f"Error in state listener: {e}")

    def add_state_listener(self, listener: Callable[[str, CircuitState, CircuitState], None]):
        """添加状态变化监听器"""
        self.state_listeners.append(listener)

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        通过熔断器调用函数

        Args:
            func: 要调用的异步函数
            *args: 函数参数
            **kwargs: 函数关键字参数

        Returns:
            函数返回值

        Raises:
            CircuitOpenError: 熔断器开启
            原函数的异常
        """
        # 检查是否应该尝试重置
        if self._should_attempt_reset():
            self._change_state(CircuitState.HALF_OPEN, "Timeout expired, attempting reset")

        # 如果熔断器开启，直接拒绝
        if self.state == CircuitState.OPEN:
            retry_after = max(0, int(self.timeout - (time.time() - self.state_changed_at)))
            raise CircuitOpenError(self.name, retry_after)

        # 半开状态下限制请求数量
        if self.state == CircuitState.HALF_OPEN and self.success_count + self.failure_count >= 3:
            # 在半开状态下只允许少量测试请求
            if self._should_close():
                self._change_state(CircuitState.CLOSED, "Test requests successful")
            elif self._should_reopen():
                self._change_state(CircuitState.OPEN, "Test requests failed")
                raise CircuitOpenError(self.name, self.timeout)

        # 执行函数调用
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure(e)
            raise

    def _on_success(self):
        """成功调用的处理"""
        self.success_count += 1
        self.failure_count = 0  # 重置连续失败计数
        self.last_success_time = time.time()
        self.call_results.append(True)

        if self.state == CircuitState.HALF_OPEN:
            if self._should_close():
                self._change_state(CircuitState.CLOSED, f"Success threshold ({self.success_threshold}) reached")

    def _on_failure(self, exception: Exception):
        """失败调用的处理"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        self.call_results.append(False)

        logger.warning(f"Circuit breaker '{self.name}' recorded failure #{self.failure_count}: {exception}")

        if self.state == CircuitState.HALF_OPEN:
            self._change_state(CircuitState.OPEN, "Failed during half-open test")
        elif self.state == CircuitState.CLOSED:
            if self._should_open():
                self._change_state(CircuitState.OPEN, f"Failure threshold ({self.failure_threshold}) reached")

    def reset(self):
        """手动重置熔断器"""
        self._change_state(CircuitState.CLOSED, "Manual reset")
        self.failure_count = 0
        self.success_count = 0
        self.call_results.clear()
        logger.info(f"Circuit breaker '{self.name}' manually reset")

    def get_stats(self) -> Dict[str, Any]:
        """获取熔断器统计信息"""
        stats = {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "failure_rate": self._calculate_failure_rate(),
            "total_calls": len(self.call_results),
            "state_duration": time.time() - self.state_changed_at
        }

        if self.last_failure_time:
            stats["last_failure"] = datetime.fromtimestamp(self.last_failure_time).isoformat()

        if self.last_success_time:
            stats["last_success"] = datetime.fromtimestamp(self.last_success_time).isoformat()

        if self.state == CircuitState.OPEN:
            stats["retry_after"] = max(0, int(self.timeout - (time.time() - self.state_changed_at)))

        return stats


class CircuitBreakerManager:
    """
    熔断器管理器 - 集中管理多个熔断器

    用于管理不同服务的熔断器
    """

    def __init__(self):
        self.breakers: Dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(
        self,
        name: str,
        failure_threshold: int = 5,
        timeout: int = 60,
        **kwargs
    ) -> CircuitBreaker:
        """
        获取或创建熔断器

        Args:
            name: 熔断器名称
            failure_threshold: 失败阈值
            timeout: 熔断超时时间
            **kwargs: 其他CircuitBreaker参数

        Returns:
            熔断器实例
        """
        async with self._lock:
            if name not in self.breakers:
                self.breakers[name] = CircuitBreaker(
                    name=name,
                    failure_threshold=failure_threshold,
                    timeout=timeout,
                    **kwargs
                )
            return self.breakers[name]

    def get(self, name: str) -> Optional[CircuitBreaker]:
        """获取熔断器"""
        return self.breakers.get(name)

    def reset(self, name: str) -> bool:
        """重置特定熔断器"""
        breaker = self.get(name)
        if breaker:
            breaker.reset()
            return True
        return False

    def reset_all(self):
        """重置所有熔断器"""
        for breaker in self.breakers.values():
            breaker.reset()

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有熔断器的统计信息"""
        return {
            name: breaker.get_stats()
            for name, breaker in self.breakers.items()
        }

    def get_open_breakers(self) -> list:
        """获取所有开启的熔断器"""
        return [
            name for name, breaker in self.breakers.items()
            if breaker.is_open
        ]

    def cleanup_idle(self, idle_time: int = 3600):
        """
        清理空闲的熔断器

        Args:
            idle_time: 空闲时间阈值（秒）
        """
        current_time = time.time()
        to_remove = []

        for name, breaker in self.breakers.items():
            # 如果熔断器长时间处于关闭状态且无调用，则清理
            if breaker.is_closed:
                last_activity = max(
                    breaker.last_success_time or 0,
                    breaker.last_failure_time or 0,
                    breaker.state_changed_at
                )
                if current_time - last_activity > idle_time:
                    to_remove.append(name)

        for name in to_remove:
            del self.breakers[name]
            logger.info(f"Cleaned up idle circuit breaker: {name}")


# 全局熔断器管理器实例
circuit_breaker_manager = CircuitBreakerManager()