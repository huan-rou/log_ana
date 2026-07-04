from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.task import AnalysisResult, Category, Feedback, LogFile, ArchivedReview, HighValueRecord
from app.models.user import User
from app.auth import require_write_review, get_current_user

router = APIRouter()


class ConfirmRequest(BaseModel):
    note: Optional[str] = None


class OverrideRequest(BaseModel):
    category_id: str
    evidence: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    note: Optional[str] = None


async def _get_file(file_id: str, db: AsyncSession) -> LogFile:
    f = (await db.execute(select(LogFile).where(LogFile.id == file_id))).scalar_one_or_none()
    if not f:
        raise HTTPException(404, "Log file not found")
    return f


async def _primary_result(file_id: str, db: AsyncSession) -> Optional[AnalysisResult]:
    return (await db.execute(
        select(AnalysisResult)
        .where(AnalysisResult.log_file_id == file_id, AnalysisResult.rank == 1)
    )).scalars().first()


async def _upsert_feedback(
    db: AsyncSession,
    result: Optional[AnalysisResult],
    *,
    is_correct: bool,
    suggested_category_id: Optional[str] = None,
    comment: Optional[str] = None,
):
    """审核动作同步写入 Feedback，使既有反馈统计/规则改进数据保持可用。"""
    if not result:
        return
    existing = (await db.execute(
        select(Feedback).where(Feedback.analysis_result_id == result.id)
    )).scalar_one_or_none()
    if existing:
        existing.is_correct = is_correct
        existing.suggested_category_id = suggested_category_id
        existing.comment = comment
    else:
        db.add(Feedback(
            analysis_result_id=result.id,
            is_correct=is_correct,
            suggested_category_id=suggested_category_id,
            comment=comment,
        ))


@router.post("/files/{file_id}/confirm")
async def confirm_file(
    file_id: str,
    req: ConfirmRequest,
    _current_user: User = Depends(require_write_review),
    db: AsyncSession = Depends(get_db),
):
    """确认文件的自动分析结论无误。"""
    f = await _get_file(file_id, db)
    f.review_status = "confirmed"
    f.reviewed_at = datetime.utcnow()
    if req.note is not None:
        f.reviewer_note = req.note
    f.override_category_id = None
    f.override_evidence = None
    f.override_line_start = None
    f.override_line_end = None

    await _upsert_feedback(db, await _primary_result(file_id, db),
                           is_correct=True, comment=req.note)
    await db.commit()
    return {"ok": True, "review_status": f.review_status}


@router.post("/files/{file_id}/override")
async def override_file(
    file_id: str,
    req: OverrideRequest,
    _current_user: User = Depends(require_write_review),
    db: AsyncSession = Depends(get_db),
):
    """人工覆盖文件的最终结论（自动结果保留以供对比）。"""
    f = await _get_file(file_id, db)

    cat = (await db.execute(
        select(Category).where(Category.id == req.category_id)
    )).scalar_one_or_none()
    if not cat:
        raise HTTPException(400, "Category not found")

    f.review_status = "overridden"
    f.reviewed_at = datetime.utcnow()
    f.override_category_id = req.category_id
    f.override_evidence = req.evidence
    f.override_line_start = req.line_start
    f.override_line_end = req.line_end
    if req.note is not None:
        f.reviewer_note = req.note

    await _upsert_feedback(db, await _primary_result(file_id, db),
                           is_correct=False,
                           suggested_category_id=req.category_id,
                           comment=req.note)
    await db.commit()
    return {"ok": True, "review_status": f.review_status}


@router.post("/files/{file_id}/reset")
async def reset_file(
    file_id: str,
    _current_user: User = Depends(require_write_review),
    db: AsyncSession = Depends(get_db),
):
    """重置为待审核（清除覆盖信息，保留备注）。"""
    f = await _get_file(file_id, db)
    f.review_status = "pending"
    f.reviewed_at = None
    f.override_category_id = None
    f.override_evidence = None
    f.override_line_start = None
    f.override_line_end = None

    primary = await _primary_result(file_id, db)
    if primary:
        existing = (await db.execute(
            select(Feedback).where(Feedback.analysis_result_id == primary.id)
        )).scalar_one_or_none()
        if existing:
            await db.delete(existing)

    await db.commit()
    return {"ok": True, "review_status": f.review_status}


# ── Overridden list (flat, non-archived only) ──

@router.get("/overridden")
async def list_overridden(
    limit: int = 200,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """列出所有已被覆盖且未归档的文件（平铺，用于人工审核复盘）。"""
    from app.models.task import Task

    archived_sub = select(ArchivedReview.log_file_id)
    query = (
        select(LogFile)
        .where(
            LogFile.review_status == "overridden",
            LogFile.id.not_in(archived_sub),
        )
        .order_by(LogFile.reviewed_at.desc().nulls_last())
        .offset(offset)
        .limit(limit)
    )
    files = list((await db.execute(query)).scalars())

    task_ids = list({f.task_id for f in files})
    tasks_map = {}
    if task_ids:
        t_rows = (await db.execute(
            select(Task).where(Task.id.in_(task_ids))
        )).scalars()
        tasks_map = {t.id: t for t in t_rows}

    file_ids = [f.id for f in files]
    results_map = await _load_file_results_batch(db, file_ids)
    cmap = await _category_map(db)

    out = []
    for f in files:
        rows = results_map.get(f.id, [])
        primary = next((r for r in rows if r[0].rank == 1), None)
        out.append({
            "id": f.id,
            "task_id": f.task_id,
            "task_name": tasks_map.get(f.task_id).name if f.task_id in tasks_map else None,
            "name": f.name,
            "file_type": f.file_type,
            "testcase_name": f.testcase_name,
            "reviewed_at": f.reviewed_at,
            "reviewer_note": f.reviewer_note,
            "review_status": f.review_status,
            "override_category": _category_dict(
                cmap.get(f.override_category_id), cmap
            ) if f.override_category_id else None,
            "override_evidence": f.override_evidence,
            "primary": {
                "category": _category_dict(cmap.get(primary[0].category_id), cmap),
                "confidence": primary[0].confidence,
                "evidence": primary[0].evidence,
                "rule_name": primary[1].name if primary[1] else None,
                "rule_id": primary[1].rule_id if primary[1] else None,
                "line_start": primary[2].line_start if primary[2] else None,
                "line_end": primary[2].line_end if primary[2] else None,
            } if primary else None,
        })
    return out


# ── Archive / Unarchive ──

@router.post("/files/{file_id}/archive")
async def archive_file(
    file_id: str,
    _current_user: User = Depends(require_write_review),
    db: AsyncSession = Depends(get_db),
):
    """归档一条已覆盖的审核记录（从待处理列表移除）。"""
    await _get_file(file_id, db)
    existing = (await db.execute(
        select(ArchivedReview).where(ArchivedReview.log_file_id == file_id)
    )).scalar_one_or_none()
    if not existing:
        db.add(ArchivedReview(log_file_id=file_id))
        await db.commit()
    return {"ok": True}


@router.post("/files/{file_id}/unarchive")
async def unarchive_file(
    file_id: str,
    _current_user: User = Depends(require_write_review),
    db: AsyncSession = Depends(get_db),
):
    """取消归档。"""
    await _get_file(file_id, db)
    existing = (await db.execute(
        select(ArchivedReview).where(ArchivedReview.log_file_id == file_id)
    )).scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.commit()
    return {"ok": True}


# ── Archived list ──

@router.get("/archived")
async def list_archived(
    limit: int = 200,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """列出所有已归档的审核记录。"""
    from app.models.task import Task

    query = (
        select(LogFile, ArchivedReview)
        .join(ArchivedReview, LogFile.id == ArchivedReview.log_file_id)
        .order_by(ArchivedReview.archived_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = list((await db.execute(query)).all())

    task_ids = list({lf.task_id for lf, _ in rows})
    tasks_map = {}
    if task_ids:
        t_rows = (await db.execute(
            select(Task).where(Task.id.in_(task_ids))
        )).scalars()
        tasks_map = {t.id: t for t in t_rows}

    file_ids = [lf.id for lf, _ in rows]
    results_map = await _load_file_results_batch(db, file_ids)
    cmap = await _category_map(db)

    out = []
    for lf, ar in rows:
        rows_r = results_map.get(lf.id, [])
        primary = next((r for r in rows_r if r[0].rank == 1), None)
        out.append({
            "id": lf.id,
            "task_id": lf.task_id,
            "task_name": tasks_map.get(lf.task_id).name if lf.task_id in tasks_map else None,
            "name": lf.name,
            "file_type": lf.file_type,
            "testcase_name": lf.testcase_name,
            "reviewed_at": lf.reviewed_at,
            "reviewer_note": lf.reviewer_note,
            "review_status": lf.review_status,
            "archived_at": ar.archived_at,
            "override_category": _category_dict(
                cmap.get(lf.override_category_id), cmap
            ) if lf.override_category_id else None,
            "override_evidence": lf.override_evidence,
            "primary": {
                "category": _category_dict(cmap.get(primary[0].category_id), cmap),
                "confidence": primary[0].confidence,
                "evidence": primary[0].evidence,
                "rule_name": primary[1].name if primary[1] else None,
                "rule_id": primary[1].rule_id if primary[1] else None,
                "line_start": primary[2].line_start if primary[2] else None,
                "line_end": primary[2].line_end if primary[2] else None,
            } if primary else None,
        })
    return out


# ── High-value ──

class HighValueRequest(BaseModel):
    notes: str


@router.post("/files/{file_id}/high-value")
async def mark_high_value(
    file_id: str,
    req: HighValueRequest,
    _current_user: User = Depends(require_write_review),
    db: AsyncSession = Depends(get_db),
):
    """将一条已覆盖的审核记录标记为高价值信息。"""
    await _get_file(file_id, db)
    existing = (await db.execute(
        select(HighValueRecord).where(HighValueRecord.log_file_id == file_id)
    )).scalar_one_or_none()
    if existing:
        existing.notes = req.notes
        existing.updated_at = datetime.utcnow()
    else:
        db.add(HighValueRecord(
            log_file_id=file_id,
            notes=req.notes,
        ))
    await db.commit()
    return {"ok": True}


@router.get("/high-value")
async def list_high_value(
    limit: int = 200,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """列出所有高价值审核记录。"""
    from app.models.task import Task

    query = (
        select(LogFile, HighValueRecord)
        .join(HighValueRecord, LogFile.id == HighValueRecord.log_file_id)
        .order_by(HighValueRecord.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = list((await db.execute(query)).all())

    task_ids = list({lf.task_id for lf, _ in rows})
    tasks_map = {}
    if task_ids:
        t_rows = (await db.execute(
            select(Task).where(Task.id.in_(task_ids))
        )).scalars()
        tasks_map = {t.id: t for t in t_rows}

    file_ids = [lf.id for lf, _ in rows]
    results_map = await _load_file_results_batch(db, file_ids)
    cmap = await _category_map(db)

    out = []
    for lf, hv in rows:
        rows_r = results_map.get(lf.id, [])
        primary = next((r for r in rows_r if r[0].rank == 1), None)
        out.append({
            "id": lf.id,
            "task_id": lf.task_id,
            "task_name": tasks_map.get(lf.task_id).name if lf.task_id in tasks_map else None,
            "name": lf.name,
            "file_type": lf.file_type,
            "testcase_name": lf.testcase_name,
            "reviewed_at": lf.reviewed_at,
            "reviewer_note": lf.reviewer_note,
            "review_status": lf.review_status,
            "override_category": _category_dict(
                cmap.get(lf.override_category_id), cmap
            ) if lf.override_category_id else None,
            "override_evidence": lf.override_evidence,
            "high_value": {
                "id": hv.id,
                "notes": hv.notes,
                "created_at": hv.created_at,
                "updated_at": hv.updated_at,
            },
            "primary": {
                "category": _category_dict(cmap.get(primary[0].category_id), cmap),
                "confidence": primary[0].confidence,
                "evidence": primary[0].evidence,
                "rule_name": primary[1].name if primary[1] else None,
                "rule_id": primary[1].rule_id if primary[1] else None,
                "line_start": primary[2].line_start if primary[2] else None,
                "line_end": primary[2].line_end if primary[2] else None,
            } if primary else None,
        })
    return out


@router.put("/high-value/{record_id}/notes")
async def update_high_value_notes(
    record_id: str,
    req: HighValueRequest,
    _current_user: User = Depends(require_write_review),
    db: AsyncSession = Depends(get_db),
):
    """修改高价值记录的备注。"""
    hv = (await db.execute(
        select(HighValueRecord).where(HighValueRecord.id == record_id)
    )).scalar_one_or_none()
    if not hv:
        raise HTTPException(404, "High-value record not found")
    hv.notes = req.notes
    hv.updated_at = datetime.utcnow()
    await db.commit()
    return {"ok": True}


# ── Shared helpers ──

async def _category_map(db: AsyncSession) -> dict:
    """一次性加载全部类别。"""
    cats = (await db.execute(select(Category))).scalars().all()
    return {c.id: c for c in cats}


def _category_dict(cat, cmap: dict) -> Optional[dict]:
    if not cat:
        return None
    parent = cmap.get(cat.parent_id) if cat.parent_id else None
    return {
        "id": cat.id,
        "name": cat.name,
        "parent_id": cat.parent_id,
        "parent_name": parent.name if parent else None,
    }


async def _load_file_results_batch(db: AsyncSession, file_ids: list[str]) -> dict[str, list]:
    """加载多个文件的分析结果（含规则与失败事件），按文件分组。"""
    from app.models.task import FailureEvent, AnalysisResult as AR, AnalysisRule

    if not file_ids:
        return {}
    result = await db.execute(
        select(AR, AnalysisRule, FailureEvent)
        .join(FailureEvent, AR.failure_event_id == FailureEvent.id)
        .outerjoin(AnalysisRule, AR.rule_id == AnalysisRule.id)
        .where(AR.log_file_id.in_(file_ids))
    )
    by_file: dict[str, list] = {}
    for ar, rule, fe in result.all():
        by_file.setdefault(ar.log_file_id, []).append((ar, rule, fe))
    return by_file
