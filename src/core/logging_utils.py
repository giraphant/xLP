#!/usr/bin/env python3
"""
日志工具模块 - 处理日志安全和格式化
"""
import copy
from typing import Any, Dict


def mask_sensitive_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    遮蔽字典中的敏感信息（防止私钥、API密钥泄露）

    Args:
        data: 原始字典（会被深拷贝，不修改原数据）

    Returns:
        遮蔽后的字典副本
    """
    masked = copy.deepcopy(data)

    # 需要遮蔽的敏感字段
    sensitive_fields = [
        'private_key',
        'api_key',
        'api_secret',
        'api_token',
        'user_key',
        'secret',
        'password',
        'token'
    ]

    def _mask_dict(d: dict):
        """递归遮蔽字典"""
        for key, value in d.items():
            if isinstance(value, dict):
                _mask_dict(value)
            elif key.lower() in sensitive_fields and isinstance(value, str) and value:
                # 只显示前4位和后4位
                if len(value) > 8:
                    d[key] = f"{value[:4]}...{value[-4:]}"
                else:
                    d[key] = "***"

    _mask_dict(masked)
    return masked
