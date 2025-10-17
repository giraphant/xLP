#!/usr/bin/env python3
"""
对冲引擎核心模块
负责计算偏移、判断区间、执行平仓逻辑
"""

import json
import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from pathlib import Path

# 导入本地模块
from exchanges.interface import create_exchange
from notifications.pushover import Notifier
from core.offset_tracker import calculate_offset_and_cost
from core.state_manager import StateManager
from core.circuit_breaker import CircuitBreaker, CircuitBreakerManager
from core.exceptions import (
    HedgeEngineError,
    ChainReadError,
    ExchangeError,
    OrderPlacementError,
    OrderCancellationError,
    InvalidConfigError,
    MissingConfigError,
    CalculationError,
    classify_exception,
    should_retry,
    get_retry_delay
)
from pools import jlp, alp

logger = logging.getLogger(__name__)


class HedgeEngine:
    def __init__(self, config_path: str = "config.json", state_path: str = "data/state.json"):
        self.config_path = Path(config_path)
        self.state_path = Path(state_path)

        # 加载并验证配置
        self.config = self._load_config()
        self._validate_config()

        # 初始化状态管理器
        self.state_manager = StateManager(
            state_path=self.state_path,
            backup_dir=Path("data/backups")
        )

        # 初始化熔断器管理器
        self.circuit_manager = CircuitBreakerManager()

        # 初始化交易所和通知器
        self.exchange = create_exchange(self.config["exchange"])
        self.notifier = Notifier(self.config["pushover"])

    def _load_config(self) -> dict:
        """
        加载配置 - 优先使用环境变量，config.json作为默认值
        环境变量 > config.json
        """
        # 从config.json加载默认值（如果存在）
        config = {}
        if self.config_path.exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

        # 从环境变量覆盖（优先级更高）
        config["jlp_amount"] = float(os.getenv("JLP_AMOUNT", config.get("jlp_amount", 50000)))
        config["alp_amount"] = float(os.getenv("ALP_AMOUNT", config.get("alp_amount", 10000)))

        config["threshold_min_usd"] = float(os.getenv("THRESHOLD_MIN_USD", config.get("threshold_min_usd", 5.0)))
        config["threshold_max_usd"] = float(os.getenv("THRESHOLD_MAX_USD", config.get("threshold_max_usd", 20.0)))
        config["threshold_step_usd"] = float(os.getenv("THRESHOLD_STEP_USD", config.get("threshold_step_usd", 2.5)))
        config["order_price_offset"] = float(os.getenv("ORDER_PRICE_OFFSET", config.get("order_price_offset", 0.2)))
        config["close_ratio"] = float(os.getenv("CLOSE_RATIO", config.get("close_ratio", 40.0)))
        config["timeout_minutes"] = int(os.getenv("TIMEOUT_MINUTES", config.get("timeout_minutes", 20)))
        config["check_interval_seconds"] = int(os.getenv("CHECK_INTERVAL_SECONDS", config.get("check_interval_seconds", 60)))

        # 初始偏移量（从环境变量或config.json）
        initial_offset = config.get("initial_offset", {})
        config["initial_offset"] = {
            "SOL": float(os.getenv("INITIAL_OFFSET_SOL", initial_offset.get("SOL", 0.0))),
            "ETH": float(os.getenv("INITIAL_OFFSET_ETH", initial_offset.get("ETH", 0.0))),
            "BTC": float(os.getenv("INITIAL_OFFSET_BTC", initial_offset.get("BTC", 0.0))),
            "BONK": float(os.getenv("INITIAL_OFFSET_BONK", initial_offset.get("BONK", 0.0))),
        }

        # Exchange配置
        exchange_config = config.get("exchange", {})
        config["exchange"] = {
            "name": os.getenv("EXCHANGE_NAME", exchange_config.get("name", "mock")),
            "private_key": os.getenv("EXCHANGE_PRIVATE_KEY", exchange_config.get("private_key", "")),
            "account_index": int(os.getenv("EXCHANGE_ACCOUNT_INDEX", exchange_config.get("account_index", 0))),
            "api_key_index": int(os.getenv("EXCHANGE_API_KEY_INDEX", exchange_config.get("api_key_index", 0))),
            "base_url": os.getenv("EXCHANGE_BASE_URL", exchange_config.get("base_url", "https://mainnet.zklighter.elliot.ai")),
        }

        # Pushover配置
        pushover_config = config.get("pushover", {})
        config["pushover"] = {
            "user_key": os.getenv("PUSHOVER_USER_KEY", pushover_config.get("user_key", "")),
            "api_token": os.getenv("PUSHOVER_API_TOKEN", pushover_config.get("api_token", "")),
            "enabled": os.getenv("PUSHOVER_ENABLED", str(pushover_config.get("enabled", True))).lower() in ("true", "1", "yes"),
        }

        # RPC URL
        config["rpc_url"] = os.getenv("RPC_URL", config.get("rpc_url", "https://api.mainnet-beta.solana.com"))

        return config

    def _validate_config(self):
        """验证配置完整性和合理性"""
        required_fields = ['jlp_amount', 'alp_amount', 'exchange', 'threshold_min_usd', 'threshold_max_usd']

        # 检查必要字段
        for field in required_fields:
            if field not in self.config:
                raise MissingConfigError(field)

        # 验证阈值关系
        if self.config['threshold_min_usd'] >= self.config['threshold_max_usd']:
            raise InvalidConfigError(
                'threshold_min_usd/threshold_max_usd',
                f"min={self.config['threshold_min_usd']}, max={self.config['threshold_max_usd']}",
                "threshold_min must be less than threshold_max"
            )

        # 验证close_ratio
        if not 0 < self.config['close_ratio'] <= 100:
            raise InvalidConfigError(
                'close_ratio',
                self.config['close_ratio'],
                "must be between 0 and 100"
            )

        logger.info("Configuration validated successfully")

    async def get_ideal_hedges(self, pool_type: str, amount: float) -> Dict[str, float]:
        """
        获取理想对冲量（带熔断保护）

        Args:
            pool_type: "jlp" 或 "alp"
            amount: JLP或ALP数量

        Returns:
            {"SOL": -100.5, "ETH": -5.2, "BTC": -0.5, ...} 负数表示做空
        """
        # 获取对应池子的熔断器
        breaker = await self.circuit_manager.get_or_create(
            f"pool_{pool_type}",
            failure_threshold=3,
            timeout=60
        )

        try:
            # 通过熔断器调用池子计算
            if pool_type == "jlp":
                positions = await breaker.call(jlp.calculate_hedge, amount)
            elif pool_type == "alp":
                positions = await breaker.call(alp.calculate_hedge, amount)
            else:
                raise ValueError(f"Unknown pool type: {pool_type}")

            # 转换为做空量（负数），并将WBTC重命名为BTC
            result = {}
            for symbol, data in positions.items():
                exchange_symbol = "BTC" if symbol == "WBTC" else symbol
                result[exchange_symbol] = -data["amount"]

            return result

        except Exception as e:
            # 包装并重新抛出链读取错误
            raise ChainReadError(
                f"{pool_type}_pool",
                f"Failed to calculate hedge for {pool_type}",
                e
            )

    def get_zone(self, offset_usd: float) -> Optional[int]:
        """
        根据偏移USD绝对值计算所在区间

        Args:
            offset_usd: 偏移USD价值（绝对值）

        Returns:
            None: 低于最低阈值
            0-N: 区间编号
            -1: 超过最高阈值（警报）
        """
        abs_usd = abs(offset_usd)

        if abs_usd < self.config["threshold_min_usd"]:
            return None

        if abs_usd > self.config["threshold_max_usd"]:
            return -1

        # 计算区间
        zone = int((abs_usd - self.config["threshold_min_usd"]) / self.config["threshold_step_usd"])
        return zone

    def _calculate_close_size(self, offset: float) -> float:
        """
        计算平仓数量

        Args:
            offset: 偏移量（正数或负数）

        Returns:
            应平仓的数量（根据close_ratio配置）
        """
        return abs(offset) * (self.config["close_ratio"] / 100)

    def calculate_order_price(
        self,
        cost_basis: float,
        offset: float,
        price_offset_pct: float
    ) -> float:
        """
        计算挂单价格

        Args:
            cost_basis: 成本基础
            offset: 偏移量（正=多头敞口，负=空头敞口）
            price_offset_pct: 价格偏移百分比（如0.2表示0.2%）

        Returns:
            挂单价格
        """
        if offset > 0:
            # 多头敞口：需要卖出平仓，挂高价
            return cost_basis * (1 + price_offset_pct / 100)
        else:
            # 空头敞口：需要买入平仓，挂低价
            return cost_basis * (1 - price_offset_pct / 100)

    async def process_symbol(
        self,
        symbol: str,
        ideal_position: float,
        current_price: float
    ):
        """
        处理单个币种的对冲逻辑（使用新的状态管理器）

        Args:
            symbol: 币种符号
            ideal_position: 理想持仓
            current_price: 当前价格
        """
        # 从状态管理器获取币种状态
        state = await self.state_manager.get_symbol_state(symbol)

        # 从交易所获取实际持仓
        actual_position = await self.exchange.get_position(symbol)
        # 加上初始偏移量（用于手动调整基准）
        actual_position += self.config["initial_offset"].get(symbol, 0.0)

        # 计算偏移和成本（使用原子模块）
        old_offset = state["offset"]
        old_cost = state["cost_basis"]
        new_offset, new_cost = calculate_offset_and_cost(
            ideal_position, actual_position, current_price, old_offset, old_cost
        )

        # 更新状态到状态管理器
        await self.state_manager.update_symbol_state(symbol, {
            "offset": new_offset,
            "cost_basis": new_cost
        })

        # 计算偏移USD绝对值
        offset_usd = abs(new_offset) * current_price

        # 判断区间
        new_zone = self.get_zone(offset_usd)
        current_zone = state.get("monitoring", {}).get("current_zone")
        is_monitoring = state.get("monitoring", {}).get("active", False)

        logger.info(f"{symbol}: actual_pos={actual_position:.4f}, ideal_pos={ideal_position:.4f}, offset={new_offset:.4f}, cost=${new_cost:.2f}, zone={new_zone}, offset_usd=${offset_usd:.2f}")

        # 处理超阈值警报
        if new_zone == -1:
            logger.warning(f"[{symbol}] 超过最高阈值！偏移 ${offset_usd:.2f}")

            # 撤单
            if state.get("monitoring", {}).get("order_id"):
                try:
                    await self.exchange.cancel_order(state["monitoring"]["order_id"])
                except OrderCancellationError as e:
                    logger.error(f"Failed to cancel order: {e}")

            # 发送Pushover警报
            await self.notifier.alert_threshold_exceeded(
                symbol, offset_usd, new_offset, current_price
            )

            # 重置监控状态
            await self.state_manager.reset_symbol_monitoring(symbol)
            await self.state_manager.save_state()
            return

        # 处理区间变化
        if new_zone != current_zone:
            # 区间变化，需要撤单重挂
            if is_monitoring and state.get("monitoring", {}).get("order_id"):
                logger.info(f"区间变化 {current_zone} → {new_zone}，撤销旧单")
                try:
                    await self.exchange.cancel_order(state["monitoring"]["order_id"])
                except OrderCancellationError as e:
                    logger.error(f"Failed to cancel order: {e}")

            if new_zone is None:
                # 回到阈值内，停止监控
                logger.info(f"偏移回到阈值内，停止监控")
                await self.state_manager.reset_symbol_monitoring(symbol)
            else:
                # 新区间，重新挂单
                order_price = self.calculate_order_price(
                    new_cost, new_offset, self.config["order_price_offset"]
                )
                order_size = self._calculate_close_size(new_offset)
                side = "sell" if new_offset > 0 else "buy"

                logger.info(f"进入区间 {new_zone}，挂单: {side} {order_size:.4f} @ ${order_price:.2f}")

                try:
                    # 通过熔断器下单
                    exchange_breaker = await self.circuit_manager.get_or_create(
                        f"exchange_{symbol}",
                        failure_threshold=3,
                        timeout=30
                    )

                    order_id = await exchange_breaker.call(
                        self.exchange.place_limit_order,
                        symbol, side, order_size, order_price
                    )

                    # 更新监控状态
                    await self.state_manager.update_symbol_state(symbol, {
                        "monitoring": {
                            "active": True,
                            "current_zone": new_zone,
                            "order_id": order_id,
                            "started_at": datetime.now().isoformat()
                        }
                    })

                    # 增加订单计数
                    await self.state_manager.increment_counter(symbol, "stats.total_orders")

                except OrderPlacementError as e:
                    logger.error(f"Failed to place order: {e}")
                    await self.notifier.alert_order_failed(symbol, side, order_size, str(e))

        # 检查超时
        if is_monitoring and state.get("monitoring", {}).get("started_at"):
            started_at = datetime.fromisoformat(state["monitoring"]["started_at"])
            elapsed = (datetime.now() - started_at).total_seconds() / 60
            timeout = self.config["timeout_minutes"]

            if elapsed >= timeout:
                logger.warning(f"超时 {elapsed:.1f}分钟，强制市价平仓")

                # 撤单
                if state.get("monitoring", {}).get("order_id"):
                    try:
                        await self.exchange.cancel_order(state["monitoring"]["order_id"])
                    except OrderCancellationError as e:
                        logger.error(f"Failed to cancel order: {e}")

                # 市价平仓
                order_size = self._calculate_close_size(new_offset)
                side = "sell" if new_offset > 0 else "buy"

                try:
                    # 通过熔断器执行市价单
                    exchange_breaker = await self.circuit_manager.get_or_create(
                        f"exchange_{symbol}",
                        failure_threshold=3,
                        timeout=30
                    )

                    await exchange_breaker.call(
                        self.exchange.place_market_order,
                        symbol, side, order_size
                    )

                    await self.notifier.alert_force_close(symbol, order_size, side)

                    # 更新统计
                    await self.state_manager.increment_counter(symbol, "stats.forced_closes")

                except OrderPlacementError as e:
                    logger.error(f"Failed to place market order: {e}")
                    # 市价单失败是严重问题，需要通知
                    await self.notifier.alert_critical_error(
                        f"Market order failed for {symbol}",
                        str(e)
                    )

                # 重置监控状态
                await self.state_manager.reset_symbol_monitoring(symbol)

        # 保存状态
        await self.state_manager.save_state()

    async def run_once(self):
        """执行一次检查循环（带错误处理）"""
        logger.info(f"{'='*60}")
        logger.info(f"检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{'='*60}")

        try:
            # 1. 获取JLP和ALP的理想对冲量
            jlp_hedges = await self.get_ideal_hedges("jlp", self.config["jlp_amount"])
            alp_hedges = await self.get_ideal_hedges("alp", self.config["alp_amount"])

            # 2. 合并对冲量（按币种）
            all_symbols = set(jlp_hedges.keys()) | set(alp_hedges.keys())
            merged_hedges = {}
            for symbol in all_symbols:
                jlp_amount = jlp_hedges.get(symbol, 0.0)
                alp_amount = alp_hedges.get(symbol, 0.0)
                merged_hedges[symbol] = jlp_amount + alp_amount

            # 3. 获取所有需要的价格（通过熔断器）
            prices = {}
            for symbol in merged_hedges.keys():
                price_breaker = await self.circuit_manager.get_or_create(
                    f"price_{symbol}",
                    failure_threshold=5,
                    timeout=30
                )
                try:
                    price = await price_breaker.call(self.exchange.get_price, symbol)
                    prices[symbol] = price
                except Exception as e:
                    logger.error(f"Failed to get price for {symbol}: {e}")
                    # 使用上次的价格或跳过
                    continue

            # 4. 统一处理每个币种
            for symbol, ideal_pos in merged_hedges.items():
                if symbol not in prices:
                    logger.warning(f"Skipping {symbol} due to missing price")
                    continue

                current_price = prices[symbol]

                try:
                    await self.process_symbol(symbol, ideal_pos, current_price)
                except HedgeEngineError as e:
                    logger.error(f"Failed to process {symbol}: {e}")
                    if e.should_notify:
                        await self.notifier.alert_error(symbol, str(e))
                except Exception as e:
                    logger.error(f"Unexpected error processing {symbol}: {e}")

            # 更新元数据
            await self.state_manager.update_metadata({
                "last_check": datetime.now().isoformat(),
                "total_runs": (await self.state_manager.get_metadata()).get("total_runs", 0) + 1
            })

            # 清理超时的订单监控
            await self.state_manager.cleanup_stale_orders()

            # 最终保存状态
            await self.state_manager.save_state()

            # 清理空闲的熔断器
            self.circuit_manager.cleanup_idle()

        except Exception as e:
            logger.error(f"Error in run_once: {e}")
            # 记录最后的错误
            await self.state_manager.update_metadata({
                "last_error": str(e),
                "last_error_time": datetime.now().isoformat()
            })
            raise


async def main():
    """测试主函数"""
    engine = HedgeEngine()
    await engine.run_once()


if __name__ == "__main__":
    asyncio.run(main())
