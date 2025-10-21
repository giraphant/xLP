"""
Exchange integration modules - 统一入口
"""

from .interface import ExchangeInterface
from .mock import MockExchange
from .lighter.adapter import LighterExchange
from .lighter import LighterClient


def create_exchange(config: dict) -> ExchangeInterface:
    """
    工厂函数：根据配置创建交易所实例

    Args:
        config: 交易所配置
            {
                "name": "lighter" | "mock",
                "private_key": "...",  # for lighter
                ...
            }

    Returns:
        ExchangeInterface实例

    Examples:
        >>> exchange = create_exchange({"name": "mock"})
        >>> exchange = create_exchange({
        ...     "name": "lighter",
        ...     "private_key": "0x...",
        ...     "account_index": 0
        ... })
    """
    name = config.get("name", "").lower()

    if name == "mock":
        return MockExchange(config)
    elif name == "lighter":
        return LighterExchange(config)
    else:
        raise ValueError(f"Unknown exchange: {name}")


__all__ = [
    'ExchangeInterface',
    'MockExchange',
    'LighterExchange',
    'LighterClient',
    'create_exchange',
]
