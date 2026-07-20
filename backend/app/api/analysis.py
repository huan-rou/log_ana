from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy import select, Integer, text, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from pydantic import BaseModel, Field

from app.database import get_db, async_session
from app.models.task import Task, AnalysisResult, LogEntry, FailureEvent, LogFile
from app.config import settings
from app.auth import require_start_task

router = APIRouter()
logger = logging.getLogger("app.analysis")


async def _db_checkpoint(db: AsyncSession, task_id: str, label: str) -> None:
    try:
        result = await db.execute(text("PRAGMA database_list"))
        logger.warning("[analysis:%s] task=%s database_list=%s", label, task_id, result.fetchall())
        result = await db.execute(text("PRAGMA journal_mode"))
        logger.warning("[analysis:%s] task=%s journal_mode=%s", label, task_id, result.fetchall())
    except Exception as exc:
        logger.exception("[analysis:%s] task=%s db checkpoint failed: %s", label, task_id, exc)


@router.post("/{task_id}/run")
async def run_analysis(
    task_id: str,
    background_tasks: BackgroundTasks,
    _current_user=Depends(require_start_task),
    db: AsyncSession = Depends(get_db),
):
    """触发任务的日志解析和分析（后台执行）。"""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")

    if task.status not in ("pending", "failed"):
        raise HTTPException(400, f"Task is already {task.status}")

    task.status = "parsing"
    await db.commit()

    background_tasks.add_task(_run_pipeline, task_id)
    return {"task_id": task_id, "status": "started"}


class RerunRequest(BaseModel):
    """完整重分析请求。

    preserve_review 默认 False —— 因为整条流水线重跑后，
    旧的人工覆盖 / 确认结论已经对应旧 AnalysisResult，结论可能变了，
    留着会出现「人工说没事但下面 result 不一样」的不一致状态。
    如果用户明确说保留（很了解场景），可选 True。
    """
    preserve_review: bool = Field(False, description="是否保留 LogFile 上的人工覆盖/确认")


class RerunBatchRequest(BaseModel):
    """批量重分析请求。"""
    task_ids: list[str] = Field(..., min_length=1, max_length=200)
    preserve_review: bool = False


class RunBatchRequest(BaseModel):
    """批量启动请求体。"""
    task_ids: list[str] = Field(..., min_length=1, max_length=200)


@router.post("/run_batch")
async def run_analysis_batch(
    req: RunBatchRequest,
    background_tasks: BackgroundTasks,
    _current_user=Depends(require_start_task),
    db: AsyncSession = Depends(get_db),
):
    """批量触发多个任务的后台分析流水线。

    与单端点 run_analysis 等价语义，逐个 task 处理：
      - 不存在 → error
      - 状态非 pending/failed → skipped（已 running/completed）
      - 状态合法 → 改 parsing + add_pipeline（后台）

    返回每个 task_id 的结果明细，前端可用于弹进度面板。
    """
    # 去重保序（避免同一 task 被请求两次）
    seen: set[str] = set()
    deduped_ids: list[str] = []
    for tid in req.task_ids:
        if tid not in seen:
            seen.add(tid)
            deduped_ids.append(tid)

    started: list[str] = []
    skipped: list[dict] = []
    errors: list[dict] = []

    for task_id in deduped_ids:
        task = (await db.execute(
            select(Task).where(Task.id == task_id)
        )).scalar_one_or_none()
        if not task:
            errors.append({"task_id": task_id, "reason": "not_found"})
            continue
        if task.status not in ("pending", "failed"):
            skipped.append({
                "task_id": task_id,
                "name": task.name,
                "status": task.status,
                "reason": f"status is {task.status}, only pending/failed can start",
            })
            continue
        task.status = "parsing"
        started.append(task_id)

    if started:
        await db.commit()
        for tid in started:
            background_tasks.add_task(_run_pipeline, tid)

    logger.info(
        "[run_batch] total=%d started=%d skipped=%d errors=%d",
        len(deduped_ids), len(started), len(skipped), len(errors),
    )
    return {
        "total": len(deduped_ids),
        "started": started,
        "skipped": skipped,
        "errors": errors,
    }


# ════════════════════════════════════════════════════════════════
# v6: 完整重分析（清旧数据 → 重跑 parse/detect/classify）
# ════════════════════════════════════════════════════════════════


async def _reset_task_data(
    db: AsyncSession,
    task_id: str,
    preserve_review: bool = False,
) -> dict:
    """清理 task 旧解析/检测/分类数据，为重分析腾空间。

    删除顺序（外键依赖，最深子表先删）：
      Feedback → AnalysisResult → FailureEvent → LogEntry / TestCase
        → ArchivedReview / HighValueRecord → LogFile

    LogFile 必须删：之前保留是为了"保住 review 状态"，但 log_parser 重跑会再次
    create LogFile（按 file_path 复用），同 task_id 下没有 unique 约束，会留下
    旧+新两份 LogFile row，每个文件在 UI 上被列两次。rerun 必须连同 LogFile 一起清。

    preserve_review 仅影响 ArchivedReview/HighValueRecord：True 保留；False 一并清。
    （LogFile 上的 review_status/override_* 字段无法跨"删 LogFile 重建"保留——
     重跑后底下的 AnalysisResult 都换了，绑死的 review 数据失去意义。）
    """
    from sqlalchemy import delete as sql_delete
    from app.models.task import (
        Task, LogEntry, FailureEvent, AnalysisResult,
        Feedback, LogFile, TestCase, ArchivedReview, HighValueRecord,
    )

    # 1. Feedback（依赖 AnalysisResult）
    fb_del = (await db.execute(
        sql_delete(Feedback).where(
            Feedback.analysis_result_id.in_(
                select(AnalysisResult.id).where(
                    AnalysisResult.failure_event_id.in_(
                        select(FailureEvent.id).where(FailureEvent.task_id == task_id)
                    )
                )
            )
        )
    )).rowcount

    # 2. AnalysisResult（依赖 FailureEvent）
    ar_del = (await db.execute(
        sql_delete(AnalysisResult).where(
            AnalysisResult.failure_event_id.in_(
                select(FailureEvent.id).where(FailureEvent.task_id == task_id)
            )
        )
    )).rowcount

    # 3. FailureEvent（依赖 Task / LogFile）
    fe_del = (await db.execute(
        sql_delete(FailureEvent).where(FailureEvent.task_id == task_id)
    )).rowcount

    # 4. LogEntry（依赖 Task / LogFile）
    le_del = (await db.execute(
        sql_delete(LogEntry).where(LogEntry.task_id == task_id)
    )).rowcount

    # 5. TestCase（清理派生行，failure_event_id 别悬空）
    tc_del = (await db.execute(
        sql_delete(TestCase).where(TestCase.task_id == task_id)
    )).rowcount

    # PurposeExecution derived rows are rebuilt from the immutable raw JSON and
    # summary reports on rerun. Delete occurrences before LogFile because they
    # may reference a logfile that is about to be replaced.
    from app.models.purpose_execution import (
        CaseOccurrence, ExecutionSuite, PurposeExecution, TaskBlock, TaskSource,
    )
    execution_id = (await db.execute(
        select(Task.purpose_execution_id).where(Task.id == task_id)
    )).scalar_one_or_none()
    occurrence_del = 0
    suite_del = 0
    if execution_id:
        source_ids = select(TaskSource.id).where(TaskSource.execution_id == execution_id)
        block_ids = select(TaskBlock.id).where(TaskBlock.source_id.in_(source_ids))
        occurrence_del = (await db.execute(
            sql_delete(CaseOccurrence).where(CaseOccurrence.task_block_id.in_(block_ids))
        )).rowcount
        suite_del = (await db.execute(
            sql_delete(ExecutionSuite).where(ExecutionSuite.task_block_id.in_(block_ids))
        )).rowcount
        await db.execute(
            update(TaskBlock).where(TaskBlock.source_id.in_(source_ids)).values(
                status="pending", error_message=None
            )
        )
        await db.execute(
            update(TaskSource).where(TaskSource.execution_id == execution_id).values(
                status="pending"
            )
        )

    # 6. ArchivedReview / HighValueRecord（依赖 LogFile）—— 必须在删 LogFile 之前
    arch_del = 0
    hvr_del = 0
    if not preserve_review:
        arch_del = (await db.execute(
            sql_delete(ArchivedReview).where(
                ArchivedReview.log_file_id.in_(
                    select(LogFile.id).where(LogFile.task_id == task_id)
                )
            )
        )).rowcount
        hvr_del = (await db.execute(
            sql_delete(HighValueRecord).where(
                HighValueRecord.log_file_id.in_(
                    select(LogFile.id).where(LogFile.task_id == task_id)
                )
            )
        )).rowcount

    # 7. LogFile（最后删——它的 review_status 和 override_* 字段随 row 一起走；
    #    重跑完成后 parse_log_file 会重新 create 新 LogFile row，且 id 全新。
    #    不删 LogFile 是 v6 的 bug：会留下旧+新两份 row，每文件 UI 显示两次。）
    lf_del = (await db.execute(
        sql_delete(LogFile).where(LogFile.task_id == task_id)
    )).rowcount

    counts: dict = {
        "log_entries": le_del,
        "failure_events": fe_del,
        "analysis_results": ar_del,
        "feedback": fb_del,
        "testcases": tc_del,
        "case_occurrences": occurrence_del,
        "execution_suites": suite_del,
        "log_files": lf_del,
        "preserve_review": preserve_review,
    }
    if not preserve_review:
        counts["archived_reviews"] = arch_del
        counts["high_value_records"] = hvr_del
    return counts


@router.post("/{task_id}/rerun")
async def rerun_task(
    task_id: str,
    req: Optional[RerunRequest] = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    _current_user=Depends(require_start_task),
    db: AsyncSession = Depends(get_db),
):
    """完整重跑分析流水线（清旧数据 + 重 parse/detect/classify）。

    适用场景：log_parser / failure_detector / rule 代码改动后，要 catch 全部。

    状态校验：仅 completed/failed 可触发（pending/parsing/analyzing 拒，避免覆盖在跑任务）。

    诊断：reset 后 flush + commit；commit 后用新 session 验证 db 真没残留（防 async 异步
    DELETE 看上去执行但实际未持久化），不一致则报警并拒绝启动 pipeline。
    """
    body = req or RerunRequest()

    task = (await db.execute(
        select(Task).where(Task.id == task_id)
    )).scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status not in ("completed", "completed_with_warnings", "failed"):
        raise HTTPException(
            400,
            f"Task is {task.status}; only completed/failed can be rerun. "
            "正在跑的任务请等完成后重分析。",
        )

    # reset 在 session 1 内完成，发出 DELETE SQL
    counts = await _reset_task_data(db, task.id, preserve_review=body.preserve_review)
    await db.flush()  # 确保 DELETE 进 SQL 但还未 commit

    # 重置 task 统计字段
    task.status = "parsing"
    task.error_message = None
    task.completed_at = None
    task.total_entries = 0
    task.total_testcases = 0
    task.failure_count = 0
    task.classified_count = 0
    task.unrecognized_count = 0

    # commit
    await db.commit()

    # 验证：用新 session 查 DB，确认旧数据真被删（防止 async + sqlite 罕见 race）
    async with async_session() as verify_db:
        le_n = (await verify_db.execute(
            select(func.count(LogEntry.id)).where(LogEntry.task_id == task_id)
        )).scalar()
        fe_n = (await verify_db.execute(
            select(func.count(FailureEvent.id)).where(FailureEvent.task_id == task_id)
        )).scalar()
        ar_n = (await verify_db.execute(
            select(func.count(AnalysisResult.id)).where(
                AnalysisResult.failure_event_id.in_(
                    select(FailureEvent.id).where(FailureEvent.task_id == task_id)
                )
            )
        )).scalar()
        lf_n = (await verify_db.execute(
            select(func.count(LogFile.id)).where(LogFile.task_id == task_id)
        )).scalar()

    leftover = {}
    for label, val in (("log_entries", le_n), ("failure_events", fe_n),
                       ("analysis_results", ar_n), ("log_files", lf_n)):
        if val and val > 0:
            leftover[label] = val

    logger.info(
        "[rerun.reset] task=%s preserve_review=%s counts=%s leftover=%s",
        task.id, body.preserve_review, counts, leftover,
    )

    if leftover:
        logger.error(
            "[rerun.reset] ⚠️ reset failed for task=%s; leftover=%s. "
            "Will NOT start pipeline to avoid duplicate-row bug.",
            task.id, leftover,
        )
        # 恢复 task 状态回 failed 让 user 看到诊断
        task.status = "failed"
        task.error_message = (
            f"rerun reset 验证失败：仍残留旧数据 {leftover}。"
            f"已记录日志；请把后端日志发给开发排查。"
        )
        await db.commit()
        raise HTTPException(
            500,
            {
                "message": "rerun reset 验证失败，仍有残留旧数据",
                "deleted": counts,
                "leftover": leftover,
            },
        )

    background_tasks.add_task(_run_pipeline, task.id)

    return {
        "task_id": task.id,
        "status": "rerunning",
        "preserve_review": body.preserve_review,
        "deleted": counts,
    }


@router.post("/rerun_batch")
async def rerun_batch(
    req: RerunBatchRequest,
    background_tasks: BackgroundTasks,
    _current_user=Depends(require_start_task),
    db: AsyncSession = Depends(get_db),
):
    """批量完整重跑：同 run_batch 语义，每个 task 走 rerun 流程。

    状态校验：仅 completed/failed 可触发。其余状态进 skipped。
    """
    preserve = req.preserve_review
    seen: set[str] = set()
    deduped_ids: list[str] = []
    for tid in req.task_ids:
        if tid not in seen:
            seen.add(tid)
            deduped_ids.append(tid)

    started: list[str] = []
    skipped: list[dict] = []
    errors: list[dict] = []
    deleted_summary: list[dict] = []

    for task_id in deduped_ids:
        task = (await db.execute(
            select(Task).where(Task.id == task_id)
        )).scalar_one_or_none()
        if not task:
            errors.append({"task_id": task_id, "reason": "not_found"})
            continue
        if task.status not in ("completed", "completed_with_warnings", "failed"):
            skipped.append({
                "task_id": task_id,
                "name": task.name,
                "status": task.status,
                "reason": f"status is {task.status}, only completed/failed can be rerun",
            })
            continue
        try:
            counts = await _reset_task_data(db, task_id, preserve_review=preserve)
            task.status = "parsing"
            task.error_message = None
            task.completed_at = None
            task.total_entries = 0
            task.total_testcases = 0
            task.failure_count = 0
            task.classified_count = 0
            task.unrecognized_count = 0
            deleted_summary.append({
                "task_id": task_id,
                "name": task.name,
                "deleted": counts,
            })
            started.append(task_id)
        except Exception as exc:
            errors.append({"task_id": task_id, "reason": f"reset failed: {exc}"})
            logger.exception("[rerun_batch] reset failed task=%s", task_id)

    if started:
        await db.commit()
        for tid in started:
            background_tasks.add_task(_run_pipeline, tid)

    logger.info(
        "[rerun_batch] total=%d started=%d skipped=%d errors=%d",
        len(deduped_ids), len(started), len(skipped), len(errors),
    )
    return {
        "total": len(deduped_ids),
        "started": started,
        "skipped": skipped,
        "errors": errors,
        "deleted": deleted_summary,
        "preserve_review": preserve,
    }


async def _run_pipeline(task_id: str):
    """后台执行完整分析流水线。"""
    from app.database import async_session
    from app.services.log_parser import parse_log_file
    from app.services.failure_detector import detect_failures
    from app.services.rule_executor import classify_failures
    from app.core.audit_logger import REPORT_AUDIT_SCHEMA, audit_logger

    import time as _time
    t0 = _time.monotonic()

    async with async_session() as db:
        await _db_checkpoint(db, task_id, "pipeline-session-open")
        task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
        if not task:
            return

        await audit_logger.reset_task(task_id)
        await audit_logger.pipeline_start(
            task_id,
            source_type=task.source_type,
            parser_type=task.parser_type,
            report_audit_schema=REPORT_AUDIT_SCHEMA,
        )

        try:
            # ── Step 1: Parse ──
            # PurposeExecution tasks aggregate every discovered source/block into
            # this parent task and have their own strict summary ingestion path.
            if task.purpose_execution_id:
                from app.services.purpose_execution import run_execution_pipeline

                task.status = "parsing"
                await db.commit()
                terminal_status = await run_execution_pipeline(task, db)
                task.status = terminal_status
                task.completed_at = datetime.utcnow()
                await db.commit()
                duration_ms = int((_time.monotonic() - t0) * 1000)
                await audit_logger.pipeline_end(
                    task_id, status=terminal_status,
                    total_entries=task.total_entries,
                    failure_count=task.failure_count,
                    classified=task.classified_count,
                    unrecognized=task.unrecognized_count,
                    duration_ms=duration_ms,
                )
                return

            task.status = "parsing"
            await _db_checkpoint(db, task_id, "before-parsing-status-commit")
            await db.commit()
            await _db_checkpoint(db, task_id, "after-parsing-status-commit")

            await audit_logger.step_enter(task_id, step="parsing")
            from app.models.task import LogEntry
            entries = await parse_log_file(task, db)
            await _db_checkpoint(db, task_id, "after-parse-log-file")

            if task.total_entries == 0:
                raise ValueError(
                    "日志解析完成但未提取到任何条目。"
                    "请检查日志文件是否为空或格式是否匹配。"
                )
            await audit_logger.step_exit(task_id, step="parsing",
                                         total_entries=task.total_entries)

            # ── Step 2: Detect failures ──
            task.status = "analyzing"
            await _db_checkpoint(db, task_id, "before-analyzing-status-commit")
            await db.commit()
            await _db_checkpoint(db, task_id, "after-analyzing-status-commit")

            await audit_logger.step_enter(task_id, step="failure_detection")
            failures = await detect_failures(task, db)
            await _db_checkpoint(db, task_id, "after-detect-failures")
            await audit_logger.step_exit(task_id, step="failure_detection",
                                         failure_count=len(failures))

            # ── Step 3: Classify ──
            await audit_logger.step_enter(task_id, step="classification")
            await classify_failures(task, failures, db)
            await _db_checkpoint(db, task_id, "after-classify-failures")
            await audit_logger.step_exit(task_id, step="classification",
                                         classified=task.classified_count,
                                         unrecognized=task.unrecognized_count)

            # ── Done ──
            task.status = "completed"
            task.completed_at = datetime.utcnow()
            await _db_checkpoint(db, task_id, "before-completed-commit")
            await db.commit()
            await _db_checkpoint(db, task_id, "after-completed-commit")

            duration_ms = int((_time.monotonic() - t0) * 1000)
            await audit_logger.pipeline_end(
                task_id, status="completed",
                total_entries=task.total_entries,
                failure_count=task.failure_count,
                classified=task.classified_count,
                unrecognized=task.unrecognized_count,
                duration_ms=duration_ms,
            )

        except Exception as e:
            # 记录失败状态。若当前 session 已损坏（如 SQLite 连接断开），
            # 用新 session 做恢复写入；审计日志始终不依赖 DB 所以不受影响。
            task.status = "failed"
            task.error_message = str(e)[:1000]
            await _db_checkpoint(db, task_id, "exception-before-failed-commit")
            try:
                await db.commit()
                await _db_checkpoint(db, task_id, "exception-after-failed-commit")
            except Exception:
                try:
                    async with async_session() as recovery_db:
                        await _db_checkpoint(recovery_db, task_id, "recovery-session-open")
                        t = (await recovery_db.execute(
                            select(Task).where(Task.id == task_id)
                        )).scalar_one_or_none()
                        if t:
                            t.status = "failed"
                            t.error_message = str(e)[:1000]
                            await recovery_db.commit()
                except Exception:
                    pass  # 最后兜底：审计日志已记录完整 error 字段

            duration_ms = int((_time.monotonic() - t0) * 1000)
            await audit_logger.pipeline_end(
                task_id, status="failed",
                total_entries=task.total_entries,
                failure_count=task.failure_count,
                classified=task.classified_count,
                unrecognized=task.unrecognized_count,
                duration_ms=duration_ms,
                error=str(e)[:500],
            )


async def _category_map(db: AsyncSession) -> dict:
    """一次性加载全部类别，避免序列化时触发懒加载。"""
    from app.models.task import Category
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


def _result_dict(ar, rule, fe, cmap: dict) -> dict:
    return {
        "id": ar.id,
        "rank": ar.rank,
        "category": _category_dict(cmap.get(ar.category_id), cmap),
        "confidence": ar.confidence,
        "evidence": ar.evidence,
        "is_fallback": ar.is_fallback,
        "rule": {
            "rule_id": rule.rule_id,
            "name": rule.name,
            "version": rule.version,
        } if rule else None,
        "line_start": fe.line_start if fe else None,
        "line_end": fe.line_end if fe else None,
        "exception_type": fe.exception_type if fe else None,
        "exception_message": fe.exception_message if fe else None,
        "script_name": fe.script_name if fe else None,
    }


async def _load_file_results(db: AsyncSession, file_ids: list[str]) -> dict[str, list]:
    """加载多个文件的分析结果（含规则与失败事件），按文件分组。"""
    from app.models.task import FailureEvent, AnalysisResult, AnalysisRule

    if not file_ids:
        return {}
    result = await db.execute(
        select(AnalysisResult, AnalysisRule, FailureEvent)
        .join(FailureEvent, AnalysisResult.failure_event_id == FailureEvent.id)
        .outerjoin(AnalysisRule, AnalysisResult.rule_id == AnalysisRule.id)
        .where(AnalysisResult.log_file_id.in_(file_ids))
    )
    by_file: dict[str, list] = {}
    for ar, rule, fe in result.all():
        by_file.setdefault(ar.log_file_id, []).append((ar, rule, fe))
    return by_file


# summary_report.yaml（上传方记录的原始结果元数据）的解析逻辑在
# app/services/summary_report.py，与解析流水线（blocked 跳过）共用。

@router.get("/{task_id}/files")
async def list_analyzed_files(
    task_id: str,
    review_status: Optional[str] = None,
    file_type: Optional[str] = None,
    category_id: Optional[str] = None,
    is_fallback: Optional[bool] = None,
    summary_result: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """获取任务分析过的日志文件列表（每文件一行，含最终结论与审核状态）。"""
    from app.models.task import LogFile

    logger.info(
        "[list_analyzed_files] task_id=%s review_status=%s file_type=%s "
        "category_id=%s is_fallback=%s summary_result=%s",
        task_id, review_status, file_type, category_id, is_fallback, summary_result,
    )

    query = select(LogFile).where(LogFile.task_id == task_id).order_by(LogFile.name)
    if review_status:
        query = query.where(LogFile.review_status == review_status)
    if file_type:
        query = query.where(LogFile.file_type == file_type)

    files = list((await db.execute(query)).scalars())
    results_map = await _load_file_results(db, [f.id for f in files])
    cmap = await _category_map(db)

    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    report_cache: dict = {}

    raw_count = len(files)

    out = []
    for f in files:
        rows = results_map.get(f.id, [])
        primary = next((r for r in rows if r[0].rank == 1), None)
        if f.review_status == "overridden" and f.override_category_id:
            final_category = _category_dict(cmap.get(f.override_category_id), cmap)
        elif primary:
            final_category = _category_dict(cmap.get(primary[0].category_id), cmap)
        else:
            final_category = None

        if category_id and (not final_category or final_category["id"] != category_id):
            continue

        # 按「无法识别」筛选
        if is_fallback is True and primary and not primary[0].is_fallback:
            continue
        if is_fallback is False and primary and primary[0].is_fallback:
            continue

        # 上传方原始结果（summary_report.yaml）：缺失/异常一律 null，不影响接口
        from app.services import summary_report as sr
        summary = None
        try:
            located = sr.summary_report_path(f, task)
            if located:
                provider, report_path = located
                lookup = await sr.load_summary_lookup(provider, report_path, report_cache)
                summary = sr.summary_for_file(f, lookup, report_path)
        except Exception:
            summary = None

        # 按原始结果（summary_report.yaml）筛选
        if summary_result:
            if not summary or summary.get("normalized_status") != summary_result:
                continue

        out.append({
            "summary_report": summary,
            "id": f.id,
            "name": f.name,
            "file_path": f.file_path,
            "file_type": f.file_type,
            "testcase_name": f.testcase_name,
            "total_lines": f.total_lines,
            "failure_count": f.failure_count,
            "review_status": f.review_status,
            "is_overridden": f.review_status == "overridden",
            "final_category": final_category,
            "primary": {
                "confidence": primary[0].confidence,
                "is_fallback": primary[0].is_fallback,
                "rule_name": primary[1].name if primary[1] else None,
                "rule_id": primary[1].rule_id if primary[1] else None,
            } if primary else None,
        })

    logger.info(
        "[list_analyzed_files] task_id=%s raw_count=%d filtered_count=%d",
        task_id, raw_count, len(out),
    )
    return out


@router.get("/files/{file_id}")
async def get_file_detail(
    file_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取单个日志文件的分析详情：根因、次要原因、其他可能原因、覆盖与备注。"""
    from app.models.task import LogFile

    f = (await db.execute(select(LogFile).where(LogFile.id == file_id))).scalar_one_or_none()
    if not f:
        raise HTTPException(404, "Log file not found")

    rows = (await _load_file_results(db, [f.id])).get(f.id, [])
    cmap = await _category_map(db)
    primary = next((r for r in rows if r[0].rank == 1), None)
    secondary = next((r for r in rows if r[0].rank == 2), None)
    others = [r for r in rows if r[0].rank is None]
    others.sort(key=lambda r: (-r[0].confidence,
                               r[2].line_start if r[2] and r[2].line_start is not None else 10**9))

    return {
        "file": {
            "id": f.id,
            "task_id": f.task_id,
            "name": f.name,
            "file_path": f.file_path,
            "source_dir": f.source_dir,
            "file_type": f.file_type,
            "testcase_name": f.testcase_name,
            "total_lines": f.total_lines,
            "failure_count": f.failure_count,
            "review_status": f.review_status,
            "reviewed_at": f.reviewed_at,
        },
        "primary": _result_dict(*primary, cmap) if primary else None,
        "secondary": _result_dict(*secondary, cmap) if secondary else None,
        "others": [_result_dict(*r, cmap) for r in others],
        "override": {
            "category": _category_dict(cmap.get(f.override_category_id), cmap),
            "evidence": f.override_evidence,
            "line_start": f.override_line_start,
            "line_end": f.override_line_end,
        } if f.review_status == "overridden" else None,
        "reviewer_note": f.reviewer_note,
    }


@router.get("/files/{file_id}/related")
async def list_related_files(
    file_id: str,
    db: AsyncSession = Depends(get_db),
):
    """列出与该日志文件相关、但未被解析的其他文件（实时列目录）。

    分组：
      testcase  — 同一用例目录下的其他文件（main/ 其余文件、raw/ 压缩包等）
      testsuite — 测试套目录下的其他文件
      task      — 任务级日志 artifacts/task/
      raw       — 未匹配文件 artifacts/raw/
    """
    from app.models.task import LogFile, Task

    f = (await db.execute(select(LogFile).where(LogFile.id == file_id))).scalar_one_or_none()
    if not f:
        raise HTTPException(404, "Log file not found")

    task = (await db.execute(select(Task).where(Task.id == f.task_id))).scalar_one_or_none()

    related: list[dict] = []

    if task and task.source_type == "s3" and f.source_dir and "/artifacts/" in f.source_dir:
        from app.services.storage.provider_manager import provider_manager

        artifacts_root = f.source_dir.split("/artifacts/")[0] + "/artifacts"

        async def walk(dir_path: str, group: str, depth: int = 0):
            try:
                entries = await provider_manager.list_dir("s3", dir_path)
            except Exception:
                return
            for e in entries:
                if e.is_file:
                    if e.path != f.file_path:
                        related.append({
                            "group": group,
                            "name": e.name,
                            "path": e.path,
                            "size": getattr(e, "size", None),
                            "provider": "s3",
                        })
                elif depth < 2:
                    await walk(e.path, group, depth + 1)

        if f.file_type == "testcase" and f.testcase_name:
            await walk(f"{artifacts_root}/testcases/{f.testcase_name}", "testcase")
        elif f.file_type == "testsuite":
            await walk(f"{artifacts_root}/testsuite", "testsuite")
        await walk(f"{artifacts_root}/task", "task")
        await walk(f"{artifacts_root}/raw", "raw")
    elif task and task.source_type == "upload" and f.source_dir:
        from pathlib import Path
        src = Path(f.source_dir)
        if src.exists():
            for p in src.iterdir():
                if p.is_file() and str(p) != f.file_path:
                    related.append({
                        "group": "task",
                        "name": p.name,
                        "path": str(p),
                        "size": p.stat().st_size,
                        "provider": "local",
                    })

    return related


@router.get("/{task_id}/results")
async def get_results(
    task_id: str,
    category: Optional[str] = None,
    is_fallback: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """获取任务的分析结果列表。"""
    from app.models.task import FailureEvent, AnalysisResult, Category

    query = (
        select(AnalysisResult)
        .join(FailureEvent, AnalysisResult.failure_event_id == FailureEvent.id)
        .where(FailureEvent.task_id == task_id)
    )

    if is_fallback is not None:
        query = query.where(AnalysisResult.is_fallback == is_fallback)
    if category:
        query = query.join(Category, AnalysisResult.category_id == Category.id).where(
            Category.name == category
        )

    query = query.order_by(AnalysisResult.created_at).offset(offset).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/results/{result_id}")
async def get_result_detail(
    result_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取单条分析结果详情（含关联的失败事件和反馈）。"""
    result = (
        await db.execute(select(AnalysisResult).where(AnalysisResult.id == result_id))
    ).scalar_one_or_none()
    if not result:
        raise HTTPException(404, "Analysis result not found")
    return result


@router.get("/{task_id}/dashboard")
async def get_dashboard(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取分析看板数据。"""
    from app.models.task import FailureEvent, AnalysisResult, Feedback
    from sqlalchemy import func

    # Verify task
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")

    # Category distribution
    cat_query = (
        select(AnalysisResult.category_id, func.count(AnalysisResult.id).label("cnt"))
        .where(
            AnalysisResult.failure_event_id.in_(
                select(FailureEvent.id).where(FailureEvent.task_id == task_id)
            )
        )
        .group_by(AnalysisResult.category_id)
    )
    cat_result = await db.execute(cat_query)
    category_distribution = {
        row[0]: row[1] for row in cat_result
    }

    # Feedback stats
    fb_subquery = (
        select(AnalysisResult.id)
        .where(
            AnalysisResult.failure_event_id.in_(
                select(FailureEvent.id).where(FailureEvent.task_id == task_id)
            )
        )
        .subquery()
    )
    fb_query = (
        select(
            func.count(Feedback.id).label("total"),
            func.sum(Feedback.is_correct.cast(Integer)).label("correct"),
        )
        .where(Feedback.analysis_result_id.in_(select(fb_subquery.c.id)))
    )
    fb_result = await db.execute(fb_query)
    fb_row = fb_result.one()
    feedback_total = fb_row[0] or 0
    feedback_correct = fb_row[1] or 0

    # Per-file review progress
    from app.models.task import LogFile
    file_rows = (await db.execute(
        select(LogFile.review_status, LogFile.failure_count)
        .where(LogFile.task_id == task_id)
    )).all()
    files_total = len(file_rows)
    files_failed = sum(1 for _, fc in file_rows if fc > 0)
    files_reviewed = sum(1 for rs, _ in file_rows if rs in ("confirmed", "overridden"))

    return {
        "task_id": task_id,
        "task_status": task.status,
        "files_total": files_total,
        "files_failed": files_failed,
        "files_reviewed": files_reviewed,
        "total_entries": task.total_entries,
        "total_failures": task.failure_count,
        "classified": task.classified_count,
        "unrecognized": task.unrecognized_count,
        "category_distribution": category_distribution,
        "feedback_total": feedback_total,
        "feedback_correct": feedback_correct,
        "feedback_accuracy": (feedback_correct / feedback_total * 100) if feedback_total > 0 else 0,
    }


@router.get("/{task_id}/report")
async def get_report(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取分析报告：按文件类型、审核状态统计。

    Returns:
        - total_testsuite_files: 测试套 .html 文件总数
        - total_testcase_files: 测试用例 .html 文件总数
        - total_auto_analyzed: 有主结论的失败文件数
        - auto_analyzed_pct: 有主结论 / 有失败文件
        - human_reviewed: 已人工审核的失败文件数（confirmed + overridden）
        - human_overridden: 人工覆盖的文件数
        - remaining_unreviewed: 尚未审核的文件数（仍有 failure 且 pending）
    """
    from app.models.task import LogFile

    # Verify task
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")

    files = (await db.execute(
        select(LogFile).where(LogFile.task_id == task_id)
    )).scalars().all()
    file_ids = [item.id for item in files]
    primary_file_ids = set()
    if file_ids:
        primary_file_ids = set((await db.execute(
            select(AnalysisResult.log_file_id).where(
                AnalysisResult.log_file_id.in_(file_ids),
                AnalysisResult.rank == 1,
            )
        )).scalars().all())

    testsuite_total = sum(item.file_type == "testsuite" for item in files)
    testcase_total = sum(item.file_type == "testcase" for item in files)
    tasklog_total = sum(item.file_type == "task_log" for item in files)

    eligible = [item for item in files if item.failure_count > 0]
    auto_analyzed = sum(item.id in primary_file_ids for item in eligible)
    total_files = len(files)

    human_reviewed = sum(item.review_status in ("confirmed", "overridden") for item in eligible)
    human_overridden = sum(item.review_status == "overridden" for item in eligible)
    remaining_unreviewed = sum(item.review_status == "pending" for item in eligible)

    return {
        "task_id": task_id,
        "task_status": task.status,
        "total_testsuite_files": testsuite_total,
        "total_testcase_files": testcase_total,
        "total_tasklog_files": tasklog_total,
        "total_files": total_files,
        "auto_analyzed": auto_analyzed,
        "auto_analyzed_pct": round(auto_analyzed / len(eligible) * 100, 1) if eligible else 0,
        "human_reviewed": human_reviewed,
        "human_overridden": human_overridden,
        "remaining_unreviewed": remaining_unreviewed,
    }


# ════════════════════════════════════════════════════════════════
# v5: 任务树视图 API（按 round + tree_node_id）
# ════════════════════════════════════════════════════════════════

from app.models.mapping import TestVersion
from app.models.task_tree import TestTaskNode, TestTaskTree
from app.services.task_tree_aggregate import (
    aggregate_by_name_key as _aggregate_by_name_key,
    aggregate_testcases_by_name_key as _aggregate_testcases_by_name_key,
    list_testcases_in_round as _list_testcases_in_round,
    resolve_node_subtree_leaf_ids as _resolve_node_subtree_leaf_ids,
)
from app.services.summary_report import build_suite_response as _build_suite_response


# ── 辅助 ──


async def _get_task_or_404(db: AsyncSession, task_id: str) -> Task:
    task = (await db.execute(
        select(Task).where(Task.id == task_id)
    )).scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")
    return task


async def _get_version_for_task(db: AsyncSession, task: Task) -> Optional[TestVersion]:
    """根据 task 找 TestVersion（按 package_version）。"""
    if not task.package_version:
        return None
    return (await db.execute(
        select(TestVersion).where(TestVersion.version_name == task.package_version)
    )).scalar_one_or_none()


async def _build_tree_node_dict(node: TestTaskNode) -> dict:
    return {
        "id": node.id,
        "tree_id": node.tree_id,
        "parent_id": node.parent_id,
        "name": node.name,
        "name_key": node.name_key,
        "node_id": node.node_id,
        "depth": node.depth,
        "path": node.path,
        "is_leaf": node.is_leaf,
        "sort_order": node.sort_order,
        "extra": node.extra,
    }


async def _build_tree_response(tree: TestTaskTree) -> dict:
    nodes = sorted(tree.nodes, key=lambda n: (n.depth, n.sort_order))
    return {
        "id": tree.id,
        "version_id": tree.version_id,
        "round_number": tree.round_number,
        "root_name": tree.root_name,
        "root_id": tree.root_id,
        "note": tree.note,
        "total_nodes": len(nodes),
        "leaf_count": sum(1 for n in nodes if n.is_leaf),
        "nodes": [await _build_tree_node_dict(n) for n in nodes],
        "created_at": tree.created_at,
        "parsed_at": tree.parsed_at,
    }


# ── 端点 ──


@router.get("/{task_id}/trees")
async def list_task_trees(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """列出该 Task 所属 TestVersion 下所有轮次。"""
    task = await _get_task_or_404(db, task_id)
    version = await _get_version_for_task(db, task)
    if not version:
        return []
    rows = (await db.execute(
        select(TestTaskTree)
        .where(TestTaskTree.version_id == version.id)
        .order_by(TestTaskTree.round_number)
    )).scalars().all()
    out = []
    for t in rows:
        out.append({
            "id": t.id,
            "version_id": t.version_id,
            "round_number": t.round_number,
            "root_name": t.root_name,
            "root_id": t.root_id,
            "note": t.note,
            "total_nodes": len(t.nodes) if t.nodes else 0,
            "leaf_count": sum(1 for n in (t.nodes or []) if n.is_leaf),
            "created_at": t.created_at,
            "parsed_at": t.parsed_at,
        })
    return out


@router.get("/{task_id}/tree")
async def get_task_tree(
    task_id: str,
    round: Optional[int] = Query(None, description="轮次号（不传 = 当前 Task 所在 round）"),
    db: AsyncSession = Depends(get_db),
):
    """拉取指定 round 的 JSON 树。

    不传 round：返回当前 Task 所在 round（通过 tree_node_id 找）。
    传 round=0：返回 round=1（兜底）。
    """
    task = await _get_task_or_404(db, task_id)

    if round is None:
        # 用当前 Task 所在 round
        if task.tree_node_id:
            node = (await db.execute(
                select(TestTaskNode, TestTaskTree)
                .join(TestTaskTree, TestTaskNode.tree_id == TestTaskTree.id)
                .where(TestTaskNode.id == task.tree_node_id)
            )).first()
            if node:
                tree = node[1]
                return await _build_tree_response(tree)
        return {"error": "task has no tree_node_id, please specify round"}

    # 显式传 round：找该 version 下该 round 的树
    version = await _get_version_for_task(db, task)
    if not version:
        raise HTTPException(404, "version not found for task")
    tree = (await db.execute(
        select(TestTaskTree).where(
            TestTaskTree.version_id == version.id,
            TestTaskTree.round_number == round,
        )
    )).scalar_one_or_none()
    if not tree:
        raise HTTPException(404, f"round {round} not found")
    return await _build_tree_response(tree)


@router.get("/{task_id}/aggregate")
async def aggregate_node(
    task_id: str,
    tree_node_id: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
):
    """整体视图节点元信息：跨 round 按 name_key 聚合。

    输入：tree_node_id（来自 round=1 树）
    输出：execution_count / latest_round / missing_rounds / all_rounds
    """
    task = await _get_task_or_404(db, task_id)
    version = await _get_version_for_task(db, task)
    if not version:
        raise HTTPException(404, "version not found for task")
    result = await _aggregate_by_name_key(db, version.id, tree_node_id)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/{task_id}/aggregate/testcases")
async def aggregate_testcases(
    task_id: str,
    tree_node_id: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
):
    """整体视图右表：跨 round 按 testcase_name 聚合的 TestCase 行。"""
    task = await _get_task_or_404(db, task_id)
    version = await _get_version_for_task(db, task)
    if not version:
        raise HTTPException(404, "version not found for task")
    return await _aggregate_testcases_by_name_key(db, version.id, tree_node_id)


@router.get("/{task_id}/testcases")
async def list_testcases_for_task(
    task_id: str,
    tree_node_id: Optional[str] = Query(None, description="当前选中的 tree_node_id（可选）"),
    db: AsyncSession = Depends(get_db),
):
    """单轮次视图右表：当前 Task 下 file_type=testcase 的 LogFile，按 testcase_name 分组。"""
    task = await _get_task_or_404(db, task_id)
    return await _list_testcases_in_round(db, task_id, tree_node_id)
