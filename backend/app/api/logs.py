from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.task import Task, LogEntry

router = APIRouter()


@router.get("/{task_id}/entries")
async def list_entries(
    task_id: str,
    level: Optional[str] = Query(None),
    is_error: Optional[bool] = Query(None),
    script_name: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
):
    """获取任务的解析后日志条目，支持过滤和搜索。"""
    # Verify task exists
    task = (
        await db.execute(select(Task).where(Task.id == task_id))
    ).scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")

    query = select(LogEntry).where(LogEntry.task_id == task_id)

    if level:
        query = query.where(LogEntry.level == level.upper())
    if is_error is not None:
        query = query.where(LogEntry.is_error == is_error)
    if script_name:
        query = query.where(LogEntry.script_name.contains(script_name))
    if search:
        query = query.where(
            LogEntry.message.contains(search) | LogEntry.raw_line.contains(search)
        )

    query = query.order_by(LogEntry.line_number).offset(offset).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{task_id}/failures")
async def list_failures(
    task_id: str,
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
):
    """获取任务的失败事件列表。"""
    from app.models.task import FailureEvent

    # Verify task
    task = (
        await db.execute(select(Task).where(Task.id == task_id))
    ).scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")

    query = (
        select(FailureEvent)
        .where(FailureEvent.task_id == task_id)
        .order_by(FailureEvent.detected_at)
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/failures/{failure_id}")
async def get_failure(
    failure_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取单个失败事件详情（含 traceback 和分析结果）。"""
    from app.models.task import FailureEvent

    result = await db.execute(
        select(FailureEvent).where(FailureEvent.id == failure_id)
    )
    failure = result.scalar_one_or_none()
    if not failure:
        raise HTTPException(404, "Failure event not found")
    return failure


@router.get("/files/{file_id}/raw")
async def get_file_raw(
    file_id: str,
    start_line: int = Query(1, ge=1),
    end_line: int = Query(200, ge=1),
    db: AsyncSession = Depends(get_db),
):
    """获取单个日志文件的内容行（按文件内行号分页，带错误标记）。"""
    from app.models.task import LogFile

    log_file = (
        await db.execute(select(LogFile).where(LogFile.id == file_id))
    ).scalar_one_or_none()
    if not log_file:
        raise HTTPException(404, "Log file not found")

    end_line = max(end_line, start_line)
    result = await db.execute(
        select(LogEntry)
        .where(
            LogEntry.log_file_id == file_id,
            LogEntry.file_line_number >= start_line,
            LogEntry.file_line_number <= end_line,
        )
        .order_by(LogEntry.file_line_number)
    )
    lines = [
        {"no": e.file_line_number, "text": e.raw_line, "is_error": e.is_error}
        for e in result.scalars()
    ]

    if not lines:
        task = (
            await db.execute(select(Task).where(Task.id == log_file.task_id))
        ).scalar_one_or_none()
        content = None
        if task and task.source_type == "s3":
            try:
                from app.services.storage.provider_manager import provider_manager
                fc = await provider_manager.read_file(
                    "s3", log_file.file_path, max_bytes=50 * 1024 * 1024
                )
                content = fc.content
            except Exception:
                content = None
        else:
            try:
                from pathlib import Path
                file_path = Path(log_file.file_path)
                if file_path.exists():
                    content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                content = None

        if content is not None:
            if log_file.name.lower().endswith((".html", ".htm")):
                from app.services.log_parser import parse_html_log
                parsed = parse_html_log(content)
                raw_lines = [
                    {"text": e.get("raw_line") or "", "is_error": bool(e.get("is_error"))}
                    for e in parsed
                ]
            else:
                raw_lines = [
                    {"text": text, "is_error": False}
                    for text in content.splitlines()
                ]
            total_lines = len(raw_lines)
            end_line = min(end_line, total_lines)
            lines = [
                {"no": no, "text": line["text"], "is_error": line["is_error"]}
                for no, line in enumerate(raw_lines[start_line - 1:end_line], start_line)
            ]
            return {
                "file_id": file_id,
                "name": log_file.name,
                "total_lines": total_lines,
                "start_line": start_line,
                "end_line": end_line,
                "lines": lines,
            }

    return {
        "file_id": file_id,
        "name": log_file.name,
        "total_lines": log_file.total_lines,
        "start_line": start_line,
        "end_line": end_line,
        "lines": lines,
    }


@router.get("/{task_id}/raw")
async def get_raw_log(
    task_id: str,
    start_line: int = Query(1, ge=1),
    end_line: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """获取任务的原始日志行（分页）。"""
    from pathlib import Path

    task = (
        await db.execute(select(Task).where(Task.id == task_id))
    ).scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")

    if task.log_file_path:
        file_path = Path(task.log_file_path)
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            total_lines = len(lines)
            end_line = min(end_line, total_lines)
            content = "".join(lines[start_line - 1 : end_line])

            return {
                "total_lines": total_lines,
                "start_line": start_line,
                "end_line": end_line,
                "content": content,
            }

    # S3 tasks do not have a local Task.log_file_path. Show the parsed task-wide
    # LogEntry stream instead of failing the tab.
    total_lines = await db.scalar(
        select(func.count()).select_from(LogEntry).where(LogEntry.task_id == task_id)
    ) or 0
    if total_lines == 0:
        return {
            "total_lines": 0,
            "start_line": 1,
            "end_line": 0,
            "content": "",
        }

    end_line = min(end_line, total_lines)
    result = await db.execute(
        select(LogEntry.raw_line)
        .where(LogEntry.task_id == task_id)
        .order_by(LogEntry.line_number)
        .offset(start_line - 1)
        .limit(end_line - start_line + 1)
    )
    content = "\n".join(result.scalars())

    return {
        "total_lines": total_lines,
        "start_line": start_line,
        "end_line": end_line,
        "content": content,
    }
