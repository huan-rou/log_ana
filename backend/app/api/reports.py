"""Current-state reports grouped by test version and test purpose."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.database import get_db
from app.models.mapping import TaskReference, TestPurpose, TestVersion
from app.models.task import Task
from app.models.user import User
from app.services.overall_report import build_current_report

router = APIRouter()


async def _completed_version_tasks(db: AsyncSession, version: TestVersion, task_ids=None):
    query = select(Task).where(
        Task.package_version == version.version_name,
        Task.source_type == "s3",
        Task.status == "completed",
    )
    if task_ids is not None:
        query = query.where(Task.automation_task_id.in_(task_ids))
    return (await db.execute(query)).scalars().all()


@router.get("/versions/{version_id}")
async def version_report(
    version_id: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    version = (await db.execute(
        select(TestVersion).where(TestVersion.id == version_id)
    )).scalar_one_or_none()
    if not version:
        raise HTTPException(404, "Version not found")

    tasks = await _completed_version_tasks(db, version)
    report = await build_current_report(db, tasks)
    purposes = (await db.execute(
        select(TestPurpose).where(TestPurpose.version_id == version.id).order_by(TestPurpose.name)
    )).scalars().all()
    purpose_rows = []
    for purpose in purposes:
        refs = (await db.execute(
            select(TaskReference.task_id).where(TaskReference.purpose_id == purpose.id)
        )).scalars().all()
        purpose_tasks = await _completed_version_tasks(db, version, refs)
        purpose_report = await build_current_report(db, purpose_tasks)
        purpose_rows.append({
            "id": purpose.id,
            "name": purpose.name,
            "task_count": purpose_report["tasks"]["total"],
            "failed": purpose_report["results"]["failed"],
            "blocked": purpose_report["results"]["blocked"],
            "analysis_completed": purpose_report["analysis"]["completed"],
            "analysis_subjects": purpose_report["analysis"]["subjects"],
            "review_pending": purpose_report["review"]["pending"],
        })
    report["scope"] = {"type": "version", "id": version.id, "name": version.version_name}
    report["purposes"] = purpose_rows
    return report


@router.get("/purposes/{purpose_id}")
async def purpose_report(
    purpose_id: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    purpose = (await db.execute(
        select(TestPurpose).where(TestPurpose.id == purpose_id)
    )).scalar_one_or_none()
    if not purpose:
        raise HTTPException(404, "Test purpose not found")
    version = (await db.execute(
        select(TestVersion).where(TestVersion.id == purpose.version_id)
    )).scalar_one()
    refs = (await db.execute(
        select(TaskReference.task_id).where(TaskReference.purpose_id == purpose.id)
    )).scalars().all()
    report = await build_current_report(db, await _completed_version_tasks(db, version, refs))
    report["scope"] = {
        "type": "purpose", "id": purpose.id, "name": purpose.name,
        "version_id": version.id, "version_name": version.version_name,
    }
    return report
