#!/usr/bin/env python3
"""
熔断器 - 使用 aiobreaker 成熟库（原生 asyncio 支持）
替代手写的 circuit_breaker.py (392行 → ~30行)
"""

import logging
from typing import Dict, Any, Optional
import aiobreaker

logger = logging.getLogger(__name__)


# ==================== 熔断器异常 ====================

# 重导出 aiobreaker 的异常，保持 API 兼容性
CircuitBreakerError = aiobreaker.CircuitBreakerError
CircuitOpenError = aiobreaker.CircuitBreakerError  # 兼容旧名称


# ==================== 状态监听器 ====================

class StateChangeListener(aiobreaker.CircuitBreakerListener):
    """熔断器状态变化监听器"""

    def state_change(self, breaker, old_state, new_state):
        """状态变化时调用"""
        logger.warning(
            f"Circuit breaker '{breaker.name}' state changed: "
            f"{old_state.name} -> {new_state.name}"
        )

    def before_call(self, breaker, func, *args, **kwargs):
        """调用前"""
        pass

    def success(self, breaker):
        """成功时"""
        pass

    def failure(self, breaker, exception):
        """失败时"""
        logger.debug(f"Circuit breaker '{breaker.name}' recorded failure: {exception}")


# ==================== 预定义熔断器 ====================

# 创建监听器实例
state_listener = StateChangeListener()

# 交易所 API 熔断器
exchange_breaker = aiobreaker.CircuitBreaker(
    fail_max=5,              # 连续失败 5 次后熔断
    reset_timeout=60,        # 熔断持续 60 秒
    name='exchange_api',
    listeners=[state_listener]
)

# Solana RPC 熔断器
rpc_breaker = aiobreaker.CircuitBreaker(
    fail_max=3,
    reset_timeout=30,
    name='solana_rpc',
    listeners=[state_listener]
)

# 池子数据获取熔断器
pool_data_breaker = aiobreaker.CircuitBreaker(
    fail_max=3,
    reset_timeout=45,
    name='pool_data',
    listeners=[state_listener]
)

# 通知服务熔断器
notification_breaker = aiobreaker.CircuitBreaker(
    fail_max=10,             # 通知失败容忍度更高
    reset_timeout=120,
    name='notification',
    listeners=[state_listener]
)


# ==================== aiobreaker 包装类 ====================

class AsyncCircuitBreakerWrapper:
    """
    aiobreaker 异步包装器 - 兼容旧 API

    提供 async def call() 方法来包装 aiobreaker 的 call()
    """

    def __init__(self, aiobreaker_instance: aiobreaker.CircuitBreaker):
        self._breaker = aiobreaker_instance

    async def call(self, func, *args, **kwargs):
        """
        通过熔断器调用异步函数（兼容旧 API）

        Args:
            func: 要调用的异步函数
            *args, **kwargs: 函数参数

        Returns:
            函数返回值

        Raises:
            CircuitBreakerError: 熔断器开启时
        """
        return await self._breaker.call(func, *args, **kwargs)

    @property
    def name(self):
        """获取熔断器名称"""
        return self._breaker.name

    @property
    def state(self):
        """获取熔断器状态"""
        return self._breaker.state


# ==================== 熔断器管理器 ====================

class CircuitBreakerManager:
    """
    熔断器管理器 - 兼容旧接口

    简化版本，使用 aiobreaker 预定义的熔断器
    """

    def __init__(self):
        """初始化熔断器管理器"""
        import asyncio
        self.breakers = {
            'exchange': exchange_breaker,
            'rpc': rpc_breaker,
            'pool_data': pool_data_breaker,
            'notification': notification_breaker,
        }
        self._lock = asyncio.Lock()
        logger.info("Circuit breaker manager initialized with aiobreaker")

    def get_breaker(self, name: str) -> aiobreaker.CircuitBreaker:
        """
        获取熔断器

        Args:
            name: 熔断器名称

        Returns:
            aiobreaker CircuitBreaker 实例
        """
        if name not in self.breakers:
            # 动态创建新熔断器
            self.breakers[name] = aiobreaker.CircuitBreaker(
                fail_max=5,
                reset_timeout=60,
                name=name,
                listeners=[state_listener]
            )
            logger.info(f"Created new circuit breaker: {name}")

        return self.breakers[name]

    async def call_with_breaker(self, name: str, func, *args, **kwargs):
        """
        使用熔断器调用函数（兼容旧接口）

        Args:
            name: 熔断器名称
            func: 要调用的函数
            *args, **kwargs: 函数参数

        Returns:
            函数返回值

        Raises:
            CircuitBreakerError: 熔断器开启时
        """
        breaker = self.get_breaker(name)

        # aiobreaker 的异步调用
        return await breaker.call(func, *args, **kwargs)

    def get_stats(self, name: str) -> Dict[str, Any]:
        """
        获取熔断器统计信息（兼容旧接口）

        Args:
            name: 熔断器名称

        Returns:
            包含状态和统计的字典
        """
        breaker = self.get_breaker(name)

        return {
            'name': breaker.name,
            'state': breaker.state.name,
            'failure_count': breaker.fail_counter,
            'is_open': breaker.state == aiobreaker.STATE_OPEN,
            'is_half_open': breaker.state == aiobreaker.STATE_HALF_OPEN,
            'is_closed': breaker.state == aiobreaker.STATE_CLOSED,
        }

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """
        获取所有熔断器的统计信息

        Returns:
            熔断器名称到统计信息的映射
        """
        return {
            name: self.get_stats(name)
            for name in self.breakers.keys()
        }

    def reset_breaker(self, name: str):
        """
        重置熔断器（兼容旧接口）

        Args:
            name: 熔断器名称
        """
        breaker = self.get_breaker(name)
        breaker.close()
        logger.info(f"Circuit breaker '{name}' has been reset")

    def reset_all(self):
        """重置所有熔断器"""
        for name, breaker in self.breakers.items():
            breaker.close()
            logger.info(f"Circuit breaker '{name}' has been reset")

    async def get_or_create(
        self,
        name: str,
        failure_threshold: int = 5,
        timeout: int = 60,
        **kwargs
    ) -> AsyncCircuitBreakerWrapper:
        """
        获取或创建熔断器（兼容旧接口）

        Args:
            name: 熔断器名称
            failure_threshold: 失败阈值（映射到 aiobreaker 的 fail_max）
            timeout: 熔断超时时间（映射到 aiobreaker 的 reset_timeout）
            **kwargs: 其他参数（忽略）

        Returns:
            包装后的熔断器实例
        """
        async with self._lock:
            if name not in self.breakers:
                # 动态创建新熔断器
                self.breakers[name] = aiobreaker.CircuitBreaker(
                    fail_max=failure_threshold,
                    reset_timeout=timeout,
                    name=name,
                    listeners=[state_listener]
                )
                logger.info(f"Created new circuit breaker: {name} (fail_max={failure_threshold}, reset_timeout={timeout}s)")

            # 返回包装后的熔断器
            return AsyncCircuitBreakerWrapper(self.breakers[name])


# ==================== 便捷装饰器 ====================

def with_circuit_breaker(breaker_name: str):
    """
    熔断器装饰器

    Args:
        breaker_name: 熔断器名称

    Example:
        @with_circuit_breaker('exchange')
        async def get_position():
            return await exchange.get_positions()
    """
    manager = CircuitBreakerManager()
    breaker = manager.get_breaker(breaker_name)

    def decorator(func):
        if hasattr(func, '__call__'):
            # 使用 PyBreaker 的装饰器
            return breaker(func)
        return func

    return decorator


# ==================== 全局实例 ====================

# 创建全局实例（单例模式）
_manager_instance = None


def get_circuit_manager() -> CircuitBreakerManager:
    """获取全局熔断器管理器实例"""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = CircuitBreakerManager()
    return _manager_instance
