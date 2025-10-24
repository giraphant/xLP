#!/usr/bin/env python3
"""
基于 Pydantic 的配置管理系统
- 自动类型验证和转换
- 自动从环境变量读取
- 清晰的错误信息
"""

import os
import logging
from typing import Dict, Any, Optional
from pathlib import Path
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class ExchangeName(str, Enum):
    """支持的交易所"""
    MOCK = "mock"
    LIGHTER = "lighter"


class ExchangeConfig(BaseModel):
    """交易所配置"""
    name: ExchangeName = ExchangeName.MOCK
    private_key: str = ""
    account_index: int = Field(default=0, ge=0)
    api_key_index: int = Field(default=0, ge=0)
    base_url: str = "https://mainnet.zklighter.elliot.ai"

    @field_validator('private_key')
    @classmethod
    def validate_private_key(cls, v: str, info) -> str:
        """验证私钥：非 mock 交易所必须提供私钥"""
        name = info.data.get('name')
        if name != ExchangeName.MOCK and not v:
            raise ValueError(f'Private key required for exchange: {name}')
        return v


class PushoverConfig(BaseModel):
    """Pushover 通知配置"""
    user_key: str = ""
    api_token: str = ""
    enabled: bool = True

    @model_validator(mode='after')
    def validate_credentials(self):
        if self.enabled and (not self.user_key or not self.api_token):
            logger.warning("Pushover enabled but credentials missing")
        return self


class MatsuConfig(BaseModel):
    """Matsu 监控配置"""
    enabled: bool = False
    api_endpoint: str = "https://distill.baa.one/api/hedge-data"
    auth_token: str = ""
    pool_name: str = ""

    @model_validator(mode='after')
    def validate_matsu_config(self):
        if self.enabled and (not self.pool_name or not self.auth_token):
            logger.warning("Matsu enabled but pool_name/auth_token missing")
        return self


class HedgeConfig(BaseSettings):
    """
    对冲引擎完整配置

    自动从环境变量和 .env 文件读取配置
    环境变量优先级高于配置文件
    """

    # Pool
    jlp_amount: float = Field(default=0.0, ge=0)
    alp_amount: float = Field(default=0.0, ge=0)

    # 阈值
    threshold_min_usd: float = Field(default=5.0, gt=0)
    threshold_max_usd: float = Field(default=20.0, gt=0)
    threshold_step_usd: float = Field(default=2.5, gt=0)

    # 时间和比例
    check_interval_seconds: int = Field(default=60, ge=1)
    timeout_minutes: int = Field(default=20, ge=1)
    order_price_offset: float = Field(default=0.2, ge=0, le=10)
    close_ratio: float = Field(default=40.0, gt=0, le=100)
    cooldown_after_fill_minutes: int = Field(default=5, ge=0)

    # Dry run 模式
    dry_run: bool = Field(default=False, alias="DRY_RUN")

    # 初始偏移（其他平台的持仓）
    initial_offset_sol: float = Field(default=0.0, alias="INITIAL_OFFSET_SOL")
    initial_offset_eth: float = Field(default=0.0, alias="INITIAL_OFFSET_ETH")
    initial_offset_btc: float = Field(default=0.0, alias="INITIAL_OFFSET_BTC")
    initial_offset_bonk: float = Field(default=0.0, alias="INITIAL_OFFSET_BONK")

    # RPC
    rpc_url: str = "https://api.mainnet-beta.solana.com"

    # Exchange
    exchange_name: str = Field(default="mock", alias="EXCHANGE_NAME")
    exchange_private_key: str = Field(default="", alias="EXCHANGE_PRIVATE_KEY")
    exchange_account_index: int = Field(default=0, alias="EXCHANGE_ACCOUNT_INDEX")
    exchange_api_key_index: int = Field(default=0, alias="EXCHANGE_API_KEY_INDEX")
    exchange_base_url: str = Field(default="https://mainnet.zklighter.elliot.ai", alias="EXCHANGE_BASE_URL")

    # Pushover
    pushover_user_key: str = Field(default="", alias="PUSHOVER_USER_KEY")
    pushover_api_token: str = Field(default="", alias="PUSHOVER_API_TOKEN")
    pushover_enabled: bool = Field(default=True, alias="PUSHOVER_ENABLED")

    # Matsu
    matsu_enabled: bool = Field(default=False, alias="MATSU_ENABLED")
    matsu_api_endpoint: str = Field(default="", alias="MATSU_API_ENDPOINT")
    matsu_auth_token: str = Field(default="", alias="MATSU_AUTH_TOKEN")
    matsu_pool_name: str = Field(default="", alias="MATSU_POOL_NAME")

    # Pydantic 配置
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='ignore',  # 忽略额外的环境变量
        populate_by_name=True,  # 允许使用字段名或 alias
    )

    @model_validator(mode='after')
    def validate_config(self):
        """验证配置"""
        # 阈值检查
        if self.threshold_min_usd >= self.threshold_max_usd:
            raise ValueError(f"threshold_min ({self.threshold_min_usd}) must be < threshold_max ({self.threshold_max_usd})")

        num_steps = (self.threshold_max_usd - self.threshold_min_usd) / self.threshold_step_usd
        if num_steps > 100:
            logger.warning(f"Large number of threshold steps: {num_steps:.0f}")

        # 池子检查
        if self.jlp_amount == 0 and self.alp_amount == 0:
            logger.warning("Both JLP and ALP amounts are 0")

        # 偏移检查
        offsets = {'SOL': self.initial_offset_sol, 'ETH': self.initial_offset_eth,
                   'BTC': self.initial_offset_btc, 'BONK': self.initial_offset_bonk}
        large = [f"{s}={v}" for s, v in offsets.items() if abs(v) > 1000]
        if large:
            logger.warning(f"Large offsets: {', '.join(large)}")

        return self

    def get_exchange_config(self) -> ExchangeConfig:
        """获取交易所配置"""
        return ExchangeConfig(
            name=self.exchange_name,
            private_key=self.exchange_private_key,
            account_index=self.exchange_account_index,
            api_key_index=self.exchange_api_key_index,
            base_url=self.exchange_base_url,
        )

    def get_pushover_config(self) -> PushoverConfig:
        """获取 Pushover 配置"""
        return PushoverConfig(
            user_key=self.pushover_user_key,
            api_token=self.pushover_api_token,
            enabled=self.pushover_enabled,
        )

    def get_matsu_config(self) -> MatsuConfig:
        """获取 Matsu 配置"""
        return MatsuConfig(
            enabled=self.matsu_enabled,
            api_endpoint=self.matsu_api_endpoint,
            auth_token=self.matsu_auth_token,
            pool_name=self.matsu_pool_name,
        )

    def get_initial_offset(self) -> Dict[str, float]:
        """获取初始偏移字典（其他平台的持仓）"""
        return {
            "SOL": self.initial_offset_sol,
            "ETH": self.initial_offset_eth,
            "BTC": self.initial_offset_btc,
            "BONK": self.initial_offset_bonk,
        }

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为旧格式的字典（兼容性）
        """
        return {
            "jlp_amount": self.jlp_amount,
            "alp_amount": self.alp_amount,
            "threshold_min_usd": self.threshold_min_usd,
            "threshold_max_usd": self.threshold_max_usd,
            "threshold_step_usd": self.threshold_step_usd,
            "order_price_offset": self.order_price_offset,
            "close_ratio": self.close_ratio,
            "timeout_minutes": self.timeout_minutes,
            "check_interval_seconds": self.check_interval_seconds,
            "cooldown_after_fill_minutes": self.cooldown_after_fill_minutes,
            "initial_offset": self.get_initial_offset(),
            "rpc_url": self.rpc_url,
            "exchange": {
                "name": self.exchange_name,
                "private_key": self.exchange_private_key,
                "account_index": self.exchange_account_index,
                "api_key_index": self.exchange_api_key_index,
                "base_url": self.exchange_base_url,
            },
            "pushover": {
                "user_key": self.pushover_user_key,
                "api_token": self.pushover_api_token,
                "enabled": self.pushover_enabled,
            },
            "matsu": {
                "enabled": self.matsu_enabled,
                "api_endpoint": self.matsu_api_endpoint,
                "auth_token": self.matsu_auth_token,
                "pool_name": self.matsu_pool_name,
            }
        }

    def get_summary(self) -> str:
        """获取配置摘要"""
        lines = [
            "=" * 60,
            "Configuration Summary (Pydantic)",
            "=" * 60,
            f"Exchange: {self.exchange_name}",
            f"JLP Amount: ${self.jlp_amount:,.2f}",
            f"ALP Amount: ${self.alp_amount:,.2f}",
            f"Threshold Range: ${self.threshold_min_usd} - ${self.threshold_max_usd} (step: ${self.threshold_step_usd})",
            f"Check Interval: {self.check_interval_seconds}s",
            f"Pushover: {'Enabled' if self.pushover_enabled else 'Disabled'}",
            f"Matsu: {'Enabled' if self.matsu_enabled else 'Disabled'}",
            "=" * 60,
        ]
        return "\n".join(lines)


# 便捷函数
def load_config(env_file: Optional[Path] = None) -> HedgeConfig:
    """
    加载配置

    Args:
        env_file: .env 文件路径（可选）

    Returns:
        验证后的配置对象
    """
    if env_file:
        # 临时设置环境变量指向自定义 .env 文件
        os.environ['ENV_FILE'] = str(env_file)

    return HedgeConfig()


# 兼容性：保留 ValidationError 名称
class ValidationError(ValueError):
    """配置验证错误（兼容旧代码）"""
    pass
