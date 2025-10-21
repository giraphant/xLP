#!/usr/bin/env python3
"""
测试 decision_logic.py

纯函数测试 - 零依赖，无需mock
替代原来230行的DecisionEngine.decide()方法的测试
"""

import pytest
from datetime import datetime, timedelta
from src.core.decision_logic import (
    Decision,
    decide_on_threshold_breach,
    decide_on_timeout,
    decide_on_zone_change,
    check_cooldown,
    _decide_in_cooldown,
    _create_limit_order_decision
)


class TestDecision:
    """测试 Decision 数据类"""

    def test_decision_creation(self):
        """测试：创建Decision对象"""
        decision = Decision(
            action="place_order",
            side="buy",
            size=10.5,
            price=100.2,
            reason="Test"
        )

        assert decision.action == "place_order"
        assert decision.side == "buy"
        assert decision.size == 10.5
        assert decision.price == 100.2
        assert decision.reason == "Test"
        assert decision.metadata == {}

    def test_decision_with_metadata(self):
        """测试：带metadata的Decision"""
        metadata = {"zone": 2, "offset": 10.5}
        decision = Decision(
            action="wait",
            reason="Testing",
            metadata=metadata
        )

        assert decision.metadata == metadata


class TestDecideOnThresholdBreach:
    """测试 decide_on_threshold_breach 函数"""

    def test_within_threshold(self):
        """测试：在阈值内 -> wait"""
        decision = decide_on_threshold_breach(15.0, 20.0)
        assert decision.action == "wait"
        assert "Within max threshold" in decision.reason

    def test_exceeded_threshold(self):
        """测试：超过阈值 -> alert"""
        decision = decide_on_threshold_breach(25.0, 20.0)
        assert decision.action == "alert"
        assert "Threshold exceeded" in decision.reason
        assert decision.metadata["offset_usd"] == 25.0
        assert decision.metadata["max_threshold"] == 20.0

    def test_exactly_at_threshold(self):
        """测试：刚好在阈值边界"""
        decision = decide_on_threshold_breach(20.0, 20.0)
        assert decision.action == "wait"

    def test_just_over_threshold(self):
        """测试：刚好超过阈值"""
        decision = decide_on_threshold_breach(20.01, 20.0)
        assert decision.action == "alert"

    def test_negative_offset(self):
        """测试：负数偏移（使用绝对值）"""
        decision = decide_on_threshold_breach(-25.0, 20.0)
        assert decision.action == "alert"
        assert decision.metadata["offset_usd"] == 25.0  # 绝对值


class TestDecideOnTimeout:
    """测试 decide_on_timeout 函数"""

    def test_no_order_no_timeout(self):
        """测试：无订单 -> None"""
        decision = decide_on_timeout(None, 20, 10.5, 40.0)
        assert decision is None

    def test_not_timeout_yet(self):
        """测试：未超时 -> None"""
        started_at = datetime.now() - timedelta(minutes=10)
        decision = decide_on_timeout(started_at, 20, 10.5, 40.0)
        assert decision is None

    def test_timeout_long_position(self):
        """测试：超时 - 多头敞口 -> 市价卖出"""
        started_at = datetime.now() - timedelta(minutes=25)
        decision = decide_on_timeout(started_at, 20, 10.5, 40.0)

        assert decision is not None
        assert decision.action == "market_order"
        assert decision.side == "sell"
        assert decision.size == pytest.approx(4.2, rel=1e-6)  # 10.5 * 0.4
        assert "Timeout" in decision.reason
        assert decision.metadata["force_close"] is True

    def test_timeout_short_position(self):
        """测试：超时 - 空头敞口 -> 市价买入"""
        started_at = datetime.now() - timedelta(minutes=25)
        decision = decide_on_timeout(started_at, 20, -8.0, 50.0)

        assert decision is not None
        assert decision.action == "market_order"
        assert decision.side == "buy"
        assert decision.size == pytest.approx(4.0, rel=1e-6)  # 8.0 * 0.5

    def test_exactly_timeout(self):
        """测试：刚好超时"""
        started_at = datetime.now() - timedelta(minutes=20, seconds=1)
        decision = decide_on_timeout(started_at, 20, 10.0, 40.0)

        assert decision is not None
        assert decision.action == "market_order"


class TestCheckCooldown:
    """测试 check_cooldown 函数"""

    def test_no_fill_no_cooldown(self):
        """测试：从未成交 -> False"""
        assert check_cooldown(None, 5) is False

    def test_in_cooldown(self):
        """测试：在cooldown期间 -> True"""
        last_fill = datetime.now() - timedelta(minutes=3)
        assert check_cooldown(last_fill, 5) is True

    def test_cooldown_expired(self):
        """测试：cooldown已过期 -> False"""
        last_fill = datetime.now() - timedelta(minutes=6)
        assert check_cooldown(last_fill, 5) is False

    def test_exactly_cooldown_boundary(self):
        """测试：刚好在cooldown边界"""
        # 刚好5分钟
        last_fill = datetime.now() - timedelta(minutes=5, seconds=1)
        assert check_cooldown(last_fill, 5) is False

        # 差一秒
        last_fill = datetime.now() - timedelta(minutes=4, seconds=59)
        assert check_cooldown(last_fill, 5) is True


class TestCreateLimitOrderDecision:
    """测试 _create_limit_order_decision 辅助函数"""

    def test_create_order_long_position(self):
        """测试：创建限价单 - 多头敞口"""
        decision = _create_limit_order_decision(10.5, 100.0, 40.0, 0.2, 2)

        assert decision.action == "place_order"
        assert decision.side == "sell"
        assert decision.size == pytest.approx(4.2, rel=1e-6)
        assert decision.price == pytest.approx(100.2, rel=1e-6)
        assert "Zone 2" in decision.reason
        assert decision.metadata["zone"] == 2
        assert decision.metadata["offset"] == 10.5

    def test_create_order_short_position(self):
        """测试：创建限价单 - 空头敞口"""
        decision = _create_limit_order_decision(-8.0, 50.0, 50.0, 0.5, 1)

        assert decision.action == "place_order"
        assert decision.side == "buy"
        assert decision.size == pytest.approx(4.0, rel=1e-6)
        assert decision.price == pytest.approx(49.75, rel=1e-6)
        assert "Zone 1" in decision.reason


class TestDecideInCooldown:
    """测试 _decide_in_cooldown 函数"""

    def test_zone_to_none_cancel(self):
        """测试：Zone → None -> 撤单"""
        decision = _decide_in_cooldown(2, None, 10.0, 100.0, 40.0, 0.2)

        assert decision.action == "cancel"
        assert "back within threshold" in decision.reason.lower()

    def test_old_zone_none_new_zone_place_order(self):
        """测试：上次在阈值内，现在进入zone -> 挂单"""
        decision = _decide_in_cooldown(None, 2, 10.0, 100.0, 40.0, 0.2)

        assert decision.action == "place_order"
        assert decision.side == "sell"

    def test_zone_worsened_reorder(self):
        """测试：Zone恶化 -> 重新挂单"""
        decision = _decide_in_cooldown(1, 3, 12.0, 100.0, 40.0, 0.2)

        assert decision.action == "place_order"
        assert decision.side == "sell"
        assert decision.metadata["zone"] == 3

    def test_zone_improved_wait(self):
        """测试：Zone改善 -> 等待"""
        decision = _decide_in_cooldown(3, 1, 8.0, 100.0, 40.0, 0.2)

        assert decision.action == "wait"
        assert "improved" in decision.reason.lower()

    def test_zone_unchanged_wait(self):
        """测试：Zone不变 -> 等待"""
        decision = _decide_in_cooldown(2, 2, 10.0, 100.0, 40.0, 0.2)

        assert decision.action == "wait"


class TestDecideOnZoneChange:
    """测试 decide_on_zone_change 主函数"""

    def test_no_zone_change_wait(self):
        """测试：Zone无变化 -> 等待"""
        decision = decide_on_zone_change(2, 2, False, 10.0, 100.0, 40.0, 0.2)

        assert decision.action == "wait"
        assert "No zone change" in decision.reason

    def test_zone_to_none_cancel(self):
        """测试：回到阈值内 -> 撤单"""
        decision = decide_on_zone_change(2, None, False, 5.0, 100.0, 40.0, 0.2)

        assert decision.action == "cancel"
        assert "within threshold" in decision.reason.lower()

    def test_enter_new_zone_place_order(self):
        """测试：进入新zone -> 挂单"""
        decision = decide_on_zone_change(None, 2, False, 10.0, 100.0, 40.0, 0.2)

        assert decision.action == "place_order"
        assert decision.metadata["zone"] == 2

    def test_in_cooldown_delegates_to_cooldown_logic(self):
        """测试：在cooldown期间 -> 使用cooldown逻辑"""
        # Zone改善，cooldown期间应该wait
        decision = decide_on_zone_change(3, 1, True, 8.0, 100.0, 40.0, 0.2)

        assert decision.action == "wait"
        assert "improved" in decision.reason.lower()

        # Zone恶化，cooldown期间应该re-order
        decision = decide_on_zone_change(1, 3, True, 12.0, 100.0, 40.0, 0.2)

        assert decision.action == "place_order"
        assert decision.metadata["zone"] == 3


class TestDecisionLogicIntegration:
    """集成测试：验证决策逻辑的完整流程"""

    def test_complete_decision_flow_normal(self):
        """测试：完整决策流程 - 正常情况"""
        offset_usd = 10.0
        max_threshold = 20.0
        old_zone = 1
        new_zone = 2

        # 步骤1: 检查阈值
        d1 = decide_on_threshold_breach(offset_usd, max_threshold)
        assert d1.action == "wait"  # 未超过

        # 步骤2: 检查超时（假设无订单）
        d2 = decide_on_timeout(None, 20, 10.0, 40.0)
        assert d2 is None  # 无订单

        # 步骤3: 检查zone变化
        d3 = decide_on_zone_change(old_zone, new_zone, False, 10.0, 100.0, 40.0, 0.2)
        assert d3.action == "place_order"  # 进入新zone

    def test_complete_decision_flow_threshold_exceeded(self):
        """测试：完整决策流程 - 超过阈值"""
        offset_usd = 25.0
        max_threshold = 20.0

        # 步骤1: 检查阈值
        d1 = decide_on_threshold_breach(offset_usd, max_threshold)
        assert d1.action == "alert"  # 超过阈值，直接返回

    def test_complete_decision_flow_timeout(self):
        """测试：完整决策流程 - 订单超时"""
        started_at = datetime.now() - timedelta(minutes=25)

        # 步骤1: 阈值检查通过
        d1 = decide_on_threshold_breach(15.0, 20.0)
        assert d1.action == "wait"

        # 步骤2: 超时检查
        d2 = decide_on_timeout(started_at, 20, 10.0, 40.0)
        assert d2.action == "market_order"  # 超时，市价平仓

    def test_complete_decision_flow_cooldown(self):
        """测试：完整决策流程 - Cooldown期间"""
        old_zone = 3
        new_zone = 1
        last_fill = datetime.now() - timedelta(minutes=2)
        in_cooldown = check_cooldown(last_fill, 5)

        assert in_cooldown is True

        # Zone改善，cooldown期间
        d = decide_on_zone_change(old_zone, new_zone, in_cooldown, 8.0, 100.0, 40.0, 0.2)
        assert d.action == "wait"  # Cooldown期间zone改善，等待

    def test_realistic_scenario_btc(self):
        """测试：真实场景 - BTC"""
        # BTC: offset=0.15, cost=$50000, 进入zone 2
        offset = 0.15
        cost_basis = 50000.0
        close_ratio = 40.0
        price_offset_pct = 0.2

        decision = _create_limit_order_decision(offset, cost_basis, close_ratio, price_offset_pct, 2)

        assert decision.action == "place_order"
        assert decision.side == "sell"
        assert decision.size == pytest.approx(0.06, rel=1e-6)
        assert decision.price == pytest.approx(50100.0, rel=1e-6)

    def test_realistic_scenario_sol(self):
        """测试：真实场景 - SOL空头"""
        # SOL: offset=-50, cost=$100, 进入zone 1
        offset = -50.0
        cost_basis = 100.0
        close_ratio = 40.0
        price_offset_pct = 0.2

        decision = _create_limit_order_decision(offset, cost_basis, close_ratio, price_offset_pct, 1)

        assert decision.action == "place_order"
        assert decision.side == "buy"
        assert decision.size == pytest.approx(20.0, rel=1e-6)
        assert decision.price == pytest.approx(99.8, rel=1e-6)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
