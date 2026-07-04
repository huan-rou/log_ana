from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from pathlib import Path
import json
import shutil

from app.database import get_db
from app.models.task import Task, Category
from app.config import settings
from app.auth import require_start_task

router = APIRouter()


@router.get("/categories")
async def list_categories(db: AsyncSession = Depends(get_db)):
    """获取分类类别树（两级：大类 → 子类）。"""
    result = await db.execute(select(Category).order_by(Category.created_at))
    cats = list(result.scalars())
    children_map: dict = {}
    for c in cats:
        if c.parent_id:
            children_map.setdefault(c.parent_id, []).append(c)
    return [
        {
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "children": [
                {"id": ch.id, "name": ch.name, "description": ch.description}
                for ch in children_map.get(c.id, [])
            ],
        }
        for c in cats if not c.parent_id
    ]


@router.post("/categories")
async def create_category(
    name: str = Form(...),
    description: Optional[str] = Form(None),
    parent_id: Optional[str] = Form(None),
    _current_user=Depends(require_start_task),
    db: AsyncSession = Depends(get_db),
):
    """创建新分类类别（parent_id 非空时创建子类）。"""
    if parent_id:
        parent = (await db.execute(
            select(Category).where(Category.id == parent_id)
        )).scalar_one_or_none()
        if not parent:
            raise HTTPException(400, "Parent category not found")
        if parent.parent_id:
            raise HTTPException(400, "仅支持两级分类：父类必须是大类")
    cat = Category(name=name, description=description, parent_id=parent_id)
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return cat


@router.get("/")
async def list_tasks(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """获取任务列表。"""
    query = select(Task).order_by(Task.created_at.desc())
    if status:
        query = query.where(Task.status == status)
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{task_id}")
async def get_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """获取单个任务详情。"""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")
    return task


@router.post("/")
async def create_task(
    name: str = Form(...),
    source_type: str = Form("upload"),
    parser_type: str = Form("text"),
    log_format_pattern: Optional[str] = Form(None),
    # S3 params
    bucket: Optional[str] = Form(None),
    prefix: Optional[str] = Form(None),
    package_version: Optional[str] = Form(None),
    automation_task_id: Optional[str] = Form(None),
    node_id: Optional[str] = Form(None),
    task_block_id: Optional[str] = Form(None),
    # Purpose mapping
    purpose_id: Optional[str] = Form(None),
    # Upload params
    file: UploadFile = File(None),
    _current_user=Depends(require_start_task),
    db: AsyncSession = Depends(get_db),
):
    """创建新任务。

    source_type=upload: 上传本地日志文件，存入 data/uploads/<id>/
    source_type=s3:     指定 S3 路径参数，直接从 S3 读取日志
    purpose_id:         传入后自动展开该测试目的下所有关联的 S3 task_id
    """
    # ── Purpose expansion ──
    if purpose_id:
        from app.models.mapping import TestPurpose, TaskReference, TestVersion
        purpose = (await db.execute(
            select(TestPurpose).where(TestPurpose.id == purpose_id)
        )).scalar_one_or_none()
        if not purpose:
            raise HTTPException(404, "测试目的不存在")
        refs = (await db.execute(
            select(TaskReference).where(TaskReference.purpose_id == purpose_id)
                .order_by(TaskReference.round_number)
        )).scalars().all()
        if not refs:
            raise HTTPException(400, "测试目的下没有关联的任务 ID")

        ver = (await db.execute(
            select(TestVersion).where(TestVersion.id == purpose.version_id)
        )).scalar_one_or_none()

        created = []
        for ref in refs:
            task = Task(
                name=f"{name} - #{ref.round_number}",
                status="pending",
                source_type="s3",
                parser_type=parser_type,
                log_format_pattern=log_format_pattern,
                bucket=bucket or settings.s3_bucket or None,
                prefix=prefix or settings.s3_prefix or None,
                package_version=ver.version_name if ver else package_version,
                automation_task_id=ref.task_id,
                node_id="*",
                task_block_id="*",
            )
            db.add(task)
            await db.flush()
            created.append({"id": task.id, "name": task.name, "task_id": ref.task_id, "round_number": ref.round_number})
        await db.commit()
        return {"purpose_expanded": True, "purpose_name": purpose.name, "tasks": created}

    if source_type == "s3" and not automation_task_id:
        raise HTTPException(400, "S3 任务必须指定 Task ID")

    # node_id 和 task_block_id 为空时处理 Task ID 下所有内容
    if source_type == "s3" and not node_id:
        node_id = "*"
    if source_type == "s3" and not task_block_id:
        task_block_id = "*"

    task = Task(
        name=name,
        status="pending",
        source_type=source_type,
        parser_type=parser_type,
        log_format_pattern=log_format_pattern,
        bucket=bucket or settings.s3_bucket or None,
        prefix=prefix or settings.s3_prefix or None,
        package_version=package_version,
        automation_task_id=automation_task_id,
        node_id=node_id,
        task_block_id=task_block_id,
    )
    db.add(task)
    await db.flush()

    if source_type == "upload" and file:
        task_dir = Path(settings.upload_dir) / task.id
        task_dir.mkdir(parents=True, exist_ok=True)
        file_path = task_dir / (file.filename or "log.txt")
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        task.log_file_path = str(file_path)

    await db.commit()
    await db.refresh(task)
    return task


@router.delete("/{task_id}")
async def delete_task(task_id: str, _current_user=Depends(require_start_task), db: AsyncSession = Depends(get_db)):
    """删除任务及其关联数据。"""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")

    # Clean up files
    if task.log_file_path:
        task_dir = Path(task.log_file_path).parent
        if task_dir.exists():
            shutil.rmtree(task_dir, ignore_errors=True)

    await db.delete(task)
    await db.commit()
    return {"ok": True}


@router.get("/{task_id}/summary")
async def task_summary(task_id: str, db: AsyncSession = Depends(get_db)):
    """获取任务统计摘要。"""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")

    from app.models.task import FailureEvent, AnalysisResult

    # Count categories
    cat_query = (
        select(AnalysisResult.category_id, func.count(AnalysisResult.id))
        .where(
            AnalysisResult.failure_event_id.in_(
                select(FailureEvent.id).where(FailureEvent.task_id == task_id)
            )
        )
        .group_by(AnalysisResult.category_id)
    )
    cat_result = await db.execute(cat_query)
    category_counts = {row[0]: row[1] for row in cat_result} if cat_result else {}

    return {
        "task": task,
        "total_failures": task.failure_count,
        "classified": task.classified_count,
        "unrecognized": task.unrecognized_count,
        "category_breakdown": category_counts,
    }
