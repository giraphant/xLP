#!/usr/bin/env python3
"""
数据管道模式 - 将复杂的数据处理分解为独立的步骤
提高代码可测试性和可维护性
"""

import asyncio
import logging
import time
from typing import Dict, List, Any, Optional, Callable, Tuple
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum

from core.exceptions import HedgeEngineError, classify_exception

logger = logging.getLogger(__name__)

# Export key classes for external use
__all__ = [
    'HedgePipeline',
    'PipelineContext',
    'PipelineStep',
    'StepResult',
    'StepStatus',
    'create_hedge_pipeline',
    'FetchPoolDataStep',
    'CalculateIdealHedgesStep',
    'FetchMarketDataStep',
    'CalculateOffsetsStep',
    'ApplyPredefinedOffsetStep',
    'DecideActionsStep',
    'ExecuteActionsStep',
    'logging_middleware',
    'timing_middleware',
    'error_collection_middleware'
]


class StepStatus(Enum):
    """步骤执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StepResult:
    """步骤执行结果"""
    name: str
    status: StepStatus
    data: Any = None
    error: Optional[Exception] = None
    duration: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class PipelineContext:
    """管道上下文 - 在步骤间传递数据"""
    # 输入数据
    config: dict

    # 中间结果存储
    pool_data: Dict[str, Any] = field(default_factory=dict)
    ideal_hedges: Dict[str, float] = field(default_factory=dict)
    actual_positions: Dict[str, float] = field(default_factory=dict)
    prices: Dict[str, float] = field(default_factory=dict)
    offsets: Dict[str, Tuple[float, float]] = field(default_factory=dict)  # (offset, cost_basis)
    actions: List[Dict[str, Any]] = field(default_factory=list)

    # 执行结果
    results: List[StepResult] = field(default_factory=list)

    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_result(self, result: StepResult):
        """添加步骤结果"""
        self.results.append(result)
        if result.status == StepStatus.SUCCESS:
            logger.debug(f"Step '{result.name}' completed in {result.duration:.2f}s")
        elif result.status == StepStatus.FAILED:
            logger.error(f"Step '{result.name}' failed: {result.error}")


class PipelineStep:
    """管道步骤基类"""

    def __init__(
        self,
        name: str,
        required: bool = True,
        retry_times: int = 0,
        timeout: Optional[float] = None
    ):
        """
        Args:
            name: 步骤名称
            required: 是否必须成功
            retry_times: 重试次数
            timeout: 超时时间（秒）
        """
        self.name = name
        self.required = required
        self.retry_times = retry_times
        self.timeout = timeout

    async def execute(self, context: PipelineContext) -> StepResult:
        """执行步骤"""
        start_time = time.time()

        for attempt in range(self.retry_times + 1):
            try:
                # 设置超时
                if self.timeout:
                    result = await asyncio.wait_for(
                        self._run(context),
                        timeout=self.timeout
                    )
                else:
                    result = await self._run(context)

                duration = time.time() - start_time
                return StepResult(
                    name=self.name,
                    status=StepStatus.SUCCESS,
                    data=result,
                    duration=duration
                )

            except asyncio.TimeoutError as e:
                if attempt < self.retry_times:
                    logger.warning(f"Step '{self.name}' timeout, retrying ({attempt + 1}/{self.retry_times})")
                    await asyncio.sleep(2 ** attempt)  # 指数退避
                    continue

                return StepResult(
                    name=self.name,
                    status=StepStatus.FAILED,
                    error=e,
                    duration=time.time() - start_time
                )

            except Exception as e:
                if attempt < self.retry_times:
                    logger.warning(f"Step '{self.name}' failed, retrying ({attempt + 1}/{self.retry_times}): {e}")
                    await asyncio.sleep(2 ** attempt)
                    continue

                return StepResult(
                    name=self.name,
                    status=StepStatus.FAILED,
                    error=e,
                    duration=time.time() - start_time
                )

        # 不应该到达这里
        return StepResult(
            name=self.name,
            status=StepStatus.FAILED,
            error=RuntimeError("Unexpected execution path"),
            duration=time.time() - start_time
        )

    async def _run(self, context: PipelineContext) -> Any:
        """子类需要实现的实际执行逻辑"""
        raise NotImplementedError


class HedgePipeline:
    """
    对冲处理管道

    将复杂的对冲逻辑分解为独立的步骤，每个步骤专注于单一职责
    """

    def __init__(self):
        self.steps: List[PipelineStep] = []
        self.middlewares: List[Callable] = []

    def add_step(self, step: PipelineStep):
        """添加处理步骤"""
        self.steps.append(step)
        return self

    def add_middleware(self, middleware: Callable):
        """添加中间件（如日志、缓存等）"""
        self.middlewares.append(middleware)
        return self

    async def execute(self, context: PipelineContext) -> PipelineContext:
        """执行管道"""
        logger.info(f"Starting pipeline with {len(self.steps)} steps")

        # 执行前置中间件
        for middleware in self.middlewares:
            if asyncio.iscoroutinefunction(middleware):
                await middleware(context, "before")
            else:
                middleware(context, "before")

        # 执行各个步骤
        for step in self.steps:
            logger.info(f"Executing step: {step.name}")

            result = await step.execute(context)
            context.add_result(result)

            # 如果是必需步骤且失败，停止管道
            if step.required and result.status == StepStatus.FAILED:
                logger.error(f"Required step '{step.name}' failed, stopping pipeline")
                break

        # 执行后置中间件
        for middleware in self.middlewares:
            if asyncio.iscoroutinefunction(middleware):
                await middleware(context, "after")
            else:
                middleware(context, "after")

        # 记录执行统计
        self._log_statistics(context)

        return context

    def _log_statistics(self, context: PipelineContext):
        """记录执行统计"""
        total_duration = sum(r.duration for r in context.results)
        success_count = sum(1 for r in context.results if r.status == StepStatus.SUCCESS)
        failed_count = sum(1 for r in context.results if r.status == StepStatus.FAILED)

        logger.info(f"Pipeline completed: {success_count} success, {failed_count} failed, "
                   f"total duration: {total_duration:.2f}s")


# ==================== 具体步骤实现 ====================

class FetchPoolDataStep(PipelineStep):
    """获取池子数据步骤"""

    def __init__(self, pool_calculators: dict):
        super().__init__(
            name="FetchPoolData",
            required=True,
            retry_times=2,
            timeout=30
        )
        self.pool_calculators = pool_calculators

    async def _run(self, context: PipelineContext) -> Dict[str, Any]:
        """获取所有池子数据"""
        pool_data = {}

        logger.info("=" * 50)
        logger.info("📊 FETCHING POOL DATA")
        logger.info("=" * 50)

        for pool_type, calculator in self.pool_calculators.items():
            amount = context.config.get(f"{pool_type}_amount", 0)
            if amount > 0:
                logger.info(f"🏊 {pool_type.upper()} Pool: Amount = {amount:,.2f}")
                positions = await calculator(amount)
                pool_data[pool_type] = positions

                # 详细显示每个池子的持仓
                logger.info(f"  └─ Positions in {pool_type.upper()}:")
                for symbol, data in positions.items():
                    amount_value = data["amount"] if isinstance(data, dict) else data
                    logger.info(f"     • {symbol}: {amount_value:,.4f}")

        context.pool_data = pool_data
        logger.info(f"✅ Fetched data from {len(pool_data)} pools")
        return pool_data


class CalculateIdealHedgesStep(PipelineStep):
    """计算理想对冲量步骤"""

    def __init__(self):
        super().__init__(
            name="CalculateIdealHedges",
            required=True,
            retry_times=0,
            timeout=10
        )

    async def _run(self, context: PipelineContext) -> Dict[str, float]:
        """合并计算理想对冲量"""
        merged_hedges = {}

        logger.info("=" * 50)
        logger.info("🎯 CALCULATING IDEAL HEDGES")
        logger.info("=" * 50)

        # 详细显示每个池子的贡献
        for pool_type, positions in context.pool_data.items():
            logger.info(f"📈 {pool_type.upper()} Pool Contributions:")
            for symbol, data in positions.items():
                # 转换符号（WBTC -> BTC）
                exchange_symbol = "BTC" if symbol == "WBTC" else symbol

                # 累加对冲量（负数表示做空）
                if exchange_symbol not in merged_hedges:
                    merged_hedges[exchange_symbol] = 0

                # 从data中提取amount（根据实际数据结构）
                amount = data["amount"] if isinstance(data, dict) else data
                hedge_amount = -amount  # 负数表示做空
                merged_hedges[exchange_symbol] += hedge_amount

                logger.info(f"  • {symbol} → {exchange_symbol}: {hedge_amount:+.4f} (short)")

        # 显示最终的合并结果
        logger.info("📊 MERGED IDEAL POSITIONS (Negative = Short):")
        for symbol, amount in sorted(merged_hedges.items()):
            logger.info(f"  💹 {symbol}: {amount:+.4f}")

        context.ideal_hedges = merged_hedges
        logger.info(f"✅ Calculated hedges for {len(merged_hedges)} symbols")
        return merged_hedges


class FetchMarketDataStep(PipelineStep):
    """获取市场数据步骤（价格和持仓）"""

    def __init__(self, exchange):
        super().__init__(
            name="FetchMarketData",
            required=True,
            retry_times=2,
            timeout=30
        )
        self.exchange = exchange

    async def _run(self, context: PipelineContext) -> Dict[str, Any]:
        """并发获取价格和持仓"""
        symbols = list(context.ideal_hedges.keys())

        logger.info("=" * 50)
        logger.info("💹 FETCHING MARKET DATA")
        logger.info("=" * 50)

        # 并发获取价格
        price_tasks = {
            symbol: self.exchange.get_price(symbol)
            for symbol in symbols
        }

        # 并发获取持仓
        position_tasks = {
            symbol: self.exchange.get_position(symbol)
            for symbol in symbols
        }

        # 等待所有任务完成
        prices_results = await asyncio.gather(*price_tasks.values(), return_exceptions=True)
        positions_results = await asyncio.gather(*position_tasks.values(), return_exceptions=True)

        # 处理结果
        prices = {}
        positions = {}

        logger.info("📈 CURRENT PRICES:")
        for symbol, price in zip(price_tasks.keys(), prices_results):
            if isinstance(price, Exception):
                logger.error(f"  ❌ {symbol}: Failed to get price - {price}")
            else:
                prices[symbol] = price
                logger.info(f"  💵 {symbol}: ${price:,.2f}")

        logger.info("📊 ACTUAL POSITIONS (Exchange + Initial Offset):")
        for symbol, position in zip(position_tasks.keys(), positions_results):
            if isinstance(position, Exception):
                logger.error(f"  ❌ {symbol}: Failed to get position - {position}")
                positions[symbol] = 0.0  # 默认为0
            else:
                # 加上初始偏移量
                initial_offset = context.config.get("initial_offset", {}).get(symbol, 0.0)
                total_position = position + initial_offset
                positions[symbol] = total_position

                if initial_offset != 0:
                    logger.info(f"  📍 {symbol}: {total_position:+.4f} "
                               f"(Exchange: {position:+.4f}, Initial: {initial_offset:+.4f})")
                else:
                    logger.info(f"  📍 {symbol}: {total_position:+.4f}")

        context.prices = prices
        context.actual_positions = positions

        logger.info(f"✅ Fetched market data for {len(prices)} symbols")
        return {"prices": prices, "positions": positions}


class CalculateOffsetsStep(PipelineStep):
    """计算偏移量步骤"""

    def __init__(self, offset_calculator, state_manager):
        super().__init__(
            name="CalculateOffsets",
            required=True,
            retry_times=0,
            timeout=10
        )
        self.offset_calculator = offset_calculator
        self.state_manager = state_manager

    async def _run(self, context: PipelineContext) -> Dict[str, Tuple[float, float]]:
        """计算所有币种的偏移量和成本基础"""
        offsets = {}

        logger.info("=" * 50)
        logger.info("🔍 CALCULATING OFFSETS AND COST BASIS")
        logger.info("=" * 50)

        for symbol in context.ideal_hedges.keys():
            if symbol not in context.prices:
                logger.warning(f"⚠️ Skipping {symbol} due to missing price")
                continue

            # 获取历史状态
            state = await self.state_manager.get_symbol_state(symbol)
            old_offset = state.get("offset", 0.0)
            old_cost = state.get("cost_basis", 0.0)
            old_actual_pos = state.get("last_actual_position", None)

            # 计算新的偏移和成本
            ideal_pos = context.ideal_hedges[symbol]
            actual_pos = context.actual_positions.get(symbol, 0.0)
            current_price = context.prices[symbol]

            new_offset, new_cost = self.offset_calculator(
                ideal_pos, actual_pos, current_price, old_offset, old_cost
            )

            offsets[symbol] = (new_offset, new_cost)

            # 计算USD价值
            offset_usd = abs(new_offset) * current_price

            # 检测position变化（说明有成交或手动调仓）
            if old_actual_pos is not None:  # 只有有历史记录时才检测
                position_change = abs(actual_pos - old_actual_pos)
                if position_change > 0.0001:  # 防止浮点误差
                    logger.info(f"  ⚡ {symbol}: Position changed from {old_actual_pos:+.4f} to {actual_pos:+.4f} (Δ{actual_pos - old_actual_pos:+.4f})")
                    # 记录成交时间
                    await self.state_manager.update_symbol_state(symbol, {
                        "last_fill_time": datetime.now().isoformat()
                    })

            # 详细日志输出
            logger.info(f"📊 {symbol}:")
            logger.info(f"  ├─ Ideal Position: {ideal_pos:+.4f}")
            logger.info(f"  ├─ Actual Position: {actual_pos:+.4f}")
            logger.info(f"  ├─ Offset: {new_offset:+.4f} ({offset_usd:.2f} USD)")
            logger.info(f"  ├─ Cost Basis: ${new_cost:.2f} (Previous: ${old_cost:.2f})")

            # 显示偏移方向
            if new_offset > 0:
                logger.info(f"  └─ Status: 🔴 LONG exposure (Need to SELL {abs(new_offset):.4f})")
            elif new_offset < 0:
                logger.info(f"  └─ Status: 🟢 SHORT exposure (Need to BUY {abs(new_offset):.4f})")
            else:
                logger.info(f"  └─ Status: ✅ BALANCED")

            # 更新状态（包括actual position）
            await self.state_manager.update_symbol_state(symbol, {
                "offset": new_offset,
                "cost_basis": new_cost,
                "last_actual_position": actual_pos
            })

        context.offsets = offsets
        logger.info(f"✅ Calculated offsets for {len(offsets)} symbols")
        return offsets


class ApplyPredefinedOffsetStep(PipelineStep):
    """应用预设偏移量步骤 - 处理外部对冲调整"""

    def __init__(self):
        super().__init__(
            name="ApplyPredefinedOffset",
            required=False,  # 非必需，如果没有配置就跳过
            retry_times=0,
            timeout=5
        )

    async def _run(self, context: PipelineContext) -> Dict[str, Tuple[float, float]]:
        """应用预设的偏移量调整（用于外部对冲）"""
        predefined = context.config.get("predefined_offset", {})

        if not predefined:
            logger.info("✅ No predefined offset configured, skipping")
            return context.offsets

        logger.info("=" * 50)
        logger.info("🔧 APPLYING PREDEFINED OFFSETS")
        logger.info("=" * 50)

        # 保存原始offset用于对比和调试
        context.metadata["raw_offsets"] = context.offsets.copy()

        adjusted_count = 0
        for symbol, adjustment in predefined.items():
            if symbol in context.offsets:
                old_offset, cost_basis = context.offsets[symbol]
                new_offset = old_offset - adjustment

                # 计算USD价值
                if symbol in context.prices:
                    old_offset_usd = abs(old_offset) * context.prices[symbol]
                    new_offset_usd = abs(new_offset) * context.prices[symbol]

                    logger.info(f"📊 {symbol}:")
                    logger.info(f"  ├─ Raw Offset: {old_offset:+.6f} (${old_offset_usd:.2f})")
                    logger.info(f"  ├─ Adjustment: {adjustment:+.6f} (external hedge)")
                    logger.info(f"  └─ Final Offset: {new_offset:+.6f} (${new_offset_usd:.2f})")

                    # 更新context
                    context.offsets[symbol] = (new_offset, cost_basis)
                    adjusted_count += 1
            else:
                logger.warning(f"⚠️ Symbol {symbol} has predefined offset but no calculated offset, skipping")

        logger.info(f"✅ Applied predefined offsets for {adjusted_count} symbols")
        return context.offsets


class DecideActionsStep(PipelineStep):
    """决策步骤 - 使用决策引擎决定需要执行的操作"""

    def __init__(self, decision_engine):
        super().__init__(
            name="DecideActions",
            required=True,
            retry_times=0,
            timeout=10
        )
        self.decision_engine = decision_engine

    async def _run(self, context: PipelineContext) -> List[Any]:
        """根据市场数据决定操作"""
        logger.info("=" * 50)
        logger.info("🤔 DECISION ENGINE - EVALUATING ACTIONS")
        logger.info("=" * 50)

        # 准备决策数据
        market_data = {}

        # 显示阈值配置
        threshold_min = self.decision_engine.threshold_min_usd
        threshold_max = self.decision_engine.threshold_max_usd
        threshold_step = self.decision_engine.threshold_step_usd
        logger.info(f"⚡ Thresholds: ${threshold_min:.2f} - ${threshold_max:.2f} (Step: ${threshold_step:.2f})")

        for symbol, (offset, cost_basis) in context.offsets.items():
            if symbol not in context.prices:
                logger.warning(f"⚠️ Skipping {symbol} - no price data")
                continue

            current_price = context.prices[symbol]
            offset_usd = abs(offset) * current_price

            market_data[symbol] = {
                "offset": offset,
                "cost_basis": cost_basis,
                "current_price": current_price,
                "offset_usd": offset_usd
            }

            # 显示币种评估
            zone = self.decision_engine.get_zone(offset_usd)
            logger.info(f"🎯 {symbol}: Offset ${offset_usd:.2f} → Zone {zone}")

        # 批量决策
        actions = await self.decision_engine.batch_decide(market_data)

        # 显示决策结果
        logger.info("📋 DECISIONS:")
        action_counts = {}
        for action in actions:
            action_type = action.type.value
            action_counts[action_type] = action_counts.get(action_type, 0) + 1

            # 根据不同操作类型显示详细信息
            if action.type.value == "place_limit_order":
                logger.info(f"  📝 {action.symbol}: PLACE LIMIT {action.side.upper()} "
                           f"{action.size:.4f} @ ${action.price:.2f} - {action.reason}")
            elif action.type.value == "place_market_order":
                logger.info(f"  🚨 {action.symbol}: PLACE MARKET {action.side.upper()} "
                           f"{action.size:.4f} - {action.reason}")
            elif action.type.value == "cancel_order":
                logger.info(f"  ❌ {action.symbol}: CANCEL ORDER {action.order_id} - {action.reason}")
            elif action.type.value == "alert":
                logger.info(f"  ⚠️ {action.symbol}: ALERT - {action.reason}")
            elif action.type.value == "no_action":
                logger.debug(f"  ✅ {action.symbol}: NO ACTION - {action.reason}")

        # 显示汇总
        logger.info(f"📊 Summary: {action_counts}")

        context.actions = actions
        logger.info(f"✅ Decided on {len(actions)} actions")
        return actions


class ExecuteActionsStep(PipelineStep):
    """执行操作步骤 - 使用操作执行器执行所有决策"""

    def __init__(self, action_executor):
        super().__init__(
            name="ExecuteActions",
            required=False,  # 执行失败不停止管道
            retry_times=1,
            timeout=60
        )
        self.action_executor = action_executor

    async def _run(self, context: PipelineContext) -> List[Any]:
        """执行所有决定的操作"""
        if not context.actions:
            logger.info("✅ No actions to execute")
            return []

        logger.info("=" * 50)
        logger.info("⚡ EXECUTING ACTIONS")
        logger.info("=" * 50)

        logger.info(f"🎯 Executing {len(context.actions)} actions...")

        # 使用执行器批量执行
        # 注意：这里使用串行执行以避免竞态条件
        results = await self.action_executor.batch_execute(
            context.actions,
            parallel=False
        )

        # 显示执行结果
        logger.info("📊 EXECUTION RESULTS:")
        for i, result in enumerate(results, 1):
            action = result.action
            if result.success:
                if action.type.value == "place_limit_order":
                    logger.info(f"  ✅ [{i}] {action.symbol}: Limit order placed - "
                               f"{action.side.upper()} {action.size:.4f} @ ${action.price:.2f} "
                               f"(Order ID: {result.result})")
                elif action.type.value == "place_market_order":
                    logger.info(f"  ✅ [{i}] {action.symbol}: Market order executed - "
                               f"{action.side.upper()} {action.size:.4f} "
                               f"(Order ID: {result.result})")
                elif action.type.value == "cancel_order":
                    logger.info(f"  ✅ [{i}] {action.symbol}: Order cancelled - ID: {action.order_id}")
                elif action.type.value == "alert":
                    logger.info(f"  ✅ [{i}] {action.symbol}: Alert sent - {action.reason}")
                elif action.type.value == "no_action":
                    logger.debug(f"  ✅ [{i}] {action.symbol}: No action taken")
            else:
                logger.error(f"  ❌ [{i}] {action.symbol}: Failed to {action.type.value} - "
                            f"Error: {result.error}")

        # 统计执行结果
        success_count = sum(1 for r in results if r.success)
        failed_count = len(results) - success_count

        # 显示统计信息
        stats = self.action_executor.get_stats()
        logger.info("📈 EXECUTION STATISTICS:")
        logger.info(f"  • Total Actions: {len(results)}")
        logger.info(f"  • Successful: {success_count}")
        logger.info(f"  • Failed: {failed_count}")
        logger.info(f"  • Success Rate: {stats.get('success_rate', 0)*100:.1f}%")

        # 按类型显示统计
        if stats.get('by_type'):
            logger.info("  • By Type:")
            for action_type, type_stats in stats['by_type'].items():
                logger.info(f"    - {action_type}: {type_stats['success']} success, "
                           f"{type_stats['failed']} failed")

        # 将结果存入上下文
        context.metadata["execution_results"] = results
        context.metadata["execution_stats"] = stats

        logger.info(f"✅ Execution complete: {success_count}/{len(results)} successful")
        return results


# ==================== 管道工厂 ====================

def create_hedge_pipeline(
    pool_calculators: Dict[str, Any],
    exchange,
    state_manager,
    offset_calculator,
    decision_engine,
    action_executor
) -> HedgePipeline:
    """
    创建完整的对冲处理管道

    Args:
        pool_calculators: 池子计算器字典
        exchange: 交易所接口
        state_manager: 状态管理器
        offset_calculator: 偏移计算函数
        decision_engine: 决策引擎
        action_executor: 操作执行器

    Returns:
        配置好的管道实例
    """
    pipeline = HedgePipeline()

    # 添加中间件
    pipeline.add_middleware(logging_middleware)
    pipeline.add_middleware(timing_middleware)
    pipeline.add_middleware(error_collection_middleware)

    # 添加处理步骤
    pipeline.add_step(FetchPoolDataStep(pool_calculators))
    pipeline.add_step(CalculateIdealHedgesStep())
    pipeline.add_step(FetchMarketDataStep(exchange))
    pipeline.add_step(CalculateOffsetsStep(offset_calculator, state_manager))
    pipeline.add_step(ApplyPredefinedOffsetStep())  # 应用外部对冲调整
    pipeline.add_step(DecideActionsStep(decision_engine))
    pipeline.add_step(ExecuteActionsStep(action_executor))

    return pipeline


# ==================== 中间件 ====================

async def logging_middleware(context: PipelineContext, phase: str):
    """日志中间件（自动遮蔽敏感信息）"""
    if phase == "before":
        from utils.logging_utils import mask_sensitive_data
        masked_config = mask_sensitive_data(context.config)
        logger.debug(f"Pipeline starting with config: {masked_config}")
    elif phase == "after":
        success_count = sum(1 for r in context.results if r.status == StepStatus.SUCCESS)
        logger.info(f"Pipeline completed with {success_count}/{len(context.results)} successful steps")


async def timing_middleware(context: PipelineContext, phase: str):
    """计时中间件"""
    if phase == "before":
        context.metadata["start_time"] = time.time()
    elif phase == "after":
        duration = time.time() - context.metadata.get("start_time", 0)
        context.metadata["total_duration"] = duration
        logger.info(f"Pipeline total execution time: {duration:.2f}s")


def error_collection_middleware(context: PipelineContext, phase: str):
    """错误收集中间件"""
    if phase == "after":
        errors = [r for r in context.results if r.status == StepStatus.FAILED]
        if errors:
            context.metadata["errors"] = [
                {
                    "step": r.name,
                    "error": str(r.error),
                    "timestamp": r.timestamp.isoformat()
                }
                for r in errors
            ]
            logger.warning(f"Pipeline completed with {len(errors)} errors")