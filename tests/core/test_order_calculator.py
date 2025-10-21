#!/usr/bin/env python3
"""
测试 order_calculator.py

纯函数测试 - 零依赖，无需mock
"""

import pytest
from src.core.order_calculator import (
    calculate_order_price,
    calculate_order_size,
    calculate_order_side
)


class TestCalculateOrderPrice:
    """测试 calculate_order_price 函数"""

    def test_long_position_sell_higher(self):
        """测试：多头敞口，卖出时挂高价"""
        # offset > 0 表示多头敞口，需要卖出
        # 成本100，偏移0.2%，应该挂100.2
        price = calculate_order_price(100.0, 10.5, 0.2)
        assert price == pytest.approx(100.2, rel=1e-6)

    def test_short_position_buy_lower(self):
        """测试：空头敞口，买入时挂低价"""
        # offset < 0 表示空头敞口，需要买入
        # 成本100，偏移0.2%，应该挂99.8
        price = calculate_order_price(100.0, -10.5, 0.2)
        assert price == pytest.approx(99.8, rel=1e-6)

    def test_different_price_offsets(self):
        """测试：不同的价格偏移百分比"""
        # 0.5%
        assert calculate_order_price(100.0, 5.0, 0.5) == pytest.approx(100.5, rel=1e-6)
        assert calculate_order_price(100.0, -5.0, 0.5) == pytest.approx(99.5, rel=1e-6)

        # 1.0%
        assert calculate_order_price(100.0, 5.0, 1.0) == pytest.approx(101.0, rel=1e-6)
        assert calculate_order_price(100.0, -5.0, 1.0) == pytest.approx(99.0, rel=1e-6)

    def test_different_cost_basis(self):
        """测试：不同的成本基础"""
        # 成本50
        assert calculate_order_price(50.0, 10.0, 0.2) == pytest.approx(50.1, rel=1e-6)
        assert calculate_order_price(50.0, -10.0, 0.2) == pytest.approx(49.9, rel=1e-6)

        # 成本200
        assert calculate_order_price(200.0, 10.0, 0.2) == pytest.approx(200.4, rel=1e-6)
        assert calculate_order_price(200.0, -10.0, 0.2) == pytest.approx(199.6, rel=1e-6)

    def test_high_price_crypto(self):
        """测试：高价加密货币（如BTC）"""
        # BTC价格 $50,000
        btc_price = 50000.0
        price_offset = 0.2

        # 多头
        sell_price = calculate_order_price(btc_price, 0.1, price_offset)
        assert sell_price == pytest.approx(50100.0, rel=1e-6)

        # 空头
        buy_price = calculate_order_price(btc_price, -0.1, price_offset)
        assert buy_price == pytest.approx(49900.0, rel=1e-6)

    def test_low_price_crypto(self):
        """测试：低价加密货币（如BONK）"""
        # BONK价格 $0.00001
        bonk_price = 0.00001
        price_offset = 0.2

        # 多头
        sell_price = calculate_order_price(bonk_price, 1000.0, price_offset)
        assert sell_price == pytest.approx(0.00001002, rel=1e-6)

        # 空头
        buy_price = calculate_order_price(bonk_price, -1000.0, price_offset)
        assert buy_price == pytest.approx(0.00000998, rel=1e-6)


class TestCalculateOrderSize:
    """测试 calculate_order_size 函数"""

    def test_positive_offset(self):
        """测试：正数偏移"""
        # offset=10, ratio=40% -> size=4
        size = calculate_order_size(10.0, 40.0)
        assert size == pytest.approx(4.0, rel=1e-6)

    def test_negative_offset(self):
        """测试：负数偏移（取绝对值）"""
        # offset=-10, ratio=40% -> size=4
        size = calculate_order_size(-10.0, 40.0)
        assert size == pytest.approx(4.0, rel=1e-6)

    def test_different_close_ratios(self):
        """测试：不同的平仓比例"""
        offset = 10.0

        # 20%
        assert calculate_order_size(offset, 20.0) == pytest.approx(2.0, rel=1e-6)

        # 50%
        assert calculate_order_size(offset, 50.0) == pytest.approx(5.0, rel=1e-6)

        # 100%
        assert calculate_order_size(offset, 100.0) == pytest.approx(10.0, rel=1e-6)

    def test_fractional_offset(self):
        """测试：小数偏移"""
        # offset=0.5, ratio=40% -> size=0.2
        size = calculate_order_size(0.5, 40.0)
        assert size == pytest.approx(0.2, rel=1e-6)

        # offset=123.456, ratio=40% -> size=49.3824
        size = calculate_order_size(123.456, 40.0)
        assert size == pytest.approx(49.3824, rel=1e-6)

    def test_zero_offset(self):
        """测试：零偏移"""
        size = calculate_order_size(0.0, 40.0)
        assert size == 0.0

    def test_large_offset(self):
        """测试：大偏移量"""
        # offset=1000, ratio=40% -> size=400
        size = calculate_order_size(1000.0, 40.0)
        assert size == pytest.approx(400.0, rel=1e-6)


class TestCalculateOrderSide:
    """测试 calculate_order_side 函数"""

    def test_positive_offset_is_sell(self):
        """测试：多头敞口 -> 卖出"""
        assert calculate_order_side(10.5) == "sell"
        assert calculate_order_side(0.1) == "sell"
        assert calculate_order_side(1000.0) == "sell"

    def test_negative_offset_is_buy(self):
        """测试：空头敞口 -> 买入"""
        assert calculate_order_side(-10.5) == "buy"
        assert calculate_order_side(-0.1) == "buy"
        assert calculate_order_side(-1000.0) == "buy"

    def test_zero_offset_is_buy(self):
        """测试：零偏移默认为买入"""
        # 注意：zero offset通常不会触发订单，但如果触发，默认为buy
        assert calculate_order_side(0.0) == "buy"


class TestOrderCalculatorIntegration:
    """集成测试：验证订单参数计算的一致性"""

    def test_complete_order_calculation_long(self):
        """测试：完整的订单计算 - 多头敞口"""
        offset = 10.5
        cost_basis = 100.0
        close_ratio = 40.0
        price_offset_pct = 0.2

        # 计算所有参数
        side = calculate_order_side(offset)
        size = calculate_order_size(offset, close_ratio)
        price = calculate_order_price(cost_basis, offset, price_offset_pct)

        # 验证
        assert side == "sell"
        assert size == pytest.approx(4.2, rel=1e-6)
        assert price == pytest.approx(100.2, rel=1e-6)

    def test_complete_order_calculation_short(self):
        """测试：完整的订单计算 - 空头敞口"""
        offset = -8.0
        cost_basis = 50.0
        close_ratio = 50.0
        price_offset_pct = 0.5

        # 计算所有参数
        side = calculate_order_side(offset)
        size = calculate_order_size(offset, close_ratio)
        price = calculate_order_price(cost_basis, offset, price_offset_pct)

        # 验证
        assert side == "buy"
        assert size == pytest.approx(4.0, rel=1e-6)
        assert price == pytest.approx(49.75, rel=1e-6)

    def test_realistic_btc_scenario(self):
        """测试：真实的BTC场景"""
        # BTC: 成本$50,000, 多头敞口0.15 BTC
        offset = 0.15
        cost_basis = 50000.0
        close_ratio = 40.0
        price_offset_pct = 0.2

        side = calculate_order_side(offset)
        size = calculate_order_size(offset, close_ratio)
        price = calculate_order_price(cost_basis, offset, price_offset_pct)

        assert side == "sell"
        assert size == pytest.approx(0.06, rel=1e-6)  # 40% of 0.15
        assert price == pytest.approx(50100.0, rel=1e-6)  # +0.2%

    def test_realistic_sol_scenario(self):
        """测试：真实的SOL场景"""
        # SOL: 成本$100, 空头敞口-50 SOL
        offset = -50.0
        cost_basis = 100.0
        close_ratio = 40.0
        price_offset_pct = 0.2

        side = calculate_order_side(offset)
        size = calculate_order_size(offset, close_ratio)
        price = calculate_order_price(cost_basis, offset, price_offset_pct)

        assert side == "buy"
        assert size == pytest.approx(20.0, rel=1e-6)  # 40% of 50
        assert price == pytest.approx(99.8, rel=1e-6)  # -0.2%


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
