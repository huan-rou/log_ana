"""独立审计日志记录器。

以 JSON Lines 格式记录分析流水线的完整生命周期：
任务启停、S3 I/O、失败检测统计、每条规则的调用及匹配结果。

每任务一个文件：{audit_dir}/{task_id}.audit.jsonl
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class AuditLogger:
    """独立审计日志记录器。

    异步安全，以 task_id 为维度隔离写入锁。
    所有方法都是 fire-and-forget：写入失败不抛异常，仅静默忽略。
    """

    def __init__(self, audit_dir: str, enabled: bool = True):
        self._dir = Path(audit_dir)
        self._enabled = enabled
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = threading.Lock()

    # ── Internal ──

    def _get_lock(self, task_id: str) -> asyncio.Lock:
        with self._global_lock:
            if task_id not in self._locks:
                self._locks[task_id] = asyncio.Lock()
            return self._locks[task_id]

    async def log(self, task_id: str, event_type: str, **fields) -> None:
        if not self._enabled:
            return
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "task_id": task_id,
            **fields,
        }
        lock = self._get_lock(task_id)
        async with lock:
            try:
                self._dir.mkdir(parents=True, exist_ok=True)
                filepath = self._dir / f"{task_id}.audit.jsonl"
                line = json.dumps(entry, ensure_ascii=False, default=str)
                with open(filepath, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass  # audit log must never crash the pipeline

    # ── Pipeline lifecycle ──

    async def pipeline_start(self, task_id: str, *, source_type: str = "",
                             parser_type: str = "", **kw) -> None:
        await self.log(task_id, "pipeline.start",
                       source_type=source_type, parser_type=parser_type, **kw)

    async def pipeline_end(self, task_id: str, *, status: str = "",
                           total_entries: int = 0, failure_count: int = 0,
                           classified: int = 0, unrecognized: int = 0,
                           duration_ms: int = 0, **kw) -> None:
        await self.log(task_id, "pipeline.end",
                       status=status, total_entries=total_entries,
                       failure_count=failure_count, classified=classified,
                       unrecognized=unrecognized, duration_ms=duration_ms, **kw)

    async def step_enter(self, task_id: str, *, step: str, **kw) -> None:
        await self.log(task_id, "step.enter", step=step, **kw)

    async def step_exit(self, task_id: str, *, step: str, **kw) -> None:
        await self.log(task_id, "step.exit", step=step, **kw)

    # ── S3 I/O ──

    async def s3_list_dir(self, task_id: str, *, path: str = "",
                          count: int = 0, duration_ms: int = 0,
                          error: str = "", **kw) -> None:
        await self.log(task_id, "s3.list_dir",
                       path=path, count=count, duration_ms=duration_ms,
                       error=error, **kw)

    async def s3_read_file(self, task_id: str, *, path: str = "",
                           size: int = 0, duration_ms: int = 0,
                           error: str = "", **kw) -> None:
        await self.log(task_id, "s3.read_file",
                       path=path, size=size, duration_ms=duration_ms,
                       error=error, **kw)

    # ── Rule engine ──

    async def rule_evaluate(self, task_id: str, *, rule_id: str = "",
                            failure_id: str = "", matched: bool = False,
                            category: str = "", confidence: float = 0.0,
                            duration_ms: int = 0, error: str = "", **kw) -> None:
        await self.log(task_id, "rule.evaluate",
                       rule_id=rule_id, failure_id=failure_id,
                       matched=matched, category=category,
                       confidence=confidence, duration_ms=duration_ms,
                       error=error, **kw)

    async def failure_classified(self, task_id: str, *, failure_id: str = "",
                                 is_fallback: bool = False, category: str = "",
                                 confidence: float = 0.0, evidence: str = "",
                                 rule_id: str = "", **kw) -> None:
        await self.log(task_id, "failure.classified",
                       failure_id=failure_id, is_fallback=is_fallback,
                       category=category, confidence=confidence,
                       evidence=evidence, rule_id=rule_id, **kw)

    # ── Warnings ──

    async def warning(self, task_id: str, *, message: str = "", **kw) -> None:
        await self.log(task_id, "warning", message=message, **kw)

    # ── File reading (for browse API) ──

    def read_lines(self, task_id: str, *, max_lines: int = 500,
                   offset: int = 0) -> list[dict]:
        """读取审计日志文件的内容（同步，供 API 使用）。"""
        filepath = self._dir / f"{task_id}.audit.jsonl"
        if not filepath.exists():
            return []
        lines: list[dict] = []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        except Exception:
            return []
        total = len(lines)
        if offset >= total:
            return []
        slice_end = min(offset + max_lines, total)
        return lines[offset:slice_end]

    def line_count(self, task_id: str) -> int:
        """返回审计日志行数。"""
        filepath = self._dir / f"{task_id}.audit.jsonl"
        if not filepath.exists():
            return 0
        count = 0
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for _ in f:
                    count += 1
        except Exception:
            pass
        return count


# ── 全局单例 ──

audit_logger = AuditLogger(audit_dir="./data/audit", enabled=True)


def init_audit_logger(audit_dir: str, enabled: bool):
    """根据配置重新初始化全局审计日志器。"""
    global audit_logger
    audit_logger = AuditLogger(audit_dir=audit_dir, enabled=enabled)
