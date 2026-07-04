"""审计日志浏览 API。

提供审计日志的读取和统计接口。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.core.audit_logger import audit_logger

router = APIRouter()


@router.get("/{task_id}")
async def read_audit_log(
    task_id: str,
    max_lines: int = Query(500, le=2000),
    offset: int = Query(0, ge=0),
):
    """读取任务的审计日志。

    URL 示例:
        GET /api/audit/abc123
        GET /api/audit/abc123?max_lines=100&offset=50
    """
    total = audit_logger.line_count(task_id)
    lines = audit_logger.read_lines(task_id, max_lines=max_lines, offset=offset)

    return {
        "task_id": task_id,
        "total_lines": total,
        "offset": offset,
        "count": len(lines),
        "events": lines,
    }


@router.get("/{task_id}/summary")
async def audit_summary(task_id: str):
    """返回审计日志摘要（按事件类型统计和关键指标）。

    URL 示例:
        GET /api/audit/abc123/summary
    """
    total = audit_logger.line_count(task_id)
    if total == 0:
        raise HTTPException(404, "No audit log found for this task")

    lines = audit_logger.read_lines(task_id, max_lines=2000)

    # Count by event type
    type_counts: dict[str, int] = {}
    pipeline_start = None
    pipeline_end = None
    rule_evals = 0
    rule_errors = 0
    s3_ops = 0
    s3_errors = 0

    for evt in lines:
        t = evt.get("type", "")
        type_counts[t] = type_counts.get(t, 0) + 1

        if t == "pipeline.start":
            pipeline_start = evt
        elif t == "pipeline.end":
            pipeline_end = evt
        elif t == "rule.evaluate":
            rule_evals += 1
            if evt.get("error"):
                rule_errors += 1
        elif t in ("s3.list_dir", "s3.read_file"):
            s3_ops += 1
            if evt.get("error"):
                s3_errors += 1

    # Extract duration
    duration_ms = 0
    if pipeline_start and pipeline_end:
        duration_ms = pipeline_end.get("duration_ms", 0)

    # Avg rule latency
    avg_rule_ms = 0
    rule_durations = [
        evt.get("duration_ms", 0) for evt in lines
        if evt.get("type") == "rule.evaluate" and evt.get("duration_ms")
    ]
    if rule_durations:
        avg_rule_ms = sum(rule_durations) // len(rule_durations)

    return {
        "task_id": task_id,
        "total_events": total,
        "event_types": type_counts,
        "pipeline_status": pipeline_end.get("status") if pipeline_end else "unknown",
        "duration_ms": duration_ms,
        "s3_operations": s3_ops,
        "s3_errors": s3_errors,
        "rule_evaluations": rule_evals,
        "rule_errors": rule_errors,
        "avg_rule_latency_ms": avg_rule_ms,
    }
