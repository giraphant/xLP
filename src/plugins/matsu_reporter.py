"""
Matsu监控系统上报插件

将xLP对冲引擎的关键数据上报到Matsu监控系统：
- 理想对冲量 (ideal_hedge)
- 实际对冲量 (actual_hedge)
- 平均成本 (cost_basis)

特性:
- 非侵入式设计：失败不影响主程序
- 可插拔：通过配置启用/禁用
- 异步上报：不阻塞Pipeline执行
"""

import logging
import aiohttp
from datetime import datetime
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class MatsuReporter:
    """Matsu监控系统上报器"""

    def __init__(
        self,
        api_url: str,
        auth_token: str,
        enabled: bool = True,
        timeout: int = 10,
        pool_name: str = "xLP"
    ):
        """
        初始化Matsu上报器

        Args:
            api_url: Matsu API endpoint (不含query参数)
            auth_token: 认证token (WEBHOOK_SECRET)
            enabled: 是否启用上报
            timeout: HTTP请求超时时间（秒）
            pool_name: 池子名称前缀（用于monitor_id）
        """
        self.api_url = api_url
        self.auth_token = auth_token
        self.enabled = enabled
        self.timeout = timeout
        self.pool_name = pool_name

        if not self.enabled:
            logger.info("MatsuReporter is disabled")
        else:
            logger.info(f"MatsuReporter initialized: {api_url}")

    async def report(
        self,
        ideal_hedges: Dict[str, float],
        actual_hedges: Dict[str, float],
        cost_bases: Dict[str, float],
        timestamp: Optional[str] = None
    ) -> bool:
        """
        上报对冲数据到Matsu监控系统

        Args:
            ideal_hedges: 理想对冲量 {symbol: amount}
            actual_hedges: 实际对冲量 {symbol: amount}
            cost_bases: 平均成本 {symbol: price}
            timestamp: 时间戳（ISO 8601格式），不提供则使用当前时间

        Returns:
            bool: 是否成功
        """
        if not self.enabled:
            logger.debug("MatsuReporter is disabled, skipping report")
            return True

        if not timestamp:
            timestamp = datetime.utcnow().isoformat() + 'Z'

        # 转换数据格式
        data_points = self._build_data_points(
            ideal_hedges,
            actual_hedges,
            cost_bases,
            timestamp
        )

        if not data_points:
            logger.warning("No data points to report")
            return False

        # 发送到Matsu
        return await self._send_to_matsu(data_points)

    def _build_data_points(
        self,
        ideal_hedges: Dict[str, float],
        actual_hedges: Dict[str, float],
        cost_bases: Dict[str, float],
        timestamp: str
    ) -> List[Dict[str, Any]]:
        """
        构建Matsu API格式的数据点

        每个币种生成3个数据点：
        - {pool}_ideal_{symbol}: 理想对冲量
        - {pool}_actual_{symbol}: 实际对冲量
        - {pool}_cost_{symbol}: 平均成本
        """
        data_points = []

        # 获取所有涉及的币种
        all_symbols = set(ideal_hedges.keys()) | set(actual_hedges.keys()) | set(cost_bases.keys())

        for symbol in all_symbols:
            # 1. 理想对冲量
            if symbol in ideal_hedges:
                data_points.append({
                    "monitor_id": f"{self.pool_name}_ideal_{symbol}",
                    "monitor_name": f"{self.pool_name} {symbol} 理想对冲量",
                    "value": ideal_hedges[symbol],
                    "timestamp": timestamp
                })

            # 2. 实际对冲量
            if symbol in actual_hedges:
                data_points.append({
                    "monitor_id": f"{self.pool_name}_actual_{symbol}",
                    "monitor_name": f"{self.pool_name} {symbol} 实际对冲量",
                    "value": actual_hedges[symbol],
                    "timestamp": timestamp
                })

            # 3. 平均成本
            if symbol in cost_bases:
                data_points.append({
                    "monitor_id": f"{self.pool_name}_cost_{symbol}",
                    "monitor_name": f"{self.pool_name} {symbol} 平均成本",
                    "value": cost_bases[symbol],
                    "timestamp": timestamp
                })

        logger.debug(f"Built {len(data_points)} data points for {len(all_symbols)} symbols")
        return data_points

    async def _send_to_matsu(self, data_points: List[Dict[str, Any]]) -> bool:
        """
        发送数据到Matsu API

        Args:
            data_points: 数据点列表

        Returns:
            bool: 是否成功
        """
        payload = {"data_points": data_points}
        url = f"{self.api_url}?token={self.auth_token}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"✓ Matsu report successful: {result.get('message', 'OK')}")
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(f"✗ Matsu report failed: {response.status} - {error_text}")
                        return False

        except asyncio.TimeoutError:
            logger.error(f"✗ Matsu report timeout after {self.timeout}s")
            return False
        except aiohttp.ClientError as e:
            logger.error(f"✗ Matsu report network error: {e}")
            return False
        except Exception as e:
            logger.error(f"✗ Matsu report unexpected error: {e}", exc_info=True)
            return False


# 用于测试的辅助函数
async def test_matsu_reporter():
    """测试Matsu上报器"""
    reporter = MatsuReporter(
        api_url="https://distill.baa.one/api/hedge-data",
        auth_token="your_token_here",
        enabled=True,
        pool_name="xLP_Test"
    )

    # 模拟数据
    ideal_hedges = {
        "SOL": -10.5,
        "ETH": -2.3,
        "BTC": -0.05
    }

    actual_hedges = {
        "SOL": -10.2,
        "ETH": -2.3,
        "BTC": -0.048
    }

    cost_bases = {
        "SOL": 184.50,
        "ETH": 3200.00,
        "BTC": 68000.00
    }

    success = await reporter.report(ideal_hedges, actual_hedges, cost_bases)
    print(f"Test result: {'Success' if success else 'Failed'}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_matsu_reporter())
