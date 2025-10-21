"""
报告模块（第四步）

职责：
1. 生成控制台详细报告
2. 上报数据到 Matsu（如果启用）

这是观察性步骤，不影响主流程
"""
import logging
import os
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


async def generate_reports(
    data: Dict[str, Any],
    results: List[Dict[str, Any]],
    state_manager,
    config: Dict[str, Any],
    matsu_reporter=None
):
    """
    生成所有报告

    Args:
        data: prepare_data() 的返回值
        results: execute_actions() 的返回值
        state_manager: 状态管理器
        config: 配置字典
        matsu_reporter: Matsu上报器（可选）
    """
    # 1. 控制台详细报告
    if os.getenv("ENABLE_DETAILED_REPORTS", "true").lower() in ("true", "1", "yes"):
        await _generate_console_report(data, state_manager)

    # 2. Matsu 上报
    if matsu_reporter:
        await _report_to_matsu(data, matsu_reporter)


async def _generate_console_report(data: Dict[str, Any], state_manager):
    """
    生成控制台详细报告
    """
    logger.info("=" * 70)
    logger.info("📊 POSITION SUMMARY")
    logger.info("=" * 70)

    total_offset_usd = 0

    for symbol in data["symbols"]:
        if symbol not in data["offsets"] or symbol not in data["prices"]:
            continue

        offset, cost_basis = data["offsets"][symbol]
        price = data["prices"][symbol]
        offset_usd = abs(offset) * price
        total_offset_usd += offset_usd

        # 获取状态
        state = await state_manager.get_symbol_state(symbol)
        monitoring = state.get("monitoring", {})

        status = "🔴 LONG" if offset > 0 else ("🟢 SHORT" if offset < 0 else "✅ BALANCED")

        logger.info(f"  {status} {symbol}:")
        logger.info(f"    • Offset: {offset:+.4f} (${offset_usd:.2f})")
        logger.info(f"    • Cost: ${cost_basis:.2f}")

        if monitoring.get("active"):
            logger.info(f"    • Order: {monitoring.get('order_id')} (zone {monitoring.get('current_zone')})")

    logger.info(f"  📊 Total Exposure: ${total_offset_usd:.2f}")


async def _report_to_matsu(data: Dict[str, Any], matsu_reporter):
    """
    上报数据到 Matsu

    依赖：monitoring/matsu_reporter.py
    """
    try:
        # 准备 Matsu 需要的数据格式
        ideal_hedges = data["ideal_hedges"]  # {symbol: amount}

        # actual_hedges = 实际持仓（positions）
        # 因为 positions 就是实际的对冲持仓
        actual_hedges = data["positions"]  # {symbol: amount}

        # cost_bases = 从 offsets 中提取成本
        cost_bases = {
            symbol: cost
            for symbol, (offset, cost) in data["offsets"].items()
        }

        # 调用正确的方法名
        success = await matsu_reporter.report(
            ideal_hedges=ideal_hedges,
            actual_hedges=actual_hedges,
            cost_bases=cost_bases
        )

        if success:
            logger.debug("✅ Reported to Matsu")
        else:
            logger.warning("⚠️  Matsu report returned failure")

    except Exception as e:
        # Matsu 上报失败不应该影响主流程
        logger.warning(f"Failed to report to Matsu: {e}")
