#!/usr/bin/env python3
"""
配置验证增强 - 使用类型安全和自动验证
提供配置的完整性检查和类型保证
"""

import os
import json
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path
from datetime import datetime

# 注意：为了避免增加外部依赖，这里使用dataclasses代替pydantic
# 如果需要更强大的验证功能，可以安装pydantic并替换
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class ExchangeName(str, Enum):
    """支持的交易所"""
    MOCK = "mock"
    LIGHTER = "lighter"


class ValidationError(Exception):
    """配置验证错误"""
    pass


@dataclass
class ExchangeConfig:
    """交易所配置"""
    name: str
    private_key: str = ""
    account_index: int = 0
    api_key_index: int = 0
    base_url: str = "https://mainnet.zklighter.elliot.ai"

    def validate(self):
        """验证交易所配置"""
        # 验证交易所名称
        if self.name not in [e.value for e in ExchangeName]:
            raise ValidationError(
                f"Unsupported exchange: {self.name}. "
                f"Supported: {[e.value for e in ExchangeName]}"
            )

        # 如果是真实交易所，需要私钥
        if self.name != ExchangeName.MOCK.value and not self.private_key:
            raise ValidationError(f"Private key required for exchange: {self.name}")

        # 验证账户索引
        if self.account_index < 0:
            raise ValidationError(f"Invalid account_index: {self.account_index}")

        if self.api_key_index < 0:
            raise ValidationError(f"Invalid api_key_index: {self.api_key_index}")


@dataclass
class PushoverConfig:
    """Pushover通知配置"""
    user_key: str = ""
    api_token: str = ""
    enabled: bool = True

    def validate(self):
        """验证Pushover配置"""
        if self.enabled and (not self.user_key or not self.api_token):
            logger.warning("Pushover enabled but credentials not provided")


@dataclass
class ThresholdConfig:
    """阈值配置"""
    min_usd: float = 5.0
    max_usd: float = 20.0
    step_usd: float = 2.5

    def validate(self):
        """验证阈值配置"""
        if self.min_usd <= 0:
            raise ValidationError(f"threshold_min_usd must be positive: {self.min_usd}")

        if self.max_usd <= 0:
            raise ValidationError(f"threshold_max_usd must be positive: {self.max_usd}")

        if self.min_usd >= self.max_usd:
            raise ValidationError(
                f"threshold_min_usd ({self.min_usd}) must be less than "
                f"threshold_max_usd ({self.max_usd})"
            )

        if self.step_usd <= 0:
            raise ValidationError(f"threshold_step_usd must be positive: {self.step_usd}")

        # 检查步长是否合理
        num_steps = (self.max_usd - self.min_usd) / self.step_usd
        if num_steps > 100:
            logger.warning(f"Large number of threshold steps: {num_steps:.0f}")


@dataclass
class PoolConfig:
    """流动性池配置"""
    jlp_amount: float = 0.0
    alp_amount: float = 0.0

    def validate(self):
        """验证池子配置"""
        if self.jlp_amount < 0:
            raise ValidationError(f"jlp_amount cannot be negative: {self.jlp_amount}")

        if self.alp_amount < 0:
            raise ValidationError(f"alp_amount cannot be negative: {self.alp_amount}")

        if self.jlp_amount == 0 and self.alp_amount == 0:
            logger.warning("Both JLP and ALP amounts are 0, no hedging will occur")


@dataclass
class TimingConfig:
    """时间配置"""
    check_interval_seconds: int = 60
    timeout_minutes: int = 20
    order_price_offset: float = 0.2
    close_ratio: float = 40.0

    def validate(self):
        """验证时间配置"""
        if self.check_interval_seconds < 1:
            raise ValidationError(
                f"check_interval_seconds must be at least 1: {self.check_interval_seconds}"
            )

        if self.timeout_minutes < 1:
            raise ValidationError(f"timeout_minutes must be at least 1: {self.timeout_minutes}")

        if not 0 <= self.order_price_offset <= 10:
            raise ValidationError(
                f"order_price_offset should be between 0 and 10%: {self.order_price_offset}"
            )

        if not 0 < self.close_ratio <= 100:
            raise ValidationError(f"close_ratio must be between 0 and 100: {self.close_ratio}")


@dataclass
class InitialOffsetConfig:
    """初始偏移配置"""
    SOL: float = 0.0
    ETH: float = 0.0
    BTC: float = 0.0
    BONK: float = 0.0

    def validate(self):
        """验证初始偏移"""
        # 初始偏移通常应该较小
        large_offsets = []
        for symbol in ["SOL", "ETH", "BTC", "BONK"]:
            value = getattr(self, symbol)
            if abs(value) > 1000:  # 根据币种调整阈值
                large_offsets.append(f"{symbol}={value}")

        if large_offsets:
            logger.warning(f"Large initial offsets detected: {', '.join(large_offsets)}")


@dataclass
class HedgeConfig:
    """完整的对冲引擎配置"""
    # 子配置
    exchange: ExchangeConfig
    pushover: PushoverConfig
    thresholds: ThresholdConfig
    pools: PoolConfig
    timing: TimingConfig
    initial_offset: InitialOffsetConfig

    # 其他配置
    rpc_url: str = "https://api.mainnet-beta.solana.com"
    predefined_offset: Dict[str, float] = field(default_factory=dict)  # 外部对冲调整

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "HedgeConfig":
        """从字典创建配置对象"""
        # 提取子配置
        exchange_dict = config_dict.get("exchange", {})
        pushover_dict = config_dict.get("pushover", {})

        # 处理阈值配置（兼容新旧格式）
        thresholds_dict = {
            "min_usd": config_dict.get("threshold_min_usd",
                                       config_dict.get("threshold_min", 5.0)),
            "max_usd": config_dict.get("threshold_max_usd",
                                       config_dict.get("threshold_max", 20.0)),
            "step_usd": config_dict.get("threshold_step_usd",
                                        config_dict.get("threshold_step", 2.5))
        }

        pools_dict = {
            "jlp_amount": config_dict.get("jlp_amount", 0.0),
            "alp_amount": config_dict.get("alp_amount", 0.0)
        }

        timing_dict = {
            "check_interval_seconds": config_dict.get("check_interval_seconds", 60),
            "timeout_minutes": config_dict.get("timeout_minutes", 20),
            "order_price_offset": config_dict.get("order_price_offset", 0.2),
            "close_ratio": config_dict.get("close_ratio", 40.0)
        }

        initial_offset_dict = config_dict.get("initial_offset", {})
        predefined_offset_dict = config_dict.get("predefined_offset", {})

        return cls(
            exchange=ExchangeConfig(**exchange_dict),
            pushover=PushoverConfig(**pushover_dict),
            thresholds=ThresholdConfig(**thresholds_dict),
            pools=PoolConfig(**pools_dict),
            timing=TimingConfig(**timing_dict),
            initial_offset=InitialOffsetConfig(**initial_offset_dict),
            rpc_url=config_dict.get("rpc_url", "https://api.mainnet-beta.solana.com"),
            predefined_offset=predefined_offset_dict
        )

    @classmethod
    def from_env_and_file(
        cls,
        config_file: Optional[Path] = None,
        required: bool = False
    ) -> "HedgeConfig":
        """
        从环境变量和配置文件加载配置

        环境变量优先级高于配置文件

        Args:
            config_file: 配置文件路径
            required: 是否要求配置文件存在

        Returns:
            验证后的配置对象
        """
        config_dict = {}

        # 从文件加载（如果存在）
        if config_file and config_file.exists():
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config_dict = json.load(f)
                logger.info(f"Loaded configuration from {config_file}")
            except json.JSONDecodeError as e:
                raise ValidationError(f"Invalid JSON in config file: {e}")
        elif required and config_file:
            raise ValidationError(f"Required config file not found: {config_file}")

        # 从环境变量覆盖
        config_dict = cls._override_from_env(config_dict)

        # 创建并验证配置
        config = cls.from_dict(config_dict)
        config.validate()

        return config

    @staticmethod
    def _override_from_env(config_dict: Dict[str, Any]) -> Dict[str, Any]:
        """从环境变量覆盖配置"""
        # Pool配置
        if "JLP_AMOUNT" in os.environ:
            config_dict["jlp_amount"] = float(os.getenv("JLP_AMOUNT"))
        if "ALP_AMOUNT" in os.environ:
            config_dict["alp_amount"] = float(os.getenv("ALP_AMOUNT"))

        # 阈值配置
        if "THRESHOLD_MIN_USD" in os.environ:
            config_dict["threshold_min_usd"] = float(os.getenv("THRESHOLD_MIN_USD"))
        if "THRESHOLD_MAX_USD" in os.environ:
            config_dict["threshold_max_usd"] = float(os.getenv("THRESHOLD_MAX_USD"))
        if "THRESHOLD_STEP_USD" in os.environ:
            config_dict["threshold_step_usd"] = float(os.getenv("THRESHOLD_STEP_USD"))

        # 时间配置
        if "CHECK_INTERVAL_SECONDS" in os.environ:
            config_dict["check_interval_seconds"] = int(os.getenv("CHECK_INTERVAL_SECONDS"))
        if "TIMEOUT_MINUTES" in os.environ:
            config_dict["timeout_minutes"] = int(os.getenv("TIMEOUT_MINUTES"))
        if "ORDER_PRICE_OFFSET" in os.environ:
            config_dict["order_price_offset"] = float(os.getenv("ORDER_PRICE_OFFSET"))
        if "CLOSE_RATIO" in os.environ:
            config_dict["close_ratio"] = float(os.getenv("CLOSE_RATIO"))

        # 交易所配置
        if "exchange" not in config_dict:
            config_dict["exchange"] = {}
        if "EXCHANGE_NAME" in os.environ:
            config_dict["exchange"]["name"] = os.getenv("EXCHANGE_NAME")
        if "EXCHANGE_PRIVATE_KEY" in os.environ:
            config_dict["exchange"]["private_key"] = os.getenv("EXCHANGE_PRIVATE_KEY")
        if "EXCHANGE_ACCOUNT_INDEX" in os.environ:
            config_dict["exchange"]["account_index"] = int(os.getenv("EXCHANGE_ACCOUNT_INDEX"))
        if "EXCHANGE_API_KEY_INDEX" in os.environ:
            config_dict["exchange"]["api_key_index"] = int(os.getenv("EXCHANGE_API_KEY_INDEX"))
        if "EXCHANGE_BASE_URL" in os.environ:
            config_dict["exchange"]["base_url"] = os.getenv("EXCHANGE_BASE_URL")

        # Pushover配置
        if "pushover" not in config_dict:
            config_dict["pushover"] = {}
        if "PUSHOVER_USER_KEY" in os.environ:
            config_dict["pushover"]["user_key"] = os.getenv("PUSHOVER_USER_KEY")
        if "PUSHOVER_API_TOKEN" in os.environ:
            config_dict["pushover"]["api_token"] = os.getenv("PUSHOVER_API_TOKEN")
        if "PUSHOVER_ENABLED" in os.environ:
            config_dict["pushover"]["enabled"] = (
                os.getenv("PUSHOVER_ENABLED", "true").lower() in ("true", "1", "yes")
            )

        # 初始偏移配置
        if "initial_offset" not in config_dict:
            config_dict["initial_offset"] = {}
        for symbol in ["SOL", "ETH", "BTC", "BONK"]:
            env_key = f"INITIAL_OFFSET_{symbol}"
            if env_key in os.environ:
                config_dict["initial_offset"][symbol] = float(os.getenv(env_key))

        # RPC URL
        if "RPC_URL" in os.environ:
            config_dict["rpc_url"] = os.getenv("RPC_URL")

        # 预设偏移配置（用于外部对冲调整）
        # 支持两种方式：
        # 方式1（推荐）：独立环境变量 PREDEFINED_OFFSET_SOL=-1.0
        # 方式2：JSON字符串 PREDEFINED_OFFSET='{"SOL": -1.0}'
        predefined_offset = {}

        # 方式1：从独立的环境变量读取（优先）
        for symbol in ["SOL", "ETH", "BTC", "BONK"]:
            env_key = f"PREDEFINED_OFFSET_{symbol}"
            if env_key in os.environ:
                try:
                    predefined_offset[symbol] = float(os.getenv(env_key))
                    logger.info(f"Loaded predefined_offset from {env_key}: {predefined_offset[symbol]}")
                except ValueError as e:
                    logger.error(f"Invalid value in {env_key}: {e}")
                    raise ValidationError(f"{env_key} must be a valid number: {e}")

        # 方式2：从JSON字符串读取（兼容旧配置）
        if "PREDEFINED_OFFSET" in os.environ and not predefined_offset:
            try:
                predefined_offset_str = os.getenv("PREDEFINED_OFFSET")
                predefined_offset = json.loads(predefined_offset_str)
                logger.info(f"Loaded predefined_offset from JSON env: {predefined_offset}")
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in PREDEFINED_OFFSET: {e}")
                raise ValidationError(f"PREDEFINED_OFFSET must be valid JSON: {e}")

        # 保存到配置字典
        if predefined_offset:
            config_dict["predefined_offset"] = predefined_offset

        return config_dict

    def validate(self):
        """验证完整配置"""
        logger.info("Validating configuration...")

        # 验证各子配置
        self.exchange.validate()
        self.pushover.validate()
        self.thresholds.validate()
        self.pools.validate()
        self.timing.validate()
        self.initial_offset.validate()

        # 验证RPC URL
        if not self.rpc_url:
            raise ValidationError("rpc_url is required")

        # 交叉验证
        self._cross_validate()

        logger.info("Configuration validation successful")

    def _cross_validate(self):
        """交叉验证不同配置部分之间的关系"""
        # 检查超时和检查间隔的关系
        if self.timing.timeout_minutes * 60 < self.timing.check_interval_seconds:
            logger.warning(
                f"Timeout ({self.timing.timeout_minutes}min) is less than "
                f"check interval ({self.timing.check_interval_seconds}s)"
            )

        # 如果没有池子金额，警告其他配置无效
        if self.pools.jlp_amount == 0 and self.pools.alp_amount == 0:
            logger.warning("No pool amounts configured, most settings will be unused")

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于兼容旧代码）"""
        result = {
            "jlp_amount": self.pools.jlp_amount,
            "alp_amount": self.pools.alp_amount,
            "threshold_min_usd": self.thresholds.min_usd,
            "threshold_max_usd": self.thresholds.max_usd,
            "threshold_step_usd": self.thresholds.step_usd,
            "check_interval_seconds": self.timing.check_interval_seconds,
            "timeout_minutes": self.timing.timeout_minutes,
            "order_price_offset": self.timing.order_price_offset,
            "close_ratio": self.timing.close_ratio,
            "exchange": asdict(self.exchange),
            "pushover": asdict(self.pushover),
            "initial_offset": asdict(self.initial_offset),
            "rpc_url": self.rpc_url,
            "predefined_offset": self.predefined_offset
        }

        return result

    def save(self, filepath: Path):
        """保存配置到文件"""
        try:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
            logger.info(f"Configuration saved to {filepath}")
        except Exception as e:
            raise ValidationError(f"Failed to save configuration: {e}")

    def get_summary(self) -> str:
        """获取配置摘要"""
        lines = [
            "Configuration Summary:",
            f"  Exchange: {self.exchange.name}",
            f"  JLP Amount: {self.pools.jlp_amount:,.2f}",
            f"  ALP Amount: {self.pools.alp_amount:,.2f}",
            f"  Thresholds: ${self.thresholds.min_usd}-${self.thresholds.max_usd} "
            f"(step: ${self.thresholds.step_usd})",
            f"  Check Interval: {self.timing.check_interval_seconds}s",
            f"  Timeout: {self.timing.timeout_minutes}min",
            f"  Close Ratio: {self.timing.close_ratio}%",
            f"  Pushover: {'Enabled' if self.pushover.enabled else 'Disabled'}"
        ]

        # 显示预设偏移（如果配置了）
        if self.predefined_offset:
            offsets_str = ", ".join([f"{k}:{v:+.4f}" for k, v in self.predefined_offset.items()])
            lines.append(f"  Predefined Offsets: {offsets_str}")

        return "\n".join(lines)


# 便捷函数
def load_and_validate_config(
    config_file: Optional[str] = None,
    required: bool = False
) -> HedgeConfig:
    """
    加载并验证配置的便捷函数

    Args:
        config_file: 配置文件路径
        required: 是否要求配置文件存在

    Returns:
        验证后的配置对象

    Raises:
        ValidationError: 配置验证失败
    """
    config_path = Path(config_file) if config_file else Path("config.json")
    return HedgeConfig.from_env_and_file(config_path, required)