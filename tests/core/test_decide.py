#!/usr/bin/env python3
"""
测试决策模块 (decide.py)

重点测试：
1. Zone计算逻辑
2. 超时检测
3. 冷却期逻辑
4. Zone变化时的行为
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))

import pytest
from datetime import datetime, timedelta
from core.decide import (
    _calculate_zone,
    _check_cooldown,
    _decide_symbol_actions,
    ActionType
)


class TestZoneCalculation:
    """测试Zone计算逻辑"""

    def test_below_min_threshold(self):
        """低于最小阈值 → None"""
        zone = _calculate_zone(
            offset_usd=3.0,
            min_threshold=5.0,
            max_threshold=20.0,
            step=2.5
        )
        assert zone is None

    def test_at_min_threshold(self):
        """刚好到最小阈值 → Zone 0"""
        zone = _calculate_zone(
            offset_usd=5.0,
            min_threshold=5.0,
            max_threshold=20.0,
            step=2.5
        )
        assert zone == 0

    def test_between_thresholds(self):
        """在阈值之间 → 计算zone编号"""
        # 5.0 - 7.5 → Zone 0
        assert _calculate_zone(7.0, 5.0, 20.0, 2.5) == 0

        # 7.5 - 10.0 → Zone 1
        assert _calculate_zone(8.0, 5.0, 20.0, 2.5) == 1

        # 10.0 - 12.5 → Zone 2
        assert _calculate_zone(11.0, 5.0, 20.0, 2.5) == 2

    def test_at_max_threshold(self):
        """刚好到最大阈值 → Zone 6"""
        zone = _calculate_zone(
            offset_usd=20.0,
            min_threshold=5.0,
            max_threshold=20.0,
            step=2.5
        )
        assert zone == 6

    def test_above_max_threshold(self):
        """超过最大阈值 → -1 (警报)"""
        zone = _calculate_zone(
            offset_usd=25.0,
            min_threshold=5.0,
            max_threshold=20.0,
            step=2.5
        )
        assert zone == -1

    def test_negative_offset(self):
        """负值偏移也应该正确计算（取绝对值）"""
        zone = _calculate_zone(
            offset_usd=-8.0,
            min_threshold=5.0,
            max_threshold=20.0,
            step=2.5
        )
        assert zone == 1  # abs(8.0) = 8.0 → Zone 1


class TestCooldownLogic:
    """测试冷却期逻辑"""

    def test_no_last_fill_time(self):
        """没有成交记录 → 不在冷却期"""
        state = {}
        in_cooldown, status = _check_cooldown(state, None, None, {})
        assert in_cooldown is False
        assert status == "normal"

    def test_cooldown_expired(self):
        """冷却期已过 → 不在冷却期"""
        state = {
            "last_fill_time": datetime.now() - timedelta(minutes=10)
        }
        config = {"cooldown_after_fill_minutes": 5}

        in_cooldown, status = _check_cooldown(state, None, None, config)
        assert in_cooldown is False
        assert status == "normal"

    def test_in_cooldown_back_to_threshold(self):
        """冷却期内，回到阈值内 → cancel_only"""
        state = {
            "last_fill_time": datetime.now() - timedelta(minutes=2)
        }
        config = {"cooldown_after_fill_minutes": 5}

        in_cooldown, status = _check_cooldown(
            state,
            current_zone=1,
            new_zone=None,  # 回到阈值内
            config=config
        )
        assert in_cooldown is True
        assert status == "cancel_only"

    def test_in_cooldown_zone_worsened(self):
        """冷却期内，zone恶化 → re_order"""
        state = {
            "last_fill_time": datetime.now() - timedelta(minutes=2)
        }
        config = {"cooldown_after_fill_minutes": 5}

        in_cooldown, status = _check_cooldown(
            state,
            current_zone=1,
            new_zone=2,  # 恶化
            config=config
        )
        assert in_cooldown is True
        assert status == "re_order"

    def test_in_cooldown_zone_improved(self):
        """冷却期内，zone改善 → skip"""
        state = {
            "last_fill_time": datetime.now() - timedelta(minutes=2)
        }
        config = {"cooldown_after_fill_minutes": 5}

        in_cooldown, status = _check_cooldown(
            state,
            current_zone=2,
            new_zone=1,  # 改善
            config=config
        )
        assert in_cooldown is True
        assert status == "skip"


class TestDecisionLogic:
    """测试核心决策逻辑"""

    def setup_method(self):
        """每个测试前的设置"""
        self.config = {
            "threshold_min_usd": 5.0,
            "threshold_max_usd": 20.0,
            "threshold_step_usd": 2.5,
            "timeout_minutes": 20,
            "order_price_offset": 0.2,
            "close_ratio": 40.0,
            "cooldown_after_fill_minutes": 5
        }

    def test_threshold_exceeded(self):
        """超过最大阈值 → ALERT + CANCEL_ORDER"""
        state = {
            "monitoring": {
                "started_at": datetime.now(),
                "current_zone": None
            }
        }

        actions = _decide_symbol_actions(
            symbol="SOL",
            offset=15.0,
            cost_basis=150.0,
            current_price=150.0,
            offset_usd=2250.0,  # 超过20.0
            zone=-1,
            state=state,
            config=self.config
        )

        assert len(actions) == 2
        assert actions[0].type == ActionType.CANCEL_ORDER
        assert actions[1].type == ActionType.ALERT

    def test_timeout_triggered(self):
        """订单超时 → CANCEL_ORDER + PLACE_MARKET_ORDER"""
        state = {
            "monitoring": {
                "started_at": datetime.now() - timedelta(minutes=25),  # 超时
                "current_zone": 1
            }
        }

        actions = _decide_symbol_actions(
            symbol="SOL",
            offset=1.0,
            cost_basis=150.0,
            current_price=150.0,
            offset_usd=150.0,
            zone=1,
            state=state,
            config=self.config
        )

        assert len(actions) == 2
        assert actions[0].type == ActionType.CANCEL_ORDER
        assert actions[1].type == ActionType.PLACE_MARKET_ORDER
        assert actions[1].metadata["force_close"] is True

    def test_enter_new_zone(self):
        """进入新zone → CANCEL_ORDER + PLACE_LIMIT_ORDER"""
        state = {
            "monitoring": {
                "started_at": None,
                "current_zone": None
            }
        }

        actions = _decide_symbol_actions(
            symbol="SOL",
            offset=1.0,
            cost_basis=150.0,
            current_price=150.0,
            offset_usd=8.0,  # Zone 1
            zone=1,
            state=state,
            config=self.config
        )

        # 应该有CANCEL_ORDER（清理旧订单）+ PLACE_LIMIT_ORDER
        assert len(actions) == 2
        assert actions[0].type == ActionType.CANCEL_ORDER
        assert actions[1].type == ActionType.PLACE_LIMIT_ORDER
        assert actions[1].metadata["zone"] == 1

    def test_back_within_threshold(self):
        """回到阈值内 → CANCEL_ORDER + NO_ACTION"""
        state = {
            "monitoring": {
                "started_at": datetime.now(),
                "current_zone": 1
            }
        }

        actions = _decide_symbol_actions(
            symbol="SOL",
            offset=0.02,
            cost_basis=150.0,
            current_price=150.0,
            offset_usd=3.0,  # 低于5.0
            zone=None,
            state=state,
            config=self.config
        )

        assert len(actions) == 2
        assert actions[0].type == ActionType.CANCEL_ORDER
        assert actions[1].type == ActionType.NO_ACTION

    def test_no_zone_change(self):
        """Zone没有变化 → NO_ACTION"""
        state = {
            "monitoring": {
                "started_at": datetime.now() - timedelta(minutes=5),
                "current_zone": 1
            }
        }

        actions = _decide_symbol_actions(
            symbol="SOL",
            offset=1.0,
            cost_basis=150.0,
            current_price=150.0,
            offset_usd=8.0,  # 仍然是Zone 1
            zone=1,
            state=state,
            config=self.config
        )

        assert len(actions) == 1
        assert actions[0].type == ActionType.NO_ACTION

    def test_cooldown_zone_worsened(self):
        """冷却期内zone恶化 → CANCEL_ORDER + PLACE_LIMIT_ORDER (in_cooldown=True)"""
        state = {
            "monitoring": {
                "started_at": datetime.now() - timedelta(minutes=3),
                "current_zone": 1
            },
            "last_fill_time": datetime.now() - timedelta(minutes=2)  # 冷却期内
        }

        actions = _decide_symbol_actions(
            symbol="SOL",
            offset=2.0,
            cost_basis=150.0,
            current_price=150.0,
            offset_usd=300.0,  # Zone 2（恶化）
            zone=2,
            state=state,
            config=self.config
        )

        assert len(actions) == 2
        assert actions[0].type == ActionType.CANCEL_ORDER
        assert actions[1].type == ActionType.PLACE_LIMIT_ORDER
        assert actions[1].metadata["in_cooldown"] is True


class TestLimitOrderCalculation:
    """测试限价单价格计算"""

    def test_long_offset_sell_order(self):
        """多头敞口 → 卖出订单，挂高价"""
        state = {
            "monitoring": {
                "started_at": None,
                "current_zone": None
            }
        }
        config = {
            "threshold_min_usd": 5.0,
            "threshold_max_usd": 20.0,
            "threshold_step_usd": 2.5,
            "timeout_minutes": 20,
            "order_price_offset": 0.2,
            "close_ratio": 40.0,
            "cooldown_after_fill_minutes": 5
        }

        actions = _decide_symbol_actions(
            symbol="SOL",
            offset=1.0,  # 多头
            cost_basis=100.0,
            current_price=105.0,
            offset_usd=105.0,
            zone=1,
            state=state,
            config=config
        )

        limit_order = next(a for a in actions if a.type == ActionType.PLACE_LIMIT_ORDER)
        assert limit_order.side == "sell"
        assert limit_order.price == 100.0 * 1.002  # cost_basis * (1 + 0.2%)
        assert limit_order.size == 1.0 * 0.4  # offset * 40%

    def test_short_offset_buy_order(self):
        """空头敞口 → 买入订单，挂低价"""
        state = {
            "monitoring": {
                "started_at": None,
                "current_zone": None
            }
        }
        config = {
            "threshold_min_usd": 5.0,
            "threshold_max_usd": 20.0,
            "threshold_step_usd": 2.5,
            "timeout_minutes": 20,
            "order_price_offset": 0.2,
            "close_ratio": 40.0,
            "cooldown_after_fill_minutes": 5
        }

        actions = _decide_symbol_actions(
            symbol="SOL",
            offset=-1.0,  # 空头
            cost_basis=100.0,
            current_price=95.0,
            offset_usd=95.0,
            zone=1,
            state=state,
            config=config
        )

        limit_order = next(a for a in actions if a.type == ActionType.PLACE_LIMIT_ORDER)
        assert limit_order.side == "buy"
        assert limit_order.price == 100.0 * 0.998  # cost_basis * (1 - 0.2%)
        assert limit_order.size == 1.0 * 0.4  # abs(offset) * 40%


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
