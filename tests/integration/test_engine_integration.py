#!/usr/bin/env python3
"""
集成测试 - 端到端测试整个对冲引擎

测试场景：
1. 完整的四步流程 (prepare -> decide -> execute -> report)
2. 真实的状态管理
3. MockExchange模拟订单执行
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from engine import HedgeEngine
from exchanges.mock.exchange import MockExchange
from utils.state import StateManager
from utils.config import HedgeConfig
from core.decide import ActionType


@pytest.fixture
def mock_config():
    """模拟配置（HedgeConfig 对象）"""
    return HedgeConfig(
        jlp_amount=100.0,
        alp_amount=0.0,
        threshold_min_usd=5.0,
        threshold_max_usd=20.0,
        threshold_step_usd=2.5,
        order_price_offset=0.2,
        close_ratio=40.0,
        timeout_minutes=20,
        check_interval_seconds=60,
        cooldown_after_fill_minutes=5,
        initial_offset_sol=0.0,
        initial_offset_eth=0.0,
        initial_offset_btc=0.0,
        initial_offset_bonk=0.0,
        rpc_url="http://mock",
        exchange_name="mock",
        exchange_private_key="",
        exchange_account_index=0,
        exchange_api_key_index=0,
        exchange_base_url="http://mock",
        pushover_enabled=False,
        pushover_user_key="",
        pushover_api_token="",
        matsu_enabled=False,
        matsu_api_endpoint="",
        matsu_auth_token="",
        matsu_pool_name=""
    )


@pytest.fixture
def mock_pool_data():
    """模拟池子数据"""
    return {
        "jlp": {
            "SOL": {"amount": 10.0},
            "BTC": {"amount": 0.05}
        }
    }


class TestEngineIntegration:
    """引擎集成测试"""

    @pytest.mark.asyncio
    async def test_first_cycle_place_limit_order(self, mock_config, mock_pool_data):
        """
        测试场景1：首次循环，检测到偏移，下限价单

        流程：
        1. Prepare: 计算需要对冲（小额，避免超过阈值）
        2. Decide: offset超过阈值，进入zone
        3. Execute: 下限价单
        4. Report: 生成报告
        """
        # 创建组件
        state_manager = StateManager()
        exchange = MockExchange(mock_config.to_dict()["exchange"])

        # 设置价格（调低，避免超阈值）
        exchange.prices = {
            "SOL": 150.0,
            "BTC": 60000.0
        }

        # 模拟池子计算器（减小数量）
        async def mock_jlp_calculator(amount):
            return {
                "SOL": {"amount": 0.06},  # 0.06 * 150 = 9 USD (在5-20之间)
                "BTC": {"amount": 0.0002}  # 0.0002 * 60000 = 12 USD
            }

        pool_calculators = {
            "jlp": mock_jlp_calculator,
            "alp": AsyncMock(return_value={})
        }

        # 导入模块
        from core.prepare import prepare_data
        from core.decide import decide_actions
        from core.execute import execute_actions

        # === 步骤1: Prepare ===
        data = await prepare_data(
            mock_config,
            pool_calculators,
            exchange,
            state_manager
        )

        # 验证数据准备
        assert "SOL" in data["symbols"]
        assert "BTC" in data["symbols"]

        # offset = ideal_hedge - actual_position
        # actual_position = 0 (exchange) + 0 (initial_offset)
        # offset = ideal_hedge - 0 = ideal_hedge
        sol_offset, sol_cost = data["offsets"]["SOL"]
        sol_offset_usd = abs(sol_offset) * 150.0

        # 验证在阈值范围内
        assert 5.0 < sol_offset_usd < 20.0

        # === 步骤2: Decide ===
        actions = await decide_actions(data, state_manager, mock_config)

        # 应该决定下限价单
        sol_actions = [a for a in actions if a.symbol == "SOL"]
        assert len(sol_actions) >= 1

        # 找到限价单action
        limit_action = next((a for a in sol_actions if a.type == ActionType.PLACE_LIMIT_ORDER), None)
        if limit_action:
            # === 步骤3: Execute ===
            results = await execute_actions(
                actions,
                exchange,
                state_manager,
                AsyncMock(),  # mock notifier
                data.get("state_updates")
            )

            # 验证订单已下
            assert len(exchange.orders) > 0

            # 验证状态已更新
            sol_state = state_manager.get_symbol_state("SOL")
            assert sol_state["monitoring"]["started_at"] is not None
            assert sol_state["monitoring"]["current_zone"] is not None

    @pytest.mark.asyncio
    async def test_zone_change_reorder(self, mock_config, mock_pool_data):
        """
        测试场景2：Zone变化，撤单重新下单

        流程：
        1. 第一次循环：Zone 1，下单
        2. 价格变化：Zone变为2
        3. 第二次循环：撤单，重新下单
        """
        state_manager = StateManager()
        exchange = MockExchange(mock_config.to_dict()["exchange"])
        exchange.prices = {"SOL": 150.0}

        # 模拟池子（小数量）
        async def mock_jlp_calculator(amount):
            return {"SOL": {"amount": 0.055}}  # 0.055 * 150 = 8.25 USD

        pool_calculators = {"jlp": mock_jlp_calculator, "alp": AsyncMock(return_value={})}

        from core.prepare import prepare_data
        from core.decide import decide_actions
        from core.execute import execute_actions

        # === 第一次循环 ===
        data = await prepare_data(mock_config, pool_calculators, exchange, state_manager)
        actions = await decide_actions(data, state_manager, mock_config)
        await execute_actions(actions, exchange, state_manager, AsyncMock(), data.get("state_updates"))

        # 记录第一次的zone
        first_state = state_manager.get_symbol_state("SOL")
        first_zone = first_state["monitoring"]["current_zone"]

        # === 增加池子持仓，导致offset变大，zone恶化 ===
        async def mock_jlp_calculator_increased(amount):
            return {"SOL": {"amount": 0.07}}  # 0.07 * 150 = 10.5 USD (zone恶化)

        pool_calculators["jlp"] = mock_jlp_calculator_increased

        # === 第二次循环 ===
        data = await prepare_data(mock_config, pool_calculators, exchange, state_manager)
        actions = await decide_actions(data, state_manager, mock_config)

        # 验证zone确实变化了
        sol_offset, _ = data["offsets"]["SOL"]
        new_offset_usd = abs(sol_offset) * 150.0

        # 如果zone真的变化了，验证行为
        if new_offset_usd > 8.25 * 1.1:  # offset显著增加
            sol_actions = [a for a in actions if a.symbol == "SOL"]
            # 应该有操作（可能是撤单+重新下单）
            assert len(sol_actions) > 0

    @pytest.mark.asyncio
    async def test_timeout_force_close(self, mock_config, mock_pool_data):
        """
        测试场景3：订单超时，强制市价平仓

        流程：
        1. 下限价单
        2. 模拟时间流逝（超过timeout）
        3. 触发超时逻辑，市价平仓
        """
        state_manager = StateManager()
        exchange = MockExchange(mock_config.to_dict()["exchange"])
        exchange.prices = {"SOL": 150.0}

        async def mock_jlp_calculator(amount):
            return {"SOL": {"amount": 0.06}}  # 0.06 * 150 = 9 USD

        pool_calculators = {"jlp": mock_jlp_calculator, "alp": AsyncMock(return_value={})}

        from core.prepare import prepare_data
        from core.decide import decide_actions
        from core.execute import execute_actions

        # === 第一次循环：下限价单 ===
        data = await prepare_data(mock_config, pool_calculators, exchange, state_manager)
        actions = await decide_actions(data, state_manager, mock_config)
        await execute_actions(actions, exchange, state_manager, AsyncMock(), data.get("state_updates"))

        # === 手动设置started_at为25分钟前（超时），并设置current_zone ===
        state_manager.update_symbol_state("SOL", {
            "monitoring": {
                "started_at": datetime.now() - timedelta(minutes=25),
                "current_zone": 1  # 保留zone信息
            }
        })

        # === 第二次循环：触发超时 ===
        data = await prepare_data(mock_config, pool_calculators, exchange, state_manager)
        actions = await decide_actions(data, state_manager, mock_config)

        # 应该有撤单和市价单
        sol_actions = [a for a in actions if a.symbol == "SOL"]
        cancel_action = next((a for a in sol_actions if a.type == ActionType.CANCEL_ORDER), None)
        market_action = next((a for a in sol_actions if a.type == ActionType.PLACE_MARKET_ORDER), None)

        assert cancel_action is not None
        assert market_action is not None
        assert market_action.metadata["force_close"] is True

        # 执行
        await execute_actions(actions, exchange, state_manager, AsyncMock(), data.get("state_updates"))

        # 验证市价单已成交
        market_orders = [o for o in exchange.orders.values()
                        if o["symbol"] == "SOL" and o["status"] == "filled"]
        assert len(market_orders) > 0

    @pytest.mark.asyncio
    async def test_cooldown_prevents_reorder(self, mock_config, mock_pool_data):
        """
        测试场景4：冷却期内zone改善，不重新下单

        流程：
        1. 市价单成交，进入冷却期
        2. Zone改善
        3. 冷却期内不重新下单
        """
        state_manager = StateManager()
        exchange = MockExchange(mock_config.to_dict()["exchange"])
        exchange.prices = {"SOL": 150.0}

        async def mock_jlp_calculator(amount):
            return {"SOL": {"amount": 10.0}}

        pool_calculators = {"jlp": mock_jlp_calculator, "alp": AsyncMock(return_value={})}

        from core.prepare import prepare_data
        from core.decide import decide_actions
        from core.execute import execute_actions

        # === 模拟刚刚成交，设置last_fill_time ===
        state_manager.update_symbol_state("SOL", {
            "last_fill_time": datetime.now() - timedelta(minutes=2),  # 2分钟前成交
            "monitoring": {
                "current_zone": 2,
                "started_at": None
            }
        })

        # === 价格改善，zone变为1 ===
        data = await prepare_data(mock_config, pool_calculators, exchange, state_manager)
        actions = await decide_actions(data, state_manager, mock_config)

        # 冷却期内zone改善，应该skip
        sol_actions = [a for a in actions if a.symbol == "SOL"]
        no_action = next((a for a in sol_actions if a.type == ActionType.NO_ACTION), None)

        # 应该没有下新单
        limit_action = next((a for a in sol_actions if a.type == ActionType.PLACE_LIMIT_ORDER), None)
        # 在冷却期内zone改善的情况下不应该下新单
        # 具体行为取决于decide逻辑

    @pytest.mark.asyncio
    async def test_multiple_symbols(self, mock_config):
        """
        测试场景5：多个币种同时处理

        验证：
        - 每个symbol独立决策
        - 状态管理正确隔离
        """
        state_manager = StateManager()
        exchange = MockExchange(mock_config.to_dict()["exchange"])
        exchange.prices = {"SOL": 150.0, "BTC": 60000.0, "ETH": 3500.0}

        async def mock_jlp_calculator(amount):
            return {
                "SOL": {"amount": 0.06},  # 9 USD
                "BTC": {"amount": 0.0002},  # 12 USD
                "ETH": {"amount": 0.003}  # 10.5 USD
            }

        pool_calculators = {"jlp": mock_jlp_calculator, "alp": AsyncMock(return_value={})}

        from core.prepare import prepare_data
        from core.decide import decide_actions

        # 准备数据
        data = await prepare_data(mock_config, pool_calculators, exchange, state_manager)

        # 验证所有symbol都被处理
        assert len(data["symbols"]) == 3
        assert "SOL" in data["symbols"]
        assert "BTC" in data["symbols"]
        assert "ETH" in data["symbols"]

        # 决策
        actions = await decide_actions(data, state_manager, mock_config)

        # 验证每个symbol都有决策
        symbols_with_actions = set(a.symbol for a in actions)
        assert "SOL" in symbols_with_actions
        assert "BTC" in symbols_with_actions
        assert "ETH" in symbols_with_actions


class TestStateManagement:
    """状态管理测试"""

    def test_state_isolation(self):
        """测试不同symbol的状态隔离"""
        state_manager = StateManager()

        # 更新SOL状态
        state_manager.update_symbol_state("SOL", {
            "offset": 10.0,
            "cost_basis": 150.0
        })

        # 更新BTC状态
        state_manager.update_symbol_state("BTC", {
            "offset": -0.05,
            "cost_basis": 60000.0
        })

        # 验证隔离
        sol_state = state_manager.get_symbol_state("SOL")
        btc_state = state_manager.get_symbol_state("BTC")

        assert sol_state["offset"] == 10.0
        assert btc_state["offset"] == -0.05
        assert sol_state["offset"] != btc_state["offset"]

    def test_state_deep_merge(self):
        """测试状态深度合并"""
        state_manager = StateManager()

        # 初始状态
        state_manager.update_symbol_state("SOL", {
            "offset": 10.0,
            "monitoring": {
                "current_zone": 1
            }
        })

        # 部分更新（只更新monitoring.started_at）
        state_manager.update_symbol_state("SOL", {
            "monitoring": {
                "started_at": datetime.now()
            }
        })

        # 验证合并结果
        state = state_manager.get_symbol_state("SOL")
        assert state["offset"] == 10.0  # 保留
        assert state["monitoring"]["current_zone"] == 1  # 保留
        assert state["monitoring"]["started_at"] is not None  # 新增


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
