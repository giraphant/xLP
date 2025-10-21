#!/usr/bin/env python3
"""
指标收集器 - 收集运行时指标

职责：
- 统计决策和执行次数
- 记录成功/失败率
- 生成指标摘要

特点：
- 内存统计
- 异步安全
- 可导出
"""

import asyncio
import logging
from typing import Dict, Any
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger(__name__)


class MetricsCollector:
    """
    指标收集器 - ~80行

    替代原来的PrometheusMetrics，简化为内存统计
    """

    def __init__(self):
        """初始化指标收集器"""
        self.metrics = defaultdict(int)
        self.lock = asyncio.Lock()
        self.start_time = datetime.now()

    async def record_decision(self, symbol: str, decision: Any, **kwargs):
        """
        记录决策指标

        Args:
            symbol: 币种符号
            decision: 决策对象
            **kwargs: 额外信息
        """
        async with self.lock:
            self.metrics["decisions_total"] += 1
            self.metrics[f"decisions_{decision.action}"] += 1
            self.metrics[f"decisions_{symbol}"] += 1

    async def record_action(self, symbol: str, action: str, result: dict, **kwargs):
        """
        记录执行指标

        Args:
            symbol: 币种符号
            action: 操作类型
            result: 执行结果
            **kwargs: 额外信息
        """
        async with self.lock:
            self.metrics["actions_total"] += 1
            self.metrics[f"actions_{action}"] += 1

            if result.get("success"):
                self.metrics["actions_success"] += 1
                self.metrics[f"actions_{action}_success"] += 1
            else:
                self.metrics["actions_failed"] += 1
                self.metrics[f"actions_{action}_failed"] += 1

    async def record_error(self, error: str, **kwargs):
        """
        记录错误指标

        Args:
            error: 错误信息
            **kwargs: 额外信息
        """
        async with self.lock:
            self.metrics["errors_total"] += 1

    async def get_summary(self) -> Dict[str, Any]:
        """
        获取指标摘要

        Returns:
            指标字典
        """
        async with self.lock:
            uptime = (datetime.now() - self.start_time).total_seconds()

            return {
                "uptime_seconds": uptime,
                "metrics": dict(self.metrics)
            }

    async def reset(self):
        """重置所有指标"""
        async with self.lock:
            self.metrics.clear()
            self.start_time = datetime.now()
            logger.info("Metrics reset")
