"""Purpose execution API for multi-source, round-aware analysis."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_start_task
from app.database import get_db
from app.models.mapping import TestPurpose, TestVersion
from app.models.purpose_execution import PurposeExecution, TaskSource
from app.models.task import Task
from app.services.purpose_execution import (
    persist_execution_preview,
    preview_execution,
    suite_rows,
    testcase_history,
    testcase_rows,
)

router = APIRouter()


class ExecutionPreviewRequest(BaseModel):
    purpose_id: str
    external_task_id: str = Field(..., min_length=1)
    json_text: Optional[str] = Field(None, alias="json")

    model_config = {"populate_by_name": True}


class ExecutionCreateRequest(ExecutionPreviewRequest):
    note: Optional[str] = None


async def _purpose_and_version(db: AsyncSession, purpose_id: str):
    purpose = (await db.execute(
        select(TestPurpose).where(TestPurpose.id == purpose_id)
    )).scalar_one_or_none()
    if not purpose:
        raise HTTPException(404, "测试目的不存在")
    version = (await db.execute(
        select(TestVersion).where(TestVersion.id == purpose.version_id)
    )).scalar_one()
    return purpose, version


@router.post("/preview")
async def preview_purpose_execution(
    req: ExecutionPreviewRequest,
    _current_user=Depends(require_start_task),
    db: AsyncSession = Depends(get_db),
):
    _, version = await _purpose_and_version(db, req.purpose_id)
    try:
        preview = await preview_execution(version, req.external_task_id, req.json_text)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {key: value for key, value in preview.items() if key != "raw_json"}


@router.post("")
async def create_purpose_execution(
    req: ExecutionCreateRequest,
    _current_user=Depends(require_start_task),
    db: AsyncSession = Depends(get_db),
):
    purpose, version = await _purpose_and_version(db, req.purpose_id)
    try:
        preview = await preview_execution(version, req.external_task_id, req.json_text)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    execution, task = await persist_execution_preview(db, purpose, preview, req.note)
    return {
        "id": execution.id,
        "purpose_id": execution.purpose_id,
        "round_number": execution.round_number,
        "external_task_id": execution.external_task_id,
        "task_id": task.id,
        "task_status": task.status,
        "leaf_count": preview["leaf_count"],
        "block_count": preview["block_count"],
        "warnings": preview["warnings"],
    }


async def _execution_summary(db: AsyncSession, execution: PurposeExecution) -> dict:
    task = (await db.execute(
        select(Task).where(Task.purpose_execution_id == execution.id)
    )).scalar_one_or_none()
    sources = (await db.execute(
        select(TaskSource).where(TaskSource.execution_id == execution.id)
    )).scalars().all()
    return {
        "id": execution.id,
        "purpose_id": execution.purpose_id,
        "round_number": execution.round_number,
        "external_task_id": execution.external_task_id,
        "note": execution.note,
        "created_at": execution.created_at,
        "task_id": task.id if task else None,
        "status": task.status if task else "missing_task",
        "source_count": len(sources),
        "sources": [{
            "id": source.id,
            "name": source.name,
            "task_id": source.source_task_id,
            "status": source.status,
            "error_message": source.error_message,
            "block_count": len(source.blocks or []),
        } for source in sources],
    }


@router.get("")
async def list_purpose_executions(
    purpose_id: Optional[str] = None,
    status: Optional[str] = None,
    feature: Optional[str] = None,
    suite: Optional[str] = None,
    case_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(PurposeExecution).order_by(PurposeExecution.created_at.desc())
    if purpose_id:
        query = query.where(PurposeExecution.purpose_id == purpose_id)
    executions = (await db.execute(query)).scalars().all()
    result = []
    for execution in executions:
        item = await _execution_summary(db, execution)
        if status and item["status"] != status:
            continue
        if feature and not any(feature.lower() in source["name"].lower() for source in item["sources"]):
            continue
        if suite or case_id:
            suites = await suite_rows(db, execution.id)
            cases = await testcase_rows(db, execution.id)
            if suite and not any(suite.lower() in str(row.get("suite_name") or "").lower() for row in suites):
                continue
            if case_id and not any(case_id.lower() in row["case_id"].lower() for row in cases):
                continue
        result.append(item)
    return result


@router.get("/{execution_id}")
async def get_purpose_execution(execution_id: str, db: AsyncSession = Depends(get_db)):
    execution = (await db.execute(
        select(PurposeExecution).where(PurposeExecution.id == execution_id)
    )).scalar_one_or_none()
    if not execution:
        raise HTTPException(404, "目的执行轮次不存在")
    item = await _execution_summary(db, execution)
    purpose = (await db.execute(
        select(TestPurpose).where(TestPurpose.id == execution.purpose_id)
    )).scalar_one()
    version = (await db.execute(
        select(TestVersion).where(TestVersion.id == purpose.version_id)
    )).scalar_one()
    item.update({
        "purpose_name": purpose.name,
        "version_id": version.id,
        "version_name": version.version_name,
    })
    return item


@router.get("/{execution_id}/suites")
async def get_execution_suites(
    execution_id: str,
    status: Optional[str] = None,
    feature: Optional[str] = None,
    suite: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    rows = await suite_rows(db, execution_id)
    exists = (await db.execute(
        select(PurposeExecution.id).where(PurposeExecution.id == execution_id)
    )).scalar_one_or_none()
    if not exists:
        raise HTTPException(404, "目的执行轮次不存在")
    if status:
        rows = [
            row for row in rows
            if row["block_status"] == status or row.get("suite_normalized_status") == status
        ]
    if feature:
        rows = [row for row in rows if feature.lower() in row["feature"].lower()]
    if suite:
        rows = [row for row in rows if suite.lower() in str(row.get("suite_name") or "").lower()]
    return rows


@router.get("/{execution_id}/testcases")
async def get_execution_testcases(
    execution_id: str,
    status: Optional[str] = None,
    feature: Optional[str] = None,
    suite: Optional[str] = None,
    case_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    rows = await testcase_rows(db, execution_id)
    if status:
        rows = [row for row in rows if row["last_normalized_status"] == status]
    if feature:
        rows = [row for row in rows if feature.lower() in row["first_feature"].lower()]
    if suite:
        rows = [row for row in rows if suite.lower() in str(row.get("last_suite") or "").lower()]
    if case_id:
        rows = [row for row in rows if case_id.lower() in row["case_id"].lower()]
    return rows


@router.get("/{execution_id}/testcase-history")
async def query_execution_testcase_history(
    execution_id: str,
    case_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Query form keeps case IDs containing slashes intact."""
    return await testcase_history(db, execution_id, case_id)


@router.get("/{execution_id}/testcases/{case_id}/history")
async def get_execution_testcase_history(
    execution_id: str,
    case_id: str,
    db: AsyncSession = Depends(get_db),
):
    return await testcase_history(db, execution_id, case_id)
