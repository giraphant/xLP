#!/usr/bin/env python3
"""
配置管理 - Linus 风格简化版

去掉不必要的复杂性：
- 不需要 pydantic（YAGNI）
- 不需要嵌套类（直接用 dict）
- 不需要复杂验证器（简单 if 检查）
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


def load_config_from_json(config_file: str = "config.json") -> Dict[str, Any]:
    """
    从 JSON 文件加载配置

    Args:
        config_file: JSON 配置文件路径

    Returns:
        配置字典
    """
    config_path = Path(config_file)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")

    with open(config_path, 'r') as f:
        config = json.load(f)

    # 标准化字段名（兼容main分支的config.json）
    normalized_config = {
        # Pool 配置
        "jlp_amount": config.get("jlp_amount", 0.0),
        "alp_amount": config.get("alp_amount", 0.0),

        # 阈值配置（兼容两种命名）
        "threshold_min_usd": config.get("threshold_min_usd", config.get("threshold_min", 5.0)),
        "threshold_max_usd": config.get("threshold_max_usd", config.get("threshold_max", 20.0)),
        "threshold_step_usd": config.get("threshold_step_usd", config.get("threshold_step", 2.5)),

        # 订单配置
        "order_price_offset": config.get("order_price_offset", 0.2),
        "close_ratio": config.get("close_ratio", 40.0),
        "timeout_minutes": config.get("timeout_minutes", 20),
        "cooldown_after_fill_minutes": config.get("cooldown_after_fill_minutes", 5),

        # 时间配置
        "interval_seconds": config.get("interval_seconds", config.get("check_interval_seconds", 60)),

        # RPC 配置
        "rpc_url": config.get("rpc_url", "https://api.mainnet-beta.solana.com"),

        # Exchange 配置
        "exchange": config.get("exchange", {}),

        # Pushover 配置
        "pushover": config.get("pushover", {}),

        # Matsu 配置
        "matsu": config.get("matsu", {}),

        # 初始偏移配置
        "initial_offset": config.get("initial_offset", {}),

        # 预定义偏移配置
        "predefined_offset": config.get("predefined_offset", {}),
    }

    _validate_config(normalized_config)
    return normalized_config


def load_config(env_file: Optional[Path] = None) -> Dict[str, Any]:
    """
    加载配置（从环境变量）

    Args:
        env_file: .env 文件路径（可选）

    Returns:
        配置字典
    """
    # 加载 .env 文件（如果存在）
    from dotenv import load_dotenv
    if env_file:
        load_dotenv(env_file)
    else:
        load_dotenv()

    # 构建配置字典
    config = {
        # Pool 配置
        "jlp_amount": float(os.getenv("JLP_AMOUNT", "0.0")),
        "alp_amount": float(os.getenv("ALP_AMOUNT", "0.0")),

        # 阈值配置
        "threshold_min_usd": float(os.getenv("THRESHOLD_MIN_USD", "5.0")),
        "threshold_max_usd": float(os.getenv("THRESHOLD_MAX_USD", "20.0")),
        "threshold_step_usd": float(os.getenv("THRESHOLD_STEP_USD", "2.5")),

        # 订单配置
        "order_price_offset": float(os.getenv("ORDER_PRICE_OFFSET", "0.2")),
        "close_ratio": float(os.getenv("CLOSE_RATIO", "40.0")),
        "timeout_minutes": int(os.getenv("TIMEOUT_MINUTES", "20")),
        "cooldown_after_fill_minutes": int(os.getenv("COOLDOWN_AFTER_FILL_MINUTES", "5")),

        # 时间配置
        "check_interval_seconds": int(os.getenv("CHECK_INTERVAL_SECONDS", "60")),

        # RPC 配置
        "rpc_url": os.getenv("RPC_URL", "https://api.mainnet-beta.solana.com"),

        # Exchange 配置（嵌套 dict）
        "exchange": {
            "name": os.getenv("EXCHANGE_NAME", "mock"),
            "private_key": os.getenv("EXCHANGE_PRIVATE_KEY", ""),
            "account_index": int(os.getenv("EXCHANGE_ACCOUNT_INDEX", "0")),
            "api_key_index": int(os.getenv("EXCHANGE_API_KEY_INDEX", "0")),
            "base_url": os.getenv("EXCHANGE_BASE_URL", "https://mainnet.zklighter.elliot.ai"),
        },

        # Pushover 配置
        "pushover": {
            "user_key": os.getenv("PUSHOVER_USER_KEY", ""),
            "api_token": os.getenv("PUSHOVER_API_TOKEN", ""),
            "enabled": os.getenv("PUSHOVER_ENABLED", "true").lower() == "true",
        },

        # Matsu 配置
        "matsu": {
            "enabled": os.getenv("MATSU_ENABLED", "false").lower() == "true",
            "api_endpoint": os.getenv("MATSU_API_ENDPOINT", "https://distill.baa.one/api/hedge-data"),
            "auth_token": os.getenv("MATSU_AUTH_TOKEN", ""),
            "pool_name": os.getenv("MATSU_POOL_NAME", ""),
        },

        # 初始偏移配置
        "initial_offset": {
            "SOL": float(os.getenv("INITIAL_OFFSET_SOL", "0.0")),
            "ETH": float(os.getenv("INITIAL_OFFSET_ETH", "0.0")),
            "BTC": float(os.getenv("INITIAL_OFFSET_BTC", "0.0")),
            "BONK": float(os.getenv("INITIAL_OFFSET_BONK", "0.0")),
        },

        # 预定义偏移配置
        "predefined_offset": {
            "SOL": float(os.getenv("PREDEFINED_OFFSET_SOL", "0.0")),
            "ETH": float(os.getenv("PREDEFINED_OFFSET_ETH", "0.0")),
            "BTC": float(os.getenv("PREDEFINED_OFFSET_BTC", "0.0")),
            "BONK": float(os.getenv("PREDEFINED_OFFSET_BONK", "0.0")),
        },
    }

    # 简单验证（只验证关键配置）
    _validate_config(config)

    return config


def _validate_config(config: Dict[str, Any]):
    """
    验证配置（简单的 if 检查）

    Args:
        config: 配置字典

    Raises:
        ValueError: 配置错误
    """
    # 验证阈值
    if config["threshold_min_usd"] <= 0:
        raise ValueError("threshold_min_usd must be > 0")

    if config["threshold_max_usd"] <= config["threshold_min_usd"]:
        raise ValueError(
            f"threshold_max_usd ({config['threshold_max_usd']}) must be greater than "
            f"threshold_min_usd ({config['threshold_min_usd']})"
        )

    # 检查步长是否合理
    num_steps = (config["threshold_max_usd"] - config["threshold_min_usd"]) / config["threshold_step_usd"]
    if num_steps > 100:
        logger.warning(f"Large number of threshold steps: {num_steps:.0f}")

    # 验证 exchange
    if config["exchange"]["name"] != "mock":
        if not config["exchange"]["private_key"]:
            raise ValueError(f"Private key required for non-mock exchange: {config['exchange']['name']}")

    # 验证 pool amounts
    if config["jlp_amount"] == 0 and config["alp_amount"] == 0:
        logger.warning("Both JLP and ALP amounts are 0, no hedging will occur")

    # 检查大偏移
    large_offsets = []
    for symbol, value in config["initial_offset"].items():
        if abs(value) > 1000:
            large_offsets.append(f"{symbol}={value}")

    if large_offsets:
        logger.warning(f"Large initial offsets detected: {', '.join(large_offsets)}")

    # 检查 Pushover 配置
    if config["pushover"]["enabled"]:
        if not config["pushover"]["user_key"] or not config["pushover"]["api_token"]:
            logger.warning("Pushover enabled but credentials not provided, notifications will be disabled")

    # 检查 Matsu 配置
    if config["matsu"]["enabled"]:
        if not config["matsu"]["pool_name"]:
            logger.warning("Matsu enabled but pool_name not provided")
        if not config["matsu"]["auth_token"]:
            logger.warning("Matsu enabled but auth_token not provided")


# 便捷类（兼容旧代码）
class HedgeConfig:
    """配置类（兼容旧接口）"""

    def __init__(self, env_file: Optional[Path] = None):
        """
        初始化配置

        Args:
            env_file: .env文件路径（可选）
        """
        # 从环境变量加载配置
        self._config = load_config(env_file)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return self._config

    def get_summary(self) -> str:
        """获取配置摘要"""
        lines = [
            "=" * 60,
            "Configuration Summary",
            "=" * 60,
            f"Exchange: {self._config['exchange']['name']}",
            f"JLP Amount: ${self._config['jlp_amount']:,.2f}",
            f"ALP Amount: ${self._config['alp_amount']:,.2f}",
            f"Threshold Range: ${self._config['threshold_min_usd']} - ${self._config['threshold_max_usd']} "
            f"(step: ${self._config['threshold_step_usd']})",
            f"Check Interval: {self._config['check_interval_seconds']}s",
            f"Pushover: {'Enabled' if self._config['pushover']['enabled'] else 'Disabled'}",
            f"Matsu: {'Enabled' if self._config['matsu']['enabled'] else 'Disabled'}",
            "=" * 60,
        ]
        return "\n".join(lines)


# 兼容性：保留 ValidationError 名称
class ValidationError(ValueError):
    """配置验证错误（兼容旧代码）"""
    pass
