#!/usr/bin/env python3
"""
监控指标收集器 - 收集和导出系统运行指标
支持多种格式导出，便于监控和分析
"""

import json
import time
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from enum import Enum
import asyncio
from pathlib import Path

logger = logging.getLogger(__name__)


class MetricType(Enum):
    """指标类型"""
    COUNTER = "counter"      # 计数器（只增不减）
    GAUGE = "gauge"          # 测量值（可增可减）
    HISTOGRAM = "histogram"  # 直方图（分布统计）
    SUMMARY = "summary"      # 摘要（百分位数）


@dataclass
class Metric:
    """单个指标"""
    name: str
    type: MetricType
    value: float
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    description: str = ""


@dataclass
class MetricSnapshot:
    """指标快照"""
    timestamp: datetime
    metrics: Dict[str, Any]
    duration_seconds: float


class MetricsCollector:
    """
    监控指标收集器

    收集系统运行时的各种指标，支持导出为多种格式
    """

    def __init__(self, buffer_size: int = 1000):
        """
        Args:
            buffer_size: 历史记录缓冲区大小
        """
        # 计数器指标
        self.counters = defaultdict(int)

        # 测量值指标
        self.gauges = defaultdict(float)

        # 分布统计（使用deque限制大小）
        self.histograms = defaultdict(lambda: deque(maxlen=buffer_size))

        # 时序数据（用于趋势分析）
        self.time_series = defaultdict(lambda: deque(maxlen=buffer_size))

        # 错误分类统计
        self.error_counts = defaultdict(int)

        # 性能统计
        self.performance_stats = {
            "api_latencies": defaultdict(lambda: deque(maxlen=buffer_size)),
            "processing_times": deque(maxlen=buffer_size),
            "order_latencies": defaultdict(lambda: deque(maxlen=buffer_size))
        }

        # 业务指标
        self.business_metrics = {
            "total_volume_usd": 0.0,
            "successful_hedges": 0,
            "failed_hedges": 0,
            "forced_closes": 0,
            "threshold_breaches": 0
        }

        # 启动时间
        self.start_time = time.time()
        self._lock = asyncio.Lock()

    # ==================== 指标记录方法 ====================

    def increment(self, name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None):
        """增加计数器"""
        key = self._make_key(name, labels)
        self.counters[key] += value
        logger.debug(f"Counter {key} incremented by {value}")

    def set_gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """设置测量值"""
        key = self._make_key(name, labels)
        self.gauges[key] = value

    def observe(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """记录分布数据"""
        key = self._make_key(name, labels)
        self.histograms[key].append(value)
        self.time_series[key].append((time.time(), value))

    async def record_order(
        self,
        symbol: str,
        side: str,
        size: float,
        price: float,
        order_type: str,
        success: bool
    ):
        """记录订单指标"""
        async with self._lock:
            # 订单计数
            order_key = f"orders_{order_type}_{side}"
            self.increment(order_key, labels={"symbol": symbol})

            if success:
                self.increment("orders_successful", labels={"symbol": symbol})
            else:
                self.increment("orders_failed", labels={"symbol": symbol})

            # 订单金额
            volume_usd = size * price
            self.business_metrics["total_volume_usd"] += volume_usd

            # 记录到时序数据
            self.time_series["order_volumes"].append((time.time(), volume_usd))

    async def record_api_call(
        self,
        service: str,
        endpoint: str,
        duration: float,
        success: bool,
        error: Optional[str] = None
    ):
        """记录API调用指标"""
        async with self._lock:
            # API调用计数
            self.increment(f"api_calls_{service}", labels={"endpoint": endpoint})

            # 延迟统计
            self.performance_stats["api_latencies"][service].append(duration)

            if not success:
                self.increment(f"api_errors_{service}", labels={"endpoint": endpoint})
                if error:
                    self.error_counts[f"{service}:{error}"] += 1

    async def record_processing(
        self,
        operation: str,
        duration: float,
        symbol: Optional[str] = None
    ):
        """记录处理时间"""
        async with self._lock:
            self.performance_stats["processing_times"].append(duration)
            self.observe(f"processing_duration_{operation}", duration,
                        labels={"symbol": symbol} if symbol else None)

    async def record_hedge_result(
        self,
        symbol: str,
        offset_usd: float,
        action: str,
        success: bool
    ):
        """记录对冲结果"""
        async with self._lock:
            if success:
                self.business_metrics["successful_hedges"] += 1
            else:
                self.business_metrics["failed_hedges"] += 1

            # 记录偏移量分布
            self.observe("offset_usd_distribution", offset_usd, labels={"symbol": symbol})

            # 记录操作
            self.increment(f"hedge_actions_{action}", labels={"symbol": symbol})

    async def record_threshold_breach(self, symbol: str, offset_usd: float):
        """记录阈值突破"""
        async with self._lock:
            self.business_metrics["threshold_breaches"] += 1
            self.increment("threshold_breaches", labels={"symbol": symbol})
            self.time_series["threshold_breaches"].append((time.time(), offset_usd))

    async def record_forced_close(self, symbol: str, size: float, price: float):
        """记录强制平仓"""
        async with self._lock:
            self.business_metrics["forced_closes"] += 1
            self.increment("forced_closes", labels={"symbol": symbol})

            volume_usd = size * price
            self.time_series["forced_close_volumes"].append((time.time(), volume_usd))

    def record_error(self, error_type: str, error_message: str):
        """记录错误"""
        self.error_counts[error_type] += 1
        self.increment("errors", labels={"type": error_type})
        logger.warning(f"Error recorded: {error_type} - {error_message}")

    # ==================== 指标计算方法 ====================

    def calculate_percentile(self, data: List[float], percentile: float) -> float:
        """计算百分位数"""
        if not data:
            return 0.0

        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile / 100)
        return sorted_data[min(index, len(sorted_data) - 1)]

    def calculate_statistics(self, data: List[float]) -> Dict[str, float]:
        """计算统计信息"""
        if not data:
            return {
                "count": 0,
                "mean": 0.0,
                "min": 0.0,
                "max": 0.0,
                "p50": 0.0,
                "p95": 0.0,
                "p99": 0.0
            }

        return {
            "count": len(data),
            "mean": sum(data) / len(data),
            "min": min(data),
            "max": max(data),
            "p50": self.calculate_percentile(data, 50),
            "p95": self.calculate_percentile(data, 95),
            "p99": self.calculate_percentile(data, 99)
        }

    def get_uptime(self) -> float:
        """获取运行时间（秒）"""
        return time.time() - self.start_time

    # ==================== 导出方法 ====================

    async def get_snapshot(self) -> MetricSnapshot:
        """获取当前指标快照"""
        async with self._lock:
            metrics = {
                "counters": dict(self.counters),
                "gauges": dict(self.gauges),
                "business": dict(self.business_metrics),
                "errors": dict(self.error_counts),
                "uptime_seconds": self.get_uptime()
            }

            # 添加性能统计
            if self.performance_stats["processing_times"]:
                metrics["processing_stats"] = self.calculate_statistics(
                    list(self.performance_stats["processing_times"])
                )

            # 添加API延迟统计
            api_stats = {}
            for service, latencies in self.performance_stats["api_latencies"].items():
                if latencies:
                    api_stats[service] = self.calculate_statistics(list(latencies))
            if api_stats:
                metrics["api_latency_stats"] = api_stats

            return MetricSnapshot(
                timestamp=datetime.now(),
                metrics=metrics,
                duration_seconds=self.get_uptime()
            )

    async def export_prometheus(self) -> str:
        """
        导出为Prometheus格式

        Returns:
            Prometheus格式的指标文本
        """
        lines = []
        snapshot = await self.get_snapshot()

        # 添加帮助信息和类型
        lines.append("# HELP hedge_engine_uptime_seconds Time since engine started")
        lines.append("# TYPE hedge_engine_uptime_seconds gauge")
        lines.append(f"hedge_engine_uptime_seconds {snapshot.metrics['uptime_seconds']:.2f}")
        lines.append("")

        # 导出计数器
        for key, value in snapshot.metrics.get("counters", {}).items():
            metric_name = f"hedge_engine_{key}"
            lines.append(f"# TYPE {metric_name} counter")
            lines.append(f"{metric_name} {value}")

        # 导出测量值
        for key, value in snapshot.metrics.get("gauges", {}).items():
            metric_name = f"hedge_engine_{key}"
            lines.append(f"# TYPE {metric_name} gauge")
            lines.append(f"{metric_name} {value}")

        # 导出业务指标
        for key, value in snapshot.metrics.get("business", {}).items():
            metric_name = f"hedge_engine_{key}"
            lines.append(f"# TYPE {metric_name} gauge")
            lines.append(f"{metric_name} {value}")

        return "\n".join(lines)

    async def export_json(self, pretty: bool = True) -> str:
        """
        导出为JSON格式

        Args:
            pretty: 是否格式化输出

        Returns:
            JSON格式的指标
        """
        snapshot = await self.get_snapshot()

        data = {
            "timestamp": snapshot.timestamp.isoformat(),
            "uptime_seconds": snapshot.duration_seconds,
            "metrics": snapshot.metrics
        }

        if pretty:
            return json.dumps(data, indent=2, default=str)
        else:
            return json.dumps(data, default=str)

    async def export_summary(self) -> Dict[str, Any]:
        """
        导出摘要信息

        Returns:
            摘要字典
        """
        snapshot = await self.get_snapshot()

        uptime = timedelta(seconds=int(snapshot.duration_seconds))
        total_orders = sum(v for k, v in snapshot.metrics.get("counters", {}).items()
                          if k.startswith("orders_"))

        summary = {
            "status": "running",
            "uptime": str(uptime),
            "metrics": {
                "total_orders": total_orders,
                "successful_hedges": snapshot.metrics["business"]["successful_hedges"],
                "failed_hedges": snapshot.metrics["business"]["failed_hedges"],
                "forced_closes": snapshot.metrics["business"]["forced_closes"],
                "total_volume_usd": f"${snapshot.metrics['business']['total_volume_usd']:,.2f}",
                "error_count": sum(snapshot.metrics.get("errors", {}).values())
            },
            "performance": {
                "processing": snapshot.metrics.get("processing_stats", {}),
                "api_latency": snapshot.metrics.get("api_latency_stats", {})
            }
        }

        return summary

    async def save_to_file(self, filepath: Path, format: str = "json"):
        """
        保存指标到文件

        Args:
            filepath: 文件路径
            format: 格式（json, prometheus, summary）
        """
        try:
            if format == "json":
                content = await self.export_json()
            elif format == "prometheus":
                content = await self.export_prometheus()
            elif format == "summary":
                content = json.dumps(await self.export_summary(), indent=2)
            else:
                raise ValueError(f"Unsupported format: {format}")

            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content)
            logger.info(f"Metrics saved to {filepath}")

        except Exception as e:
            logger.error(f"Failed to save metrics: {e}")

    async def start_periodic_export(
        self,
        interval: int = 300,
        filepath: Path = Path("logs/metrics.json"),
        format: str = "json"
    ):
        """
        启动定期导出任务

        Args:
            interval: 导出间隔（秒）
            filepath: 文件路径
            format: 导出格式
        """
        while True:
            await asyncio.sleep(interval)
            await self.save_to_file(filepath, format)

    # ==================== 工具方法 ====================

    def _make_key(self, name: str, labels: Optional[Dict[str, str]] = None) -> str:
        """生成带标签的键"""
        if not labels:
            return name

        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def reset(self):
        """重置所有指标"""
        self.counters.clear()
        self.gauges.clear()
        self.histograms.clear()
        self.time_series.clear()
        self.error_counts.clear()
        self.performance_stats["api_latencies"].clear()
        self.performance_stats["processing_times"].clear()
        self.performance_stats["order_latencies"].clear()
        self.business_metrics = {
            "total_volume_usd": 0.0,
            "successful_hedges": 0,
            "failed_hedges": 0,
            "forced_closes": 0,
            "threshold_breaches": 0
        }
        self.start_time = time.time()
        logger.info("Metrics reset")

    def __str__(self) -> str:
        """字符串表示"""
        return (f"MetricsCollector(counters={len(self.counters)}, "
               f"gauges={len(self.gauges)}, uptime={self.get_uptime():.0f}s)")