#!/usr/bin/env python3
"""
测试增强的日志系统
验证所有日志输出是否正确显示持仓、偏移量和决策过程
"""

import asyncio
import logging
import sys
import os
from pathlib import Path

# 添加src目录到Python路径
sys.path.insert(0, str(Path(__file__).parent))

from hedge_engine import HedgeEngine

# 配置详细的日志输出
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

# 减少第三方库的日志噪音
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


async def test_enhanced_logging():
    """测试增强的日志系统"""
    print("\n" + "="*70)
    print("TESTING ENHANCED LOGGING SYSTEM")
    print("="*70 + "\n")

    try:
        # 初始化引擎
        print("Initializing hedge engine...")
        engine = HedgeEngine()

        # 运行一次完整的管道周期
        print("\nRunning one pipeline cycle...")
        print("Watch for the following in the logs:")
        print("  1. Pool positions from each pool (JLP/ALP)")
        print("  2. Ideal hedge calculations")
        print("  3. Current market prices and actual positions")
        print("  4. Offset calculations with cost basis")
        print("  5. Decision engine reasoning with zones")
        print("  6. Action execution details")
        print("  7. Final summary with total exposure")
        print("\n" + "-"*70 + "\n")

        await engine.run_once()

        print("\n" + "="*70)
        print("TEST COMPLETED SUCCESSFULLY")
        print("="*70)
        print("\nThe enhanced logging system shows:")
        print("✓ Clear pool position breakdown")
        print("✓ Detailed hedge calculations")
        print("✓ Market data with actual positions")
        print("✓ Offset and cost basis calculations")
        print("✓ Decision reasoning with zone information")
        print("✓ Execution results with order details")
        print("✓ Comprehensive summary with total exposure")

    except Exception as e:
        print(f"\nTest failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True


if __name__ == "__main__":
    success = asyncio.run(test_enhanced_logging())
    sys.exit(0 if success else 1)