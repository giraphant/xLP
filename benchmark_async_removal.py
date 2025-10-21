#!/usr/bin/env python3
"""
Async 移除性能 Benchmark

对比：移除不必要的 async/await 后的性能提升
- MetricsCollector: async → 同步
- AuditLog: async → 同步
"""

import sys
import time
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from plugins.metrics import MetricsCollector
from plugins.audit_log import AuditLog
from core.decision_logic import Decision


def benchmark_metrics_sync(iterations=10000):
    """Benchmark: MetricsCollector (同步版本)"""
    print("\n" + "="*70)
    print("📊 Benchmark 1: MetricsCollector (同步版本)")
    print("="*70)

    metrics = MetricsCollector()

    start_time = time.perf_counter()

    for i in range(iterations):
        decision = Decision(action="place_order", reason="test")
        metrics.record_decision("SOL", decision)

        if i % 2 == 0:
            result = {"success": True}
            metrics.record_action("SOL", "place_order", result)

    elapsed = time.perf_counter() - start_time
    ops_per_sec = iterations / elapsed

    print(f"✅ 完成 {iterations:,} 次操作")
    print(f"⏱️  耗时: {elapsed:.4f}s")
    print(f"🚀 吞吐量: {ops_per_sec:,.0f} ops/s")

    return elapsed, ops_per_sec


async def benchmark_metrics_async_wrapped(iterations=10000):
    """Benchmark: MetricsCollector 在 async 上下文中调用（模拟旧版本）"""
    print("\n" + "="*70)
    print("📊 Benchmark 2: MetricsCollector 在 async 上下文（模拟）")
    print("="*70)

    metrics = MetricsCollector()

    start_time = time.perf_counter()

    for i in range(iterations):
        decision = Decision(action="place_order", reason="test")
        # 模拟旧版本：在 async 上下文中调用（虽然是同步的）
        await asyncio.sleep(0)  # 模拟 event loop 切换开销
        metrics.record_decision("SOL", decision)

        if i % 2 == 0:
            result = {"success": True}
            await asyncio.sleep(0)
            metrics.record_action("SOL", "place_order", result)

    elapsed = time.perf_counter() - start_time
    ops_per_sec = iterations / elapsed

    print(f"✅ 完成 {iterations:,} 次操作")
    print(f"⏱️  耗时: {elapsed:.4f}s")
    print(f"🚀 吞吐量: {ops_per_sec:,.0f} ops/s")
    print(f"⚠️  注意：包含 event loop 切换开销")

    return elapsed, ops_per_sec


def benchmark_audit_log_sync(iterations=5000):
    """Benchmark: AuditLog (同步版本)"""
    print("\n" + "="*70)
    print("📊 Benchmark 3: AuditLog (同步版本)")
    print("="*70)

    import tempfile
    import os

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
        log_file = f.name

    try:
        audit = AuditLog(log_file=log_file, enabled=True)

        start_time = time.perf_counter()

        for i in range(iterations):
            decision = Decision(action="place_order", reason="test")
            audit.log_decision("SOL", decision)

            if i % 2 == 0:
                result = {"success": True, "order_id": f"order-{i}"}
                audit.log_action("SOL", "place_order", result)

        elapsed = time.perf_counter() - start_time
        ops_per_sec = iterations / elapsed

        print(f"✅ 完成 {iterations:,} 次操作 (含文件写入)")
        print(f"⏱️  耗时: {elapsed:.4f}s")
        print(f"🚀 吞吐量: {ops_per_sec:,.0f} ops/s")

        # 检查文件大小
        file_size = os.path.getsize(log_file) / 1024
        print(f"📄 日志文件大小: {file_size:.2f} KB")

        return elapsed, ops_per_sec
    finally:
        os.unlink(log_file)


def benchmark_combined_sync(iterations=10000):
    """Benchmark: 组合场景（模拟真实使用）"""
    print("\n" + "="*70)
    print("📊 Benchmark 4: 组合场景 (Metrics + AuditLog)")
    print("="*70)

    metrics = MetricsCollector()
    audit = AuditLog(enabled=False)  # 不写文件，只测内存操作

    start_time = time.perf_counter()

    for i in range(iterations):
        symbol = "SOL" if i % 2 == 0 else "BTC"
        decision = Decision(action="place_order", reason="test")

        # 模拟回调：同时调用
        audit.log_decision(symbol, decision)
        metrics.record_decision(symbol, decision)

        if i % 3 == 0:
            result = {"success": True, "order_id": f"order-{i}"}
            audit.log_action(symbol, "place_order", result)
            metrics.record_action(symbol, "place_order", result)

    elapsed = time.perf_counter() - start_time
    ops_per_sec = iterations / elapsed

    print(f"✅ 完成 {iterations:,} 次操作")
    print(f"⏱️  耗时: {elapsed:.4f}s")
    print(f"🚀 吞吐量: {ops_per_sec:,.0f} ops/s")

    # 显示 metrics 统计
    summary = metrics.get_summary()
    print(f"📈 Metrics: {summary['metrics'].get('decisions_total', 0)} decisions, "
          f"{summary['metrics'].get('actions_total', 0)} actions")

    return elapsed, ops_per_sec


def main():
    """运行所有 benchmark"""
    print("\n" + "="*70)
    print("🔥 Async 移除性能 Benchmark - P0.2 优化")
    print("="*70)
    print()
    print("优化亮点：")
    print("  ✅ MetricsCollector: async → 同步")
    print("  ✅ AuditLog: async → 同步")
    print("  ✅ 去掉 asyncio.Lock → threading.Lock")
    print("  ✅ 去掉不必要的 event loop 开销")
    print()

    results = {}

    # Benchmark 1: MetricsCollector 同步
    elapsed1, ops1 = benchmark_metrics_sync(iterations=10000)
    results['metrics_sync'] = ops1

    # Benchmark 2: MetricsCollector async wrapped (模拟)
    elapsed2, ops2 = asyncio.run(benchmark_metrics_async_wrapped(iterations=10000))
    results['metrics_async'] = ops2

    # Benchmark 3: AuditLog 同步
    elapsed3, ops3 = benchmark_audit_log_sync(iterations=5000)
    results['audit_sync'] = ops3

    # Benchmark 4: 组合场景
    elapsed4, ops4 = benchmark_combined_sync(iterations=10000)
    results['combined'] = ops4

    # 总结
    print("\n" + "="*70)
    print("📈 性能总结")
    print("="*70)
    print(f"  MetricsCollector (同步):   {results['metrics_sync']:>12,.0f} ops/s")
    print(f"  MetricsCollector (async包装): {results['metrics_async']:>12,.0f} ops/s")
    print(f"  AuditLog (同步):            {results['audit_sync']:>12,.0f} ops/s")
    print(f"  组合场景:                   {results['combined']:>12,.0f} ops/s")
    print()

    # 计算提升
    if results['metrics_async'] > 0:
        improvement = (results['metrics_sync'] / results['metrics_async'] - 1) * 100
        print(f"⚡ 相比 async 包装提升: {improvement:.1f}%")
    print()
    print("🎯 实际效果：")
    print("  - 去掉 async/await 开销")
    print("  - threading.Lock 比 asyncio.Lock 更快")
    print("  - 代码更简洁，更易维护")
    print()


if __name__ == "__main__":
    main()
