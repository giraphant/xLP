#!/usr/bin/env python3
"""
配置启动时间基准测试

对比 pydantic 版本和简化版本的启动时间
"""

import time
import sys
import os

# 测试参数
NUM_ITERATIONS = 100


def benchmark_config(config_path: str, name: str) -> float:
    """
    基准测试配置加载时间

    Args:
        config_path: 配置模块路径
        name: 配置名称

    Returns:
        平均加载时间（毫秒）
    """
    times = []

    for i in range(NUM_ITERATIONS):
        # 清除模块缓存
        if config_path in sys.modules:
            del sys.modules[config_path]

        # 测量导入时间
        start = time.perf_counter()

        # 动态导入
        module = __import__(config_path, fromlist=['HedgeConfig'])
        config_class = getattr(module, 'HedgeConfig')

        # 创建配置实例
        config = config_class()
        config_dict = config.to_dict()

        end = time.perf_counter()

        elapsed_ms = (end - start) * 1000
        times.append(elapsed_ms)

    avg = sum(times) / len(times)
    min_time = min(times)
    max_time = max(times)

    print(f"\n{name}:")
    print(f"  平均: {avg:.2f} ms")
    print(f"  最小: {min_time:.2f} ms")
    print(f"  最大: {max_time:.2f} ms")

    return avg


def main():
    print("=" * 60)
    print("配置启动时间基准测试")
    print("=" * 60)
    print(f"迭代次数: {NUM_ITERATIONS}")

    # 确保路径正确
    sys.path.insert(0, '/home/xLP/src/utils')

    # 测试简化版本
    simple_avg = benchmark_config('config', '简化版本（无 pydantic）')

    # 测试 pydantic 版本
    pydantic_avg = benchmark_config('config_pydantic_backup', 'Pydantic 版本')

    # 对比
    print("\n" + "=" * 60)
    print("对比结果:")
    print("=" * 60)
    improvement = ((pydantic_avg - simple_avg) / pydantic_avg) * 100
    speedup = pydantic_avg / simple_avg

    print(f"简化版本: {simple_avg:.2f} ms")
    print(f"Pydantic版本: {pydantic_avg:.2f} ms")
    print(f"改进: {improvement:.1f}% faster")
    print(f"加速比: {speedup:.2f}x")
    print("=" * 60)


if __name__ == "__main__":
    main()
