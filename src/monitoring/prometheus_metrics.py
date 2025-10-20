#!/usr/bin/env python3
"""
Prometheus 指标收集器 - 使用行业标准监控库
替代手写的 metrics.py (453行 → ~100行)
"""

import time
import logging
from typing import Dict, Any, Optional
from pathlib import Path
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    Summary,
    Info,
    generate_latest,
    REGISTRY
)

logger = logging.getLogger(__name__)

# ==================== 定义所有指标 ====================

# 订单指标
ORDERS_TOTAL = Counter(
    'hedge_orders_total',
    'Total number of orders placed',
    ['symbol', 'side', 'status']
)

ORDERS_CANCELLED = Counter(
    'hedge_orders_cancelled_total',
    'Total number of orders cancelled',
    ['symbol', 'reason']
)

ORDERS_FILLED = Counter(
    'hedge_orders_filled_total',
    'Total number of orders filled',
    ['symbol', 'side']
)

# 持仓指标
POSITION_OFFSET = Gauge(
    'hedge_position_offset',
    'Current position offset',
    ['symbol']
)

POSITION_COST_BASIS = Gauge(
    'hedge_position_cost_basis',
    'Current position cost basis',
    ['symbol']
)

POSITION_ZONE = Gauge(
    'hedge_position_zone',
    'Current position zone',
    ['symbol']
)

# 性能指标
ORDER_LATENCY = Histogram(
    'hedge_order_latency_seconds',
    'Order execution latency',
    ['symbol', 'operation'],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

PIPELINE_DURATION = Summary(
    'hedge_pipeline_duration_seconds',
    'Pipeline execution duration',
    ['stage']
)

API_LATENCY = Histogram(
    'hedge_api_latency_seconds',
    'API call latency',
    ['service', 'endpoint'],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0]
)

# 错误指标
ERRORS_TOTAL = Counter(
    'hedge_errors_total',
    'Total number of errors',
    ['type', 'severity']
)

CIRCUIT_BREAKER_STATE = Gauge(
    'hedge_circuit_breaker_state',
    'Circuit breaker state (0=closed, 1=half-open, 2=open)',
    ['service']
)

# 系统指标
PIPELINE_RUNS = Counter(
    'hedge_pipeline_runs_total',
    'Total number of pipeline runs',
    ['status']
)

UPTIME_SECONDS = Gauge(
    'hedge_uptime_seconds',
    'System uptime in seconds'
)

# 元数据
SYSTEM_INFO = Info(
    'hedge_system',
    'System information'
)


class PrometheusMetrics:
    """
    Prometheus 指标收集器

    简单封装 Prometheus Client，提供友好的 API
    兼容旧的 MetricsCollector 接口
    """

    def __init__(self):
        """初始化指标收集器"""
        self.start_time = time.time()

        # 设置系统信息
        SYSTEM_INFO.info({
            'version': '2.0',
            'metrics_backend': 'prometheus',
        })

        logger.info("Prometheus metrics collector initialized")

    # ==================== 订单指标 ====================

    def record_order_placed(self, symbol: str, side: str, status: str = 'placed'):
        """记录下单"""
        ORDERS_TOTAL.labels(symbol=symbol, side=side, status=status).inc()

    def record_order_cancelled(self, symbol: str, reason: str = 'timeout'):
        """记录订单取消"""
        ORDERS_CANCELLED.labels(symbol=symbol, reason=reason).inc()

    def record_order_filled(self, symbol: str, side: str):
        """记录订单成交"""
        ORDERS_FILLED.labels(symbol=symbol, side=side).inc()

    async def record_order(self, symbol: str, side: str, size: float, price: float, order_type: str, success: bool):
        """
        记录订单（兼容旧接口）

        Args:
            symbol: 交易对
            side: 买卖方向
            size: 数量
            price: 价格
            order_type: 订单类型（limit/market）
            success: 是否成功
        """
        status = 'placed' if success else 'failed'
        self.record_order_placed(symbol, side, status)

    # ==================== 持仓指标 ====================

    def update_position_offset(self, symbol: str, offset: float):
        """更新持仓偏移"""
        POSITION_OFFSET.labels(symbol=symbol).set(offset)

    def update_cost_basis(self, symbol: str, cost_basis: float):
        """更新成本基础"""
        POSITION_COST_BASIS.labels(symbol=symbol).set(cost_basis)

    def update_position_zone(self, symbol: str, zone: Optional[int]):
        """更新持仓区间"""
        zone_value = zone if zone is not None else -1
        POSITION_ZONE.labels(symbol=symbol).set(zone_value)

    # ==================== 性能指标 ====================

    def record_order_latency(self, symbol: str, operation: str, duration: float):
        """记录订单延迟"""
        ORDER_LATENCY.labels(symbol=symbol, operation=operation).observe(duration)

    def record_pipeline_duration(self, stage: str, duration: float):
        """记录 Pipeline 执行时间"""
        PIPELINE_DURATION.labels(stage=stage).observe(duration)

    def record_api_latency(self, service: str, endpoint: str, duration: float):
        """记录 API 调用延迟"""
        API_LATENCY.labels(service=service, endpoint=endpoint).observe(duration)

    # ==================== 错误指标 ====================

    def record_error(self, error_type: str, severity: str = 'medium'):
        """记录错误"""
        ERRORS_TOTAL.labels(type=error_type, severity=severity).inc()

    def set_circuit_breaker_state(self, service: str, state: str):
        """设置熔断器状态"""
        state_map = {'closed': 0, 'half_open': 1, 'open': 2}
        state_value = state_map.get(state, 0)
        CIRCUIT_BREAKER_STATE.labels(service=service).set(state_value)

    # ==================== 系统指标 ====================

    def record_pipeline_run(self, status: str = 'success'):
        """记录 Pipeline 运行"""
        PIPELINE_RUNS.labels(status=status).inc()

    def update_uptime(self):
        """更新系统运行时间"""
        uptime = time.time() - self.start_time
        UPTIME_SECONDS.set(uptime)

    # ==================== 导出方法 ====================

    def export_prometheus(self) -> bytes:
        """
        导出 Prometheus 格式

        Returns:
            Prometheus 格式的 metrics（bytes）
        """
        self.update_uptime()
        return generate_latest(REGISTRY)

    async def export_summary(self) -> Dict[str, Any]:
        """
        导出摘要（兼容旧接口）

        Returns:
            包含所有指标的字典
        """
        metrics = {}

        # 遍历所有指标并提取值
        for metric in REGISTRY.collect():
            for sample in metric.samples:
                # 构建指标键
                labels_str = ','.join([f'{k}={v}' for k, v in sample.labels.items()])
                key = f"{sample.name}"
                if labels_str:
                    key += f"{{{labels_str}}}"

                metrics[key] = sample.value

        return {
            'timestamp': time.time(),
            'metrics': metrics,
            'uptime_seconds': time.time() - self.start_time
        }

    async def save_to_file(self, file_path: Path, format: str = "prometheus"):
        """
        保存指标到文件

        Args:
            file_path: 文件路径
            format: 格式（prometheus 或 json）
        """
        file_path.parent.mkdir(parents=True, exist_ok=True)

        if format == "prometheus":
            # Prometheus 格式
            content = self.export_prometheus()
            file_path.write_bytes(content)
        else:
            # JSON 格式
            import json
            summary = await self.export_summary()
            file_path.write_text(json.dumps(summary, indent=2))

        logger.debug(f"Metrics saved to {file_path} (format: {format})")

    # ==================== 兼容性方法 ====================

    def increment_counter(self, name: str, value: int = 1, **labels):
        """增加计数器（兼容旧接口）"""
        # 根据名称映射到对应的 Prometheus 指标
        if 'order' in name:
            symbol = labels.get('symbol', 'UNKNOWN')
            side = labels.get('side', 'unknown')
            self.record_order_placed(symbol, side)
        elif 'error' in name:
            error_type = labels.get('type', name)
            self.record_error(error_type)

    def set_gauge(self, name: str, value: float, **labels):
        """设置测量值（兼容旧接口）"""
        symbol = labels.get('symbol', 'UNKNOWN')

        if 'offset' in name:
            self.update_position_offset(symbol, value)
        elif 'cost' in name:
            self.update_cost_basis(symbol, value)

    def record_histogram(self, name: str, value: float, **labels):
        """记录直方图（兼容旧接口）"""
        symbol = labels.get('symbol', 'UNKNOWN')
        operation = labels.get('operation', 'unknown')

        if 'latency' in name or 'duration' in name:
            self.record_order_latency(symbol, operation, value)


# 创建全局实例（单例模式）
_metrics_instance = None


def get_metrics() -> PrometheusMetrics:
    """获取全局指标收集器实例"""
    global _metrics_instance
    if _metrics_instance is None:
        _metrics_instance = PrometheusMetrics()
    return _metrics_instance
