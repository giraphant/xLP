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
    _decide_symbol_actions,
    ActionType
)
from utils.config import HedgeConfig


@pytest.fixture
def mock_config():
    """标准测试配置"""
    return HedgeConfig(
        threshold_min_usd=5.0,
        threshold_max_usd=20.0,
        threshold_step_usd=2.5,
        timeout_minutes=20,
        order_price_offset=0.2,
        close_ratio=40.0,
        cooldown_after_fill_minutes=5
    )


class TestZoneCalculation:
    """测试Zone计算逻辑"""

    def test_below_min_threshold(self, mock_config):
        """低于最小阈值 → None"""
        zone = _calculate_zone(
            offset_usd=3.0,
            min_threshold=5.0,
            max_threshold=20.0,
            step=2.5
        )
        assert zone is None

    def test_at_min_threshold(self, mock_config):
        """刚好到最小阈值 → Zone 0"""
        zone = _calculate_zone(
            offset_usd=5.0,
            min_threshold=5.0,
            max_threshold=20.0,
            step=2.5
        )
        assert zone == 0

    def test_between_thresholds(self, mock_config):
        """在阈值之间 → 计算zone编号"""
        # 5.0 - 7.5 → Zone 0
        assert _calculate_zone(7.0, 5.0, 20.0, 2.5) == 0

        # 7.5 - 10.0 → Zone 1
        assert _calculate_zone(8.0, 5.0, 20.0, 2.5) == 1

        # 10.0 - 12.5 → Zone 2
        assert _calculate_zone(11.0, 5.0, 20.0, 2.5) == 2

    def test_at_max_threshold(self, mock_config):
        """刚好到最大阈值 → Zone 6"""
        zone = _calculate_zone(
            offset_usd=20.0,
            min_threshold=5.0,
            max_threshold=20.0,
            step=2.5
        )
        assert zone == 6

    def test_above_max_threshold(self, mock_config):
        """超过最大阈值 → -1 (警报)"""
        zone = _calculate_zone(
            offset_usd=25.0,
            min_threshold=5.0,
            max_threshold=20.0,
            step=2.5
        )
        assert zone == -1

    def test_negative_offset(self, mock_config):
        """负值偏移也应该正确计算（取绝对值）"""
        zone = _calculate_zone(
            offset_usd=-8.0,
            min_threshold=5.0,
            max_threshold=20.0,
            step=2.5
        )
        assert zone == 1  # abs(8.0) = 8.0 → Zone 1


class TestCooldownLogic:
    """测试冷却期逻辑（通过决策函数测试）"""

    def test_cooldown_no_order(self, mock_config):
        """冷却期内，无订单 → NO_ACTION（等待冷却）"""
        state = {
            "monitoring": {
                "started_at": None,  # 无订单
                "current_zone": 1
            },
            "last_fill_time": datetime.now() - timedelta(minutes=2)  # 冷却期内
        }

        actions = _decide_symbol_actions(
            symbol="SOL",
            offset=1.0,
            cost_basis=150.0,
            current_price=150.0,
            offset_usd=150.0,
            zone=1,  # 有敞口
            state=state,
            config=mock_config
        )

        assert len(actions) == 1
        assert actions[0].type == ActionType.NO_ACTION
        assert "cooldown" in actions[0].reason.lower()

    def test_cooldown_zone_worsened_with_order(self, mock_config):
        """冷却期内，有订单，zone恶化 → CANCEL_ORDER + PLACE_LIMIT_ORDER"""
        state = {
            "monitoring": {
                "started_at": datetime.now() - timedelta(minutes=3),  # 有订单
                "current_zone": 1
            },
            "last_fill_time": datetime.now() - timedelta(minutes=2)  # 冷却期内
        }

        actions = _decide_symbol_actions(
            symbol="SOL",
            offset=2.0,
            cost_basis=150.0,
            current_price=150.0,
            offset_usd=300.0,
            zone=2,  # Zone恶化（1→2）
            state=state,
            config=mock_config
        )

        assert len(actions) == 2
        assert actions[0].type == ActionType.CANCEL_ORDER
        assert actions[1].type == ActionType.PLACE_LIMIT_ORDER
        assert actions[1].metadata.get("in_cooldown") is True

    def test_cooldown_zone_improved_with_order(self, mock_config):
        """冷却期内，有订单，zone改善 → NO_ACTION（保持订单）"""
        state = {
            "monitoring": {
                "started_at": datetime.now() - timedelta(minutes=3),  # 有订单
                "current_zone": 2
            },
            "last_fill_time": datetime.now() - timedelta(minutes=2)  # 冷却期内
        }

        actions = _decide_symbol_actions(
            symbol="SOL",
            offset=1.0,
            cost_basis=150.0,
            current_price=150.0,
            offset_usd=150.0,
            zone=1,  # Zone改善（2→1）
            state=state,
            config=mock_config
        )

        assert len(actions) == 1
        assert actions[0].type == ActionType.NO_ACTION
        assert "cooldown" in actions[0].reason.lower()

    def test_non_cooldown_no_order(self, mock_config):
        """非冷却期，无订单 → PLACE_LIMIT_ORDER"""
        state = {
            "monitoring": {
                "started_at": None,  # 无订单
                "current_zone": None
            },
            "last_fill_time": datetime.now() - timedelta(minutes=10)  # 冷却期已过
        }

        actions = _decide_symbol_actions(
            symbol="SOL",
            offset=1.0,
            cost_basis=150.0,
            current_price=150.0,
            offset_usd=150.0,
            zone=1,  # 有敞口
            state=state,
            config=mock_config
        )

        assert len(actions) == 1
        assert actions[0].type == ActionType.PLACE_LIMIT_ORDER


class TestDecisionLogic:
    """测试核心决策逻辑"""

    def setup_method(self):
        """每个测试前的设置"""

    def test_zone_unchanged_but_has_exposure(self, mock_config):
        """关键测试：zone不变但有敞口，仍会评估和管理订单"""
        # 场景1：冷却期内，zone不变，有订单 → 保持订单
        state = {
            "monitoring": {
                "started_at": datetime.now() - timedelta(minutes=3),  # 有订单
                "current_zone": 1
            },
            "last_fill_time": datetime.now() - timedelta(minutes=2)  # 冷却期内
        }

        actions = _decide_symbol_actions(
            symbol="SOL",
            offset=1.0,
            cost_basis=150.0,
            current_price=150.0,
            offset_usd=150.0,
            zone=1,  # Zone 不变，但有敞口
            state=state,
            config=mock_config
        )

        # 冷却期内保持订单
        assert len(actions) == 1
        assert actions[0].type == ActionType.NO_ACTION
        assert "cooldown" in actions[0].reason.lower()

        # 场景2：非冷却期，zone不变，无订单 → 挂新单
        state = {
            "monitoring": {
                "started_at": None,  # 无订单
                "current_zone": 1
            },
            "last_fill_time": datetime.now() - timedelta(minutes=10)  # 已过冷却期
        }

        actions = _decide_symbol_actions(
            symbol="SOL",
            offset=1.0,
            cost_basis=150.0,
            current_price=150.0,
            offset_usd=150.0,
            zone=1,  # Zone 不变，但有敞口
            state=state,
            config=mock_config
        )

        # 应该挂新单
        assert len(actions) == 1
        assert actions[0].type == ActionType.PLACE_LIMIT_ORDER

    def test_threshold_exceeded(self, mock_config):
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
            config=mock_config
        )

        assert len(actions) == 2
        assert actions[0].type == ActionType.CANCEL_ORDER
        assert actions[1].type == ActionType.ALERT

    def test_timeout_triggered(self, mock_config):
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
            config=mock_config
        )

        assert len(actions) == 2
        assert actions[0].type == ActionType.CANCEL_ORDER
        assert actions[1].type == ActionType.PLACE_MARKET_ORDER
        assert actions[1].metadata["force_close"] is True

    def test_enter_new_zone(self, mock_config):
        """进入新zone（无活跃订单） → PLACE_LIMIT_ORDER"""
        state = {
            "monitoring": {
                "started_at": None,  # 无活跃订单
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
            config=mock_config
        )

        # 无活跃订单，只需要 PLACE_LIMIT_ORDER
        assert len(actions) == 1
        assert actions[0].type == ActionType.PLACE_LIMIT_ORDER
        assert actions[0].metadata["zone"] == 1

    def test_back_within_threshold(self, mock_config):
        """回到阈值内（有活跃订单） → CANCEL_ORDER"""
        state = {
            "monitoring": {
                "started_at": datetime.now(),  # 有活跃订单
                "current_zone": 1
            }
        }

        actions = _decide_symbol_actions(
            symbol="SOL",
            offset=0.02,
            cost_basis=150.0,
            current_price=150.0,
            offset_usd=3.0,  # 低于5.0
            zone=None,  # 回到安全区
            state=state,
            config=mock_config
        )

        # 决策4：有订单，回到安全区，只需取消订单
        assert len(actions) == 1
        assert actions[0].type == ActionType.CANCEL_ORDER
        assert "threshold" in actions[0].reason.lower()

    def test_non_cooldown_with_order(self, mock_config):
        """非冷却期但有订单（正常状态） → NO_ACTION (保持订单)"""
        state = {
            "monitoring": {
                "started_at": datetime.now() - timedelta(minutes=5),  # 有活跃订单
                "current_zone": 1
            }
            # 无 last_fill_time 或已过冷却期
        }

        actions = _decide_symbol_actions(
            symbol="SOL",
            offset=1.0,
            cost_basis=150.0,
            current_price=150.0,
            offset_usd=8.0,  # Zone 1
            zone=1,
            state=state,
            config=mock_config
        )

        # 正常状态：保持订单
        assert len(actions) == 1
        assert actions[0].type == ActionType.NO_ACTION
        assert "maintaining" in actions[0].reason.lower()

    def test_cooldown_zone_worsened(self, mock_config):
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
            config=mock_config
        )

        assert len(actions) == 2
        assert actions[0].type == ActionType.CANCEL_ORDER
        assert actions[1].type == ActionType.PLACE_LIMIT_ORDER
        assert actions[1].metadata["in_cooldown"] is True


class TestLimitOrderCalculation:
    """测试限价单价格计算"""

    def test_long_offset_sell_order(self, mock_config):
        """多头敞口 → 卖出订单，挂高价"""
        state = {
            "monitoring": {
                "started_at": None,  # 无活跃订单
                "current_zone": None
            }
        }

        actions = _decide_symbol_actions(
            symbol="SOL",
            offset=1.0,  # 多头
            cost_basis=100.0,
            current_price=105.0,
            offset_usd=105.0,
            zone=1,
            state=state,
            config=mock_config
        )

        # 只有一个 PLACE_LIMIT_ORDER
        assert len(actions) == 1
        limit_order = actions[0]
        assert limit_order.type == ActionType.PLACE_LIMIT_ORDER
        assert limit_order.side == "sell"
        assert limit_order.price == 100.0 * 1.002  # cost_basis * (1 + 0.2%)
        assert limit_order.size == 1.0 * 0.4  # offset * 40%

    def test_short_offset_buy_order(self, mock_config):
        """空头敞口 → 买入订单，挂低价"""
        state = {
            "monitoring": {
                "started_at": None,  # 无活跃订单
                "current_zone": None
            }
        }

        actions = _decide_symbol_actions(
            symbol="SOL",
            offset=-1.0,  # 空头
            cost_basis=100.0,
            current_price=95.0,
            offset_usd=95.0,
            zone=1,
            state=state,
            config=mock_config
        )

        # 只有一个 PLACE_LIMIT_ORDER
        assert len(actions) == 1
        limit_order = actions[0]
        assert limit_order.type == ActionType.PLACE_LIMIT_ORDER
        assert limit_order.side == "buy"
        assert limit_order.price == 100.0 * 0.998  # cost_basis * (1 - 0.2%)
        assert limit_order.size == 1.0 * 0.4  # abs(offset) * 40%


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
