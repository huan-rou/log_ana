"""任务映射 API：管理测试版本、测试目的和 S3 任务引用。

接口：
  GET  /api/mapping/versions           — 列出版本
  POST /api/mapping/versions           — 手动创建版本
  GET  /api/mapping/versions/{id}/discover  — 自动发现 S3 task_id 列表
  POST /api/mapping/purposes           — 创建测试目的
  GET  /api/mapping/purposes?version_id=  — 列出某版本下的目的
  PUT  /api/mapping/purposes/{id}      — 编辑目的（追加 task_refs）
  DELETE /api/mapping/purposes/{id}    — 删除目的
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.mapping import TestVersion, TestPurpose, TaskReference
from app.models.user import User
from app.auth import require_admin

router = APIRouter()

# ── Schemas ──

class CreateVersionRequest(BaseModel):
    version_name: str

class TaskRefInput(BaseModel):
    task_id: str
    round_number: int = 1

class CreatePurposeRequest(BaseModel):
    version_id: str
    name: str
    description: Optional[str] = None
    environment: Optional[str] = None
    task_refs: List[TaskRefInput] = []

class UpdatePurposeRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    environment: Optional[str] = None
    task_refs: List[TaskRefInput] = []


# ── Helpers ──

def _purpose_dict(p: TestPurpose) -> dict:
    return {
        "id": p.id,
        "version_id": p.version_id,
        "name": p.name,
        "description": p.description,
        "environment": p.environment,
        "created_at": p.created_at,
        "task_refs": [
            {"id": tr.id, "task_id": tr.task_id, "round_number": tr.round_number}
            for tr in (p.task_refs or [])
        ],
    }


# ── Versions ──

@router.get("/versions")
async def list_versions(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """列出所有测试版本。"""
    rows = (await db.execute(
        select(TestVersion).order_by(TestVersion.created_at.desc())
    )).scalars().all()
    return [
        {"id": v.id, "version_name": v.version_name, "created_at": v.created_at}
        for v in rows
    ]


@router.post("/versions")
async def create_version(
    req: CreateVersionRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """手动创建测试版本。"""
    existing = (await db.execute(
        select(TestVersion).where(TestVersion.version_name == req.version_name)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(400, "版本名称已存在")

    ver = TestVersion(
        version_name=req.version_name,
    )
    db.add(ver)
    await db.commit()
    await db.refresh(ver)
    return {"id": ver.id, "version_name": ver.version_name}


@router.post("/versions/{version_id}/discover")
async def discover_tasks(
    version_id: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """从 S3 自动发现版本下的 task_id 列表。

    扫描 s3://<bucket>/<prefix>/<version_name>/ 下的直接子目录作为 task_id。
    """
    ver = (await db.execute(
        select(TestVersion).where(TestVersion.id == version_id)
    )).scalar_one_or_none()
    if not ver:
        raise HTTPException(404, "版本不存在")

    discovered: list[str] = []
    error = None

    from app.config import settings
    bucket = settings.s3_bucket

    if bucket:
        from app.services.storage.provider_manager import provider_manager

        s3_provider = provider_manager.get("s3")
        if s3_provider:
            # list_dir 内部会通过 _s3_key() 自动拼接 prefix，这里只传版本名即可
            base = ver.version_name
            try:
                entries = await s3_provider.list_dir(base)
                for e in entries:
                    if e.is_dir:
                        discovered.append(e.name)
            except Exception as exc:
                error = str(exc)
        else:
            error = "S3 provider 未配置（请检查 LA_S3_ENABLED / LA_S3_BUCKET / LA_S3_ENDPOINT_URL / LA_S3_ACCESS_KEY / LA_S3_SECRET_KEY）"
    else:
        error = "未配置 S3 Bucket（请在 .env 中设置 LA_S3_BUCKET）"

    return {
        "version_name": ver.version_name,
        "discovered_task_ids": discovered,
        "count": len(discovered),
        "error": error,
    }


# ── Purposes ──

@router.get("/purposes")
async def list_purposes(
    version_id: Optional[str] = Query(None),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """列出测试目的（可按版本过滤）。"""
    query = select(TestPurpose).order_by(TestPurpose.created_at.desc())
    if version_id:
        query = query.where(TestPurpose.version_id == version_id)
    rows = (await db.execute(query)).scalars().all()
    return [_purpose_dict(p) for p in rows]


@router.post("/purposes")
async def create_purpose(
    req: CreatePurposeRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """创建测试目的（含关联的 task_id 列表）。"""
    ver = (await db.execute(
        select(TestVersion).where(TestVersion.id == req.version_id)
    )).scalar_one_or_none()
    if not ver:
        raise HTTPException(404, "版本不存在")

    purpose = TestPurpose(
        version_id=req.version_id,
        name=req.name,
        description=req.description,
        environment=req.environment,
    )
    db.add(purpose)
    await db.flush()

    for tr in req.task_refs:
        db.add(TaskReference(
            purpose_id=purpose.id,
            task_id=tr.task_id,
            round_number=tr.round_number,
        ))

    await db.commit()
    await db.refresh(purpose)
    return _purpose_dict(purpose)


@router.put("/purposes/{purpose_id}")
async def update_purpose(
    purpose_id: str,
    req: UpdatePurposeRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """编辑测试目的：更新基本字段并可追加/替换 task_refs。"""
    p = (await db.execute(
        select(TestPurpose).where(TestPurpose.id == purpose_id)
    )).scalar_one_or_none()
    if not p:
        raise HTTPException(404, "测试目的不存在")

    if req.name is not None:
        p.name = req.name
    if req.description is not None:
        p.description = req.description
    if req.environment is not None:
        p.environment = req.environment

    if req.task_refs:
        # Replace all task_refs (delete old, insert new)
        old_refs = (await db.execute(
            select(TaskReference).where(TaskReference.purpose_id == p.id)
        )).scalars().all()
        for old in old_refs:
            await db.delete(old)
        for tr in req.task_refs:
            db.add(TaskReference(
                purpose_id=p.id,
                task_id=tr.task_id,
                round_number=tr.round_number,
            ))

    await db.commit()
    await db.refresh(p)
    return _purpose_dict(p)


@router.delete("/purposes/{purpose_id}")
async def delete_purpose(
    purpose_id: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除测试目的及其所有 task_refs。"""
    p = (await db.execute(
        select(TestPurpose).where(TestPurpose.id == purpose_id)
    )).scalar_one_or_none()
    if not p:
        raise HTTPException(404, "测试目的不存在")

    # Delete task_refs first
    refs = (await db.execute(
        select(TaskReference).where(TaskReference.purpose_id == p.id)
    )).scalars().all()
    for ref in refs:
        await db.delete(ref)

    await db.delete(p)
    await db.commit()
    return {"ok": True}


# ── Aggregated Stats ──

@router.get("/purposes/{purpose_id}/stats")
async def purpose_stats(
    purpose_id: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """获取测试目的下所有关联任务的聚合统计。"""
    from app.models.task import Task, LogFile

    p = (await db.execute(
        select(TestPurpose).where(TestPurpose.id == purpose_id)
    )).scalar_one_or_none()
    if not p:
        raise HTTPException(404, "测试目的不存在")

    ver = (await db.execute(
        select(TestVersion).where(TestVersion.id == p.version_id)
    )).scalar_one_or_none()

    refs = (await db.execute(
        select(TaskReference).where(TaskReference.purpose_id == purpose_id)
    )).scalars().all()

    task_ids = [r.task_id for r in refs]
    if not task_ids:
        return {"purpose_name": p.name, "version": ver.version_name if ver else "",
                "tasks": [], "total_files": 0, "auto_analyzed": 0, "auto_analyzed_pct": 0,
                "human_reviewed": 0, "human_overridden": 0, "remaining_unreviewed": 0}

    # Find all Tasks matching these task_ids and version
    tasks = (await db.execute(
        select(Task).where(
            Task.automation_task_id.in_(task_ids),
            Task.package_version == ver.version_name if ver else True,
            Task.source_type == "s3",
        )
    )).scalars().all()

    # Aggregate across all matching tasks
    all_files = []
    for task in tasks:
        lf_rows = (await db.execute(
            select(LogFile).where(LogFile.task_id == task.id)
        )).scalars().all()
        all_files.append({
            "task_id": task.id,
            "task_name": task.name,
            "s3_task_id": task.automation_task_id,
            "status": task.status,
            "files": len(lf_rows),
            "failures": task.failure_count,
            "classified": task.classified_count,
            "unrecognized": task.unrecognized_count,
        })

    # Aggregate file-level stats
    total_files = sum(t["files"] for t in all_files)
    file_rows = []
    for task in tasks:
        rows = (await db.execute(
            select(LogFile).where(LogFile.task_id == task.id)
        )).scalars().all()
        file_rows.extend(rows)

    auto_analyzed = sum(1 for f in file_rows if f.failure_count > 0)
    human_reviewed = sum(1 for f in file_rows if f.review_status in ("confirmed", "overridden"))
    human_overridden = sum(1 for f in file_rows if f.review_status == "overridden")
    remaining_unreviewed = sum(1 for f in file_rows if f.review_status == "pending" and f.failure_count > 0)

    testsuite_count = sum(1 for f in file_rows if f.file_type == "testsuite")
    testcase_count = sum(1 for f in file_rows if f.file_type == "testcase")

    return {
        "purpose_name": p.name,
        "version": ver.version_name if ver else "",
        "task_count": len(tasks),
        "tasks": all_files,
        "total_testsuite_files": testsuite_count,
        "total_testcase_files": testcase_count,
        "total_files": total_files or 1,
        "auto_analyzed": auto_analyzed,
        "auto_analyzed_pct": round(auto_analyzed / (total_files or 1) * 100, 1),
        "human_reviewed": human_reviewed,
        "human_overridden": human_overridden,
        "remaining_unreviewed": remaining_unreviewed,
    }
