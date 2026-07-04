from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, Integer
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.database import get_db
from app.models.task import AnalysisResult, Feedback
from app.auth import require_write_review

router = APIRouter()


class FeedbackRequest(BaseModel):
    analysis_result_id: str
    is_correct: Optional[bool] = None
    suggested_category_id: Optional[str] = None
    comment: Optional[str] = None


@router.post("/")
async def submit_feedback(
    req: FeedbackRequest,
    _current_user=Depends(require_write_review),
    db: AsyncSession = Depends(get_db),
):
    """提交分析结果的质量反馈。"""
    # Verify result exists
    result = (
        await db.execute(select(AnalysisResult).where(AnalysisResult.id == req.analysis_result_id))
    ).scalar_one_or_none()
    if not result:
        raise HTTPException(404, "Analysis result not found")

    # Upsert feedback
    existing = (
        await db.execute(
            select(Feedback).where(Feedback.analysis_result_id == req.analysis_result_id)
        )
    ).scalar_one_or_none()

    if existing:
        existing.is_correct = req.is_correct
        existing.suggested_category_id = req.suggested_category_id
        existing.comment = req.comment
    else:
        fb = Feedback(
            analysis_result_id=req.analysis_result_id,
            is_correct=req.is_correct,
            suggested_category_id=req.suggested_category_id,
            comment=req.comment,
        )
        db.add(fb)

    await db.commit()
    return {"ok": True}


@router.get("/{task_id}/stats")
async def feedback_stats(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取任务的反馈统计。"""
    from app.models.task import FailureEvent
    from sqlalchemy import func

    subquery = (
        select(AnalysisResult.id)
        .where(
            AnalysisResult.failure_event_id.in_(
                select(FailureEvent.id).where(FailureEvent.task_id == task_id)
            )
        )
        .subquery()
    )
    query = (
        select(
            func.count(Feedback.id).label("total"),
            func.sum(Feedback.is_correct.cast(Integer)).label("correct"),
            func.sum((Feedback.is_correct == False).cast(Integer)).label("incorrect"),
        )
        .where(Feedback.analysis_result_id.in_(select(subquery.c.id)))
    )
    result = await db.execute(query)
    row = result.one()
    total = row[0] or 0
    correct = row[1] or 0
    incorrect = row[2] or 0

    return {
        "total": total,
        "correct": correct,
        "incorrect": incorrect,
        "accuracy": (correct / total * 100) if total > 0 else 0,
        "pending": max(0, (await _count_total_results(task_id, db)) - total),
    }


async def _count_total_results(task_id: str, db: AsyncSession) -> int:
    from app.models.task import FailureEvent
    from sqlalchemy import func

    subquery = (
        select(AnalysisResult.id)
        .where(
            AnalysisResult.failure_event_id.in_(
                select(FailureEvent.id).where(FailureEvent.task_id == task_id)
            )
        )
    )
    result = await db.execute(
        select(func.count()).select_from(subquery.subquery())
    )
    return result.scalar() or 0


@router.get("/list")
async def list_feedback(
    task_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """获取反馈列表。"""
    query = select(Feedback)

    if task_id:
        from app.models.task import FailureEvent
        subquery = (
            select(AnalysisResult.id)
            .where(
                AnalysisResult.failure_event_id.in_(
                    select(FailureEvent.id).where(FailureEvent.task_id == task_id)
                )
            )
        )
        query = query.where(Feedback.analysis_result_id.in_(select(subquery.subquery())))

    query = query.order_by(Feedback.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()
