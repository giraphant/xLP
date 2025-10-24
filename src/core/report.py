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
from utils.config import HedgeConfig
from .types import PreparedData

logger = logging.getLogger(__name__)


async def generate_reports(
    data: PreparedData,
    results: List[Dict[str, Any]],
    config: HedgeConfig,
    matsu_reporter=None
):
    """
    生成所有报告（完全无状态）

    Args:
        data: prepare_data() 的返回值 (PreparedData)
        results: execute_actions() 的返回值
        config: 配置字典
        matsu_reporter: Matsu上报器（可选）
    """
    # 1. 控制台详细报告
    if os.getenv("ENABLE_DETAILED_REPORTS", "true").lower() in ("true", "1", "yes"):
        await _generate_console_report(data, config)

    # 2. Matsu 上报
    if matsu_reporter:
        await _report_to_matsu(data, matsu_reporter)


async def _generate_console_report(data: PreparedData, config: HedgeConfig):
    """
    生成控制台详细报告（无状态 - 从订单计算zone）
    """
    logger.info("=" * 70)
    logger.info("📊 POSITION SUMMARY")
    logger.info("=" * 70)

    total_offset_usd = 0

    for symbol in data.symbols:
        if symbol not in data.offsets or symbol not in data.prices:
            continue

        offset, cost_basis = data.offsets[symbol]
        price = data.prices[symbol]
        offset_usd = abs(offset) * price
        total_offset_usd += offset_usd

        status = "🔴 LONG" if offset > 0 else ("🟢 SHORT" if offset < 0 else "✅ BALANCED")

        logger.info(f"  {status} {symbol}:")
        logger.info(f"    • Offset: {offset:+.4f} (${offset_usd:.2f})")
        logger.info(f"    • Cost: ${cost_basis:.2f}")

        # 检查是否有活跃订单（previous_zone 已在 prepare 阶段计算好）
        order_info = data.order_status.get(symbol)
        if order_info and order_info.has_order:
            zone = order_info.previous_zone
            logger.info(f"    • Monitoring: zone {zone} ({order_info.order_count} orders)")

    logger.info(f"  📊 Total Exposure: ${total_offset_usd:.2f}")


async def _report_to_matsu(data: PreparedData, matsu_reporter):
    """
    上报数据到 Matsu

    依赖：monitoring/matsu_reporter.py

    注意：PreparedData 不包含 ideal_hedges 和 positions
    这些字段需要从其他地方获取，或者 Matsu 报告功能需要重新设计
    """
    try:
        # TODO: PreparedData 没有 ideal_hedges 和 positions 字段
        # 需要确认 Matsu 报告的数据来源
        logger.warning("Matsu reporting temporarily disabled - PreparedData lacks required fields")
        return

        # 原始实现（注释掉，等待修复）:
        # ideal_hedges = data["ideal_hedges"]
        # actual_hedges = data["positions"]
        # cost_bases = {
        #     symbol: cost
        #     for symbol, (offset, cost) in data.offsets.items()
        # }
        # success = await matsu_reporter.report(
        #     ideal_hedges=ideal_hedges,
        #     actual_hedges=actual_hedges,
        #     cost_bases=cost_bases
        # )

    except Exception as e:
        # Matsu 上报失败不应该影响主流程
        logger.warning(f"Failed to report to Matsu: {e}")
