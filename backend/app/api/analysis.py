from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy import select, Integer, text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.database import get_db
from app.models.task import Task, AnalysisResult
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


async def _run_pipeline(task_id: str):
    """后台执行完整分析流水线。"""
    from app.database import async_session
    from app.services.log_parser import parse_log_file
    from app.services.failure_detector import detect_failures
    from app.services.rule_executor import classify_failures
    from app.core.audit_logger import audit_logger

    import time as _time
    t0 = _time.monotonic()

    async with async_session() as db:
        await _db_checkpoint(db, task_id, "pipeline-session-open")
        task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
        if not task:
            return

        await audit_logger.pipeline_start(
            task_id,
            source_type=task.source_type,
            parser_type=task.parser_type,
        )

        try:
            # ── Step 1: Parse ──
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
        - total_auto_analyzed: 自动分析过的文件数（有 failure 的）
        - auto_analyzed_pct: 自动分析占比
        - human_reviewed: 已人工审核的文件数（confirmed + overridden）
        - human_overridden: 人工覆盖的文件数
        - remaining_unreviewed: 尚未审核的文件数（仍有 failure 且 pending）
    """
    from app.models.task import LogFile

    # Verify task
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")

    rows = (await db.execute(
        select(LogFile.file_type, LogFile.review_status, LogFile.failure_count)
        .where(LogFile.task_id == task_id)
    )).all()

    testsuite_total = sum(1 for ft, _, _ in rows if ft == "testsuite")
    testcase_total = sum(1 for ft, _, _ in rows if ft == "testcase")
    tasklog_total = sum(1 for ft, _, _ in rows if ft == "task_log")

    auto_analyzed = sum(1 for _, _, fc in rows if fc > 0)
    total_files = len(rows) or 1  # avoid division by zero

    human_reviewed = sum(1 for _, rs, _ in rows if rs in ("confirmed", "overridden"))
    human_overridden = sum(1 for _, rs, _ in rows if rs == "overridden")
    remaining_unreviewed = sum(1 for _, rs, fc in rows if rs == "pending" and fc > 0)

    return {
        "task_id": task_id,
        "task_status": task.status,
        "total_testsuite_files": testsuite_total,
        "total_testcase_files": testcase_total,
        "total_tasklog_files": tasklog_total,
        "total_files": total_files,
        "auto_analyzed": auto_analyzed,
        "auto_analyzed_pct": round(auto_analyzed / total_files * 100, 1) if total_files > 0 else 0,
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

