#!/usr/bin/env python3
"""
审计日志 - 记录所有决策和操作

职责：
- 记录决策过程
- 记录执行结果
- 可选的文件/数据库输出

特点：
- 通过回调注入到HedgeBot
- 线程安全（同步操作，去掉 async 开销）
- 结构化日志
"""

import json
import threading
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

logger = logging.getLogger(__name__)


class AuditLog:
    """
    审计日志 - Linus 风格重构

    去掉不必要的 async（文件写入已经是同步的！）
    """

    def __init__(
        self,
        log_file: Optional[str] = None,
        enabled: bool = True
    ):
        """
        初始化审计日志

        Args:
            log_file: 日志文件路径（如果为None则只输出到logger）
            enabled: 是否启用
        """
        self.enabled = enabled
        self.log_file = Path(log_file) if log_file else None
        self.lock = threading.Lock()  # 同步锁

        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"Audit log enabled: {self.log_file}")

    def log_decision(self, symbol: str, decision: Any, **kwargs):
        """
        记录决策（同步操作）

        Args:
            symbol: 币种符号
            decision: 决策对象
            **kwargs: 额外信息
        """
        if not self.enabled:
            return

        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": "decision",
            "symbol": symbol,
            "action": decision.action,
            "reason": decision.reason,
            "metadata": decision.metadata,
            **kwargs
        }

        self._write_entry(entry)

    def log_action(self, symbol: str, action: str, result: dict, **kwargs):
        """
        记录操作（同步操作）

        Args:
            symbol: 币种符号
            action: 操作类型
            result: 执行结果
            **kwargs: 额外信息
        """
        if not self.enabled:
            return

        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": "action",
            "symbol": symbol,
            "action": action,
            "success": result.get("success", False),
            "result": result,
            **kwargs
        }

        self._write_entry(entry)

    def log_error(self, error: str, **kwargs):
        """
        记录错误（同步操作）

        Args:
            error: 错误信息
            **kwargs: 额外信息
        """
        if not self.enabled:
            return

        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": "error",
            "error": error,
            **kwargs
        }

        self._write_entry(entry)

    def _write_entry(self, entry: dict):
        """写入日志条目（同步操作）"""
        with self.lock:
            # 写入logger
            logger.info(f"[AUDIT] {entry['type']}: {json.dumps(entry, ensure_ascii=False)}")

            # 写入文件（如果配置）
            if self.log_file:
                try:
                    with open(self.log_file, "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                except Exception as e:
                    logger.error(f"Failed to write audit log: {e}")
