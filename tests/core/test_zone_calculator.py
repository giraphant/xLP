#!/usr/bin/env python3
"""
测试 zone_calculator.py

纯函数测试 - 零依赖，无需mock
"""

import pytest
from src.core.zone_calculator import calculate_zone, get_zone_range


class TestCalculateZone:
    """测试 calculate_zone 函数"""

    def test_within_threshold(self):
        """测试：在最小阈值内 -> None"""
        assert calculate_zone(3.0, 5.0, 20.0, 2.5) is None
        assert calculate_zone(4.99, 5.0, 20.0, 2.5) is None
        assert calculate_zone(0.0, 5.0, 20.0, 2.5) is None

    def test_negative_offset_within_threshold(self):
        """测试：负数偏移在阈值内 -> None"""
        assert calculate_zone(-3.0, 5.0, 20.0, 2.5) is None
        assert calculate_zone(-4.99, 5.0, 20.0, 2.5) is None

    def test_zone_0(self):
        """测试：刚超过最小阈值 -> zone 0"""
        assert calculate_zone(5.0, 5.0, 20.0, 2.5) == 0
        assert calculate_zone(6.5, 5.0, 20.0, 2.5) == 0
        assert calculate_zone(7.49, 5.0, 20.0, 2.5) == 0

    def test_zone_1(self):
        """测试：zone 1"""
        assert calculate_zone(7.5, 5.0, 20.0, 2.5) == 1
        assert calculate_zone(9.99, 5.0, 20.0, 2.5) == 1

    def test_zone_2(self):
        """测试：zone 2"""
        assert calculate_zone(10.0, 5.0, 20.0, 2.5) == 2
        assert calculate_zone(12.49, 5.0, 20.0, 2.5) == 2

    def test_zone_max(self):
        """测试：接近最大阈值"""
        assert calculate_zone(19.99, 5.0, 20.0, 2.5) == 5

    def test_exceeded_max_threshold(self):
        """测试：超过最大阈值 -> -1"""
        assert calculate_zone(20.01, 5.0, 20.0, 2.5) == -1
        assert calculate_zone(25.0, 5.0, 20.0, 2.5) == -1
        assert calculate_zone(100.0, 5.0, 20.0, 2.5) == -1

    def test_negative_offset_zones(self):
        """测试：负数偏移计算zone（使用绝对值）"""
        assert calculate_zone(-6.5, 5.0, 20.0, 2.5) == 0
        assert calculate_zone(-10.0, 5.0, 20.0, 2.5) == 2
        assert calculate_zone(-25.0, 5.0, 20.0, 2.5) == -1

    def test_different_step_sizes(self):
        """测试：不同的步长"""
        # 步长 1.0
        assert calculate_zone(5.5, 5.0, 20.0, 1.0) == 0
        assert calculate_zone(6.5, 5.0, 20.0, 1.0) == 1
        assert calculate_zone(10.0, 5.0, 20.0, 1.0) == 5

        # 步长 5.0
        assert calculate_zone(8.0, 5.0, 20.0, 5.0) == 0
        assert calculate_zone(12.0, 5.0, 20.0, 5.0) == 1

    def test_edge_cases(self):
        """测试：边界情况"""
        # 刚好等于最小阈值
        assert calculate_zone(5.0, 5.0, 20.0, 2.5) == 0

        # 刚好等于最大阈值
        assert calculate_zone(20.0, 5.0, 20.0, 2.5) == 6

        # 刚好超过最大阈值
        assert calculate_zone(20.001, 5.0, 20.0, 2.5) == -1


class TestGetZoneRange:
    """测试 get_zone_range 函数"""

    def test_zone_0_range(self):
        """测试：zone 0的范围"""
        assert get_zone_range(0, 5.0, 2.5) == (5.0, 7.5)

    def test_zone_1_range(self):
        """测试：zone 1的范围"""
        assert get_zone_range(1, 5.0, 2.5) == (7.5, 10.0)

    def test_zone_2_range(self):
        """测试：zone 2的范围"""
        assert get_zone_range(2, 5.0, 2.5) == (10.0, 12.5)

    def test_different_parameters(self):
        """测试：不同参数的范围"""
        assert get_zone_range(0, 10.0, 5.0) == (10.0, 15.0)
        assert get_zone_range(3, 10.0, 5.0) == (25.0, 30.0)

    def test_invalid_zone(self):
        """测试：无效的zone"""
        with pytest.raises(ValueError):
            get_zone_range(-1, 5.0, 2.5)

        with pytest.raises(ValueError):
            get_zone_range(-10, 5.0, 2.5)


class TestZoneCalculatorIntegration:
    """集成测试：验证zone计算和范围获取的一致性"""

    def test_zone_boundaries(self):
        """测试：zone边界的一致性"""
        # Zone 0: [5.0, 7.5)
        assert calculate_zone(5.0, 5.0, 20.0, 2.5) == 0
        assert calculate_zone(7.49, 5.0, 20.0, 2.5) == 0

        range_start, range_end = get_zone_range(0, 5.0, 2.5)
        assert range_start == 5.0
        assert range_end == 7.5

        # Zone 1: [7.5, 10.0)
        assert calculate_zone(7.5, 5.0, 20.0, 2.5) == 1
        assert calculate_zone(9.99, 5.0, 20.0, 2.5) == 1

        range_start, range_end = get_zone_range(1, 5.0, 2.5)
        assert range_start == 7.5
        assert range_end == 10.0

    def test_all_zones_coverage(self):
        """测试：所有zone的完整覆盖"""
        threshold_min = 5.0
        threshold_max = 20.0
        threshold_step = 2.5

        # 计算应该有多少个zone
        expected_zones = int((threshold_max - threshold_min) / threshold_step)

        # 验证每个zone
        for zone_num in range(expected_zones):
            range_start, range_end = get_zone_range(zone_num, threshold_min, threshold_step)

            # 范围起点应该在该zone
            assert calculate_zone(range_start, threshold_min, threshold_max, threshold_step) == zone_num

            # 范围终点前应该在该zone
            assert calculate_zone(range_end - 0.01, threshold_min, threshold_max, threshold_step) == zone_num

            # 范围终点应该在下一个zone（如果存在）
            if zone_num < expected_zones - 1:
                assert calculate_zone(range_end, threshold_min, threshold_max, threshold_step) == zone_num + 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
