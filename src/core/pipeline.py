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
    'CalculateZonesStep',  # 🆕
    'ApplyCooldownFilterStep',  # 🆕
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
    zones: Dict[str, Optional[int]] = field(default_factory=dict)  # Zone编号
    cooldown_status: Dict[str, str] = field(default_factory=dict)  # "normal" | "skip" | "cancel_only"
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

            # 更新状态
            await self.state_manager.update_symbol_state(symbol, {
                "offset": new_offset,
                "cost_basis": new_cost
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


class CalculateZonesStep(PipelineStep):
    """计算Zone步骤 - 将offset转换为zone编号"""

    def __init__(self, decision_engine):
        super().__init__(
            name="CalculateZones",
            required=True,
            retry_times=0,
            timeout=5
        )
        self.decision_engine = decision_engine

    async def _run(self, context: PipelineContext) -> Dict[str, Optional[int]]:
        """计算所有币种的zone"""
        zones = {}

        logger.info("=" * 50)
        logger.info("📐 CALCULATING ZONES")
        logger.info("=" * 50)

        for symbol, (offset, cost_basis) in context.offsets.items():
            if symbol not in context.prices:
                logger.warning(f"⚠️ Skipping {symbol} - no price data")
                continue

            # 计算offset的USD价值
            offset_usd = abs(offset) * context.prices[symbol]

            # 使用DecisionEngine的get_zone方法
            zone = self.decision_engine.get_zone(offset_usd)

            zones[symbol] = zone

            # 日志输出
            if zone is None:
                logger.info(f"  ✅ {symbol}: ${offset_usd:.2f} → No zone (within threshold)")
            elif zone == -1:
                logger.warning(f"  ⚠️ {symbol}: ${offset_usd:.2f} → Zone -1 (EXCEEDED MAX!)")
            else:
                logger.info(f"  📍 {symbol}: ${offset_usd:.2f} → Zone {zone}")

        context.zones = zones
        logger.info(f"✅ Calculated zones for {len(zones)} symbols")
        return zones


class ApplyCooldownFilterStep(PipelineStep):
    """Cooldown过滤器 - 检测成交并决定是否允许决策"""

    def __init__(self, state_manager, cooldown_minutes=5):
        super().__init__(
            name="ApplyCooldownFilter",
            required=True,
            retry_times=0,
            timeout=10
        )
        self.state_manager = state_manager
        self.cooldown_minutes = cooldown_minutes

    async def _run(self, context: PipelineContext) -> Dict[str, str]:
        """
        检测position变化并应用cooldown逻辑

        返回: cooldown_status = {
            "SOL": "normal",     # 正常决策
            "ETH": "skip",        # Cooldown期间zone改善，跳过
            "BTC": "cancel_only", # Cooldown期间zone→None，只撤单
        }
        """
        cooldown_status = {}

        logger.info("=" * 50)
        logger.info("🧊 COOLDOWN FILTER")
        logger.info("=" * 50)

        for symbol in context.zones.keys():
            state = await self.state_manager.get_symbol_state(symbol)

            # === Part A: 检测position变化（订单成交）===
            old_pos = state.get("last_actual_position")
            new_pos = context.actual_positions.get(symbol, 0.0)

            # ⭐ 保存成交前的zone（用于Part C比较）
            old_zone_before_fill = state.get("last_zone")

            # 首次初始化：如果从未记录过position，现在记录
            if old_pos is None:
                await self.state_manager.update_symbol_state(symbol, {
                    "last_actual_position": new_pos
                })
                logger.debug(f"  📝 {symbol}: Initialized position tracking at {new_pos:+.4f}")
                old_pos = new_pos  # 更新局部变量，避免误判为position变化

            # 检测position变化
            if abs(new_pos - old_pos) > 0.0001:
                # Position变化 → 订单成交了！
                logger.info(f"  ⚡ {symbol}: Position changed {old_pos:+.4f} → {new_pos:+.4f} (Δ{new_pos - old_pos:+.4f})")

                # 记录成交时间（注意：zone在Part C之后才更新）
                await self.state_manager.update_symbol_state(symbol, {
                    "last_fill_time": datetime.now().isoformat(),
                    "last_actual_position": new_pos
                    # last_zone暂不更新，等Part C判断完再更新
                })

                logger.info(f"  📝 {symbol}: Fill detected, cooldown reset")

            # === Part B: 检查是否在cooldown期间 ===
            last_fill_time_str = state.get("last_fill_time")

            if not last_fill_time_str:
                # 从未成交过，记录当前zone作为baseline
                cooldown_status[symbol] = "normal"
                await self.state_manager.update_symbol_state(symbol, {
                    "last_zone": context.zones[symbol]
                })
                logger.debug(f"  ✅ {symbol}: No fill history, normal mode (zone={context.zones[symbol]})")
                continue

            # 计算距离上次成交的时间
            last_fill_time = datetime.fromisoformat(last_fill_time_str)
            elapsed_min = (datetime.now() - last_fill_time).total_seconds() / 60

            if elapsed_min >= self.cooldown_minutes:
                # Cooldown结束，记录当前zone
                cooldown_status[symbol] = "normal"
                await self.state_manager.update_symbol_state(symbol, {
                    "last_zone": context.zones[symbol]
                })
                logger.debug(f"  ✅ {symbol}: Cooldown ended ({elapsed_min:.1f}min), normal mode (zone={context.zones[symbol]})")
                continue

            # === Part C: Cooldown期间的判断 ===
            cooldown_remaining = self.cooldown_minutes - elapsed_min

            # 使用成交前的zone来比较（old_zone_before_fill在Part A保存）
            old_zone = old_zone_before_fill
            new_zone = context.zones[symbol]

            logger.info(f"  🧊 {symbol}: In cooldown ({cooldown_remaining:.1f}min remaining), zone {old_zone} → {new_zone}")

            if new_zone is None:
                # Zone → None (回到阈值内)
                cooldown_status[symbol] = "cancel_only"
                logger.info(f"     → CANCEL_ONLY (back within threshold)")

            elif old_zone is None:
                # 上次成交时zone=None（在阈值内），现在进入zone了，应该允许挂单
                cooldown_status[symbol] = "normal"
                logger.info(f"     → NORMAL (previous fill was within threshold, now in zone {new_zone})")

            elif new_zone > old_zone:
                # Zone恶化 (数字变大) - offset绝对值增大
                cooldown_status[symbol] = "normal"
                logger.warning(f"     → NORMAL (zone worsened {old_zone}→{new_zone}, re-order needed)")

            else:
                # Zone改善或持平 - offset绝对值减小或不变
                cooldown_status[symbol] = "skip"
                logger.info(f"     → SKIP (zone improved/stable {old_zone}→{new_zone}, waiting for natural regression)")

            # Part C结束后，更新last_zone为当前zone（供下次比较使用）
            await self.state_manager.update_symbol_state(symbol, {
                "last_zone": new_zone
            })

        context.cooldown_status = cooldown_status
        logger.info(f"✅ Cooldown filter applied: {len(cooldown_status)} symbols")
        return cooldown_status


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

        # 显示阈值配置
        threshold_min = self.decision_engine.threshold_min_usd
        threshold_max = self.decision_engine.threshold_max_usd
        threshold_step = self.decision_engine.threshold_step_usd
        logger.info(f"⚡ Thresholds: ${threshold_min:.2f} - ${threshold_max:.2f} (Step: ${threshold_step:.2f})")

        # 先处理cooldown过滤的symbols
        actions = []
        market_data = {}  # 只包含需要正常决策的symbols

        for symbol, (offset, cost_basis) in context.offsets.items():
            if symbol not in context.prices:
                logger.warning(f"⚠️ Skipping {symbol} - no price data")
                continue

            current_price = context.prices[symbol]
            offset_usd = abs(offset) * current_price

            # 显示币种评估
            zone = context.zones.get(symbol)
            cooldown_status = context.cooldown_status.get(symbol, "normal")
            logger.info(f"🎯 {symbol}: Offset ${offset_usd:.2f} → Zone {zone} (Cooldown: {cooldown_status})")

            # 根据cooldown状态处理
            if cooldown_status == "skip":
                # Cooldown期间zone改善 - 跳过决策
                from core.decision_engine import TradingAction, ActionType
                actions.append(TradingAction(
                    type=ActionType.NO_ACTION,
                    symbol=symbol,
                    reason=f"In cooldown (zone improved), waiting for natural regression"
                ))
                logger.info(f"  → SKIP: {symbol} in cooldown, zone improved")
                continue

            elif cooldown_status == "cancel_only":
                # Cooldown期间回到阈值内 - 只撤单
                from core.decision_engine import TradingAction, ActionType

                # 获取现有订单
                state = await self.decision_engine.state_manager.get_symbol_state(symbol)
                existing_order_id = state.get("monitoring", {}).get("order_id")

                if existing_order_id:
                    actions.append(TradingAction(
                        type=ActionType.CANCEL_ORDER,
                        symbol=symbol,
                        order_id=existing_order_id,
                        reason="Back within threshold during cooldown"
                    ))

                actions.append(TradingAction(
                    type=ActionType.NO_ACTION,
                    symbol=symbol,
                    reason="Within threshold during cooldown"
                ))
                logger.info(f"  → CANCEL_ONLY: {symbol} back within threshold")
                continue

            # 状态为"normal"的symbols加入正常决策
            market_data[symbol] = {
                "offset": offset,
                "cost_basis": cost_basis,
                "current_price": current_price,
                "offset_usd": offset_usd
            }

        # 批量决策（只处理normal状态的symbols）
        if market_data:
            logger.info(f"📋 Processing {len(market_data)} symbols with normal decision logic")
            decision_actions = await self.decision_engine.batch_decide(market_data)
            actions.extend(decision_actions)
        else:
            logger.info(f"📋 All symbols filtered by cooldown, no normal decisions needed")

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
    action_executor,
    cooldown_minutes: int = 5
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
        cooldown_minutes: Cooldown时长（分钟）

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
    pipeline.add_step(CalculateZonesStep(decision_engine))  # 🆕 计算zones
    pipeline.add_step(ApplyCooldownFilterStep(state_manager, cooldown_minutes))  # 🆕 应用cooldown过滤
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