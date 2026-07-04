from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.models.task import (
    Task,
    FailureEvent,
    AnalysisRule,
    AnalysisResult,
    Category,
    LogEntry,
)
from app.services.rule_registry import rule_registry
from rules.base import RuleContext, BaseRule, RuleResult


async def classify_failures(
    task: Task,
    failures: List[FailureEvent],
    db: AsyncSession,
):
    """对检测到的失败事件执行规则分类。

    Args:
        task: 当前任务
        failures: 失败事件列表
        db: 数据库会话
    """
    # Ensure rules are loaded and synced
    if not rule_registry.get_all():
        await rule_registry.discover()
        await rule_registry.sync_to_db(db)

    # Load related log entries for context
    task_entries = await _load_task_entries(task.id, db)

    # Load enabled rules from DB (sorted by priority)
    result = await db.execute(
        select(AnalysisRule)
        .where(AnalysisRule.enabled == True)
        .order_by(AnalysisRule.priority)
    )
    db_rules = list(result.scalars())

    # Get the "unrecognized" category
    unrec_cat = await _get_or_create_category(db, "无法识别", "未能匹配任何规则的失败事件")

    classified = 0
    unrecognized = 0

    for failure in failures:
        # Build context
        ctx = await _build_context(failure, task_entries, task, db)

        # Evaluate rules
        if settings.rule_execution_mode == "parallel":
            eval_info = await _evaluate_parallel(db_rules, ctx, task.id, failure.id)
        else:
            eval_info = await _evaluate_serial(db_rules, ctx, task.id, failure.id)

        match_item = eval_info.get("match")
        if match_item:
            # Save matched result
            db_rule = match_item["rule"]
            rule_result: RuleResult = match_item["result"]

            ar = AnalysisResult(
                failure_event_id=failure.id,
                log_file_id=failure.log_file_id,
                rule_id=db_rule.id if db_rule else None,
                category_id=(
                    await _get_category_id(db, rule_result.category)
                    if rule_result.category
                    else None
                ),
                confidence=rule_result.confidence,
                evidence=rule_result.evidence,
                extractions=json.dumps(
                    {
                        **rule_result.extractions,
                        **({"line_start": rule_result.line_start,
                            "line_end": rule_result.line_end}
                           if rule_result.line_start is not None else {}),
                    },
                    ensure_ascii=False,
                ),
                is_auto=True,
                is_fallback=False,
            )
            db.add(ar)
            classified += 1

            await _audit_classified(task.id, failure, rule_result.category or "",
                                    rule_result.confidence, rule_result.evidence,
                                    db_rule.rule_id if db_rule else "", is_fallback=False)
        else:
            # Fallback: build evidence that explains WHY no rule matched
            evidence = _build_fallback_evidence(eval_info)
            ar = AnalysisResult(
                failure_event_id=failure.id,
                log_file_id=failure.log_file_id,
                category_id=unrec_cat.id,
                confidence=0.0,
                evidence=evidence,
                is_auto=True,
                is_fallback=True,
            )
            db.add(ar)
            unrecognized += 1

            await _audit_classified(task.id, failure, unrec_cat.name,
                                    0.0, evidence, "", is_fallback=True)

    task.classified_count = classified
    task.unrecognized_count = unrecognized
    await db.flush()

    await _rank_results_per_file(task, db)
    # commit 由上层 _run_pipeline 统一执行


async def _rank_results_per_file(task: Task, db: AsyncSession):
    """按文件聚合分析结果并标记 rank。

    规则：每个日志文件最多 2 条主要错误——
      rank=1 根因（最终结论）、rank=2 次要原因，其余 rank=NULL（仅参考）。
    排序键：规则优先级（小者优先）→ 置信度（高者优先）→ 失败行号（早者优先）。
    仅有 fallback（无法识别）结果的文件，取其一作为 rank=1，保证文件可被审核。
    """
    result = await db.execute(
        select(AnalysisResult, AnalysisRule, FailureEvent)
        .join(FailureEvent, AnalysisResult.failure_event_id == FailureEvent.id)
        .outerjoin(AnalysisRule, AnalysisResult.rule_id == AnalysisRule.id)
        .where(FailureEvent.task_id == task.id)
        .where(AnalysisResult.log_file_id.is_not(None))
    )
    by_file: dict[str, list] = {}
    for ar, rule, fe in result.all():
        by_file.setdefault(ar.log_file_id, []).append((ar, rule, fe))

    for rows in by_file.values():
        for ar, _, _ in rows:
            ar.rank = None
        candidates = [r for r in rows if not r[0].is_fallback]
        if not candidates:
            candidates = rows
        candidates.sort(key=lambda r: (
            r[1].priority if r[1] else 10**9,
            -r[0].confidence,
            r[2].line_start if r[2].line_start is not None else 10**9,
        ))
        for rank, (ar, _, _) in enumerate(candidates[:2], start=1):
            ar.rank = rank

    await db.flush()


async def _build_context(
    failure: FailureEvent,
    task_entries: List[LogEntry],
    task: Task,
    db: AsyncSession,
) -> RuleContext:
    """为失败事件构建 RuleContext。"""
    # Collect nearby log entries (±20 lines)
    failure_line = None
    for entry in task_entries:
        if entry.id == failure.start_entry_id:
            failure_line = entry.line_number
            break

    if failure_line is None:
        # Find by script name match
        for entry in task_entries:
            if entry.script_name and entry.script_name == failure.script_name:
                failure_line = entry.line_number
                break

    nearby_entries = []
    if failure_line:
        ctx_start = max(1, failure_line - 20)
        ctx_end = failure_line + 20
        nearby_entries = [
            e for e in task_entries
            if ctx_start <= e.line_number <= ctx_end
        ]

    # Prepare failure event dict
    fe_dict = {
        "id": failure.id,
        "script_name": failure.script_name,
        "exception_type": failure.exception_type,
        "exception_message": failure.exception_message,
        "traceback": failure.traceback,
        "relevant_log": failure.relevant_log,
        "line_start": failure.line_start,
        "line_end": failure.line_end,
    }

    # Attach source file info (rules may be file-type aware)
    if failure.log_file_id:
        from app.models.task import LogFile
        lf = (await db.execute(
            select(LogFile).where(LogFile.id == failure.log_file_id)
        )).scalar_one_or_none()
        if lf:
            fe_dict["log_file"] = {
                "name": lf.name,
                "file_type": lf.file_type,
                "testcase_name": lf.testcase_name,
            }

    # Prepare log entry dicts
    entry_dicts = [
        {
            "line_number": e.line_number,
            "level": e.level,
            "script_name": e.script_name,
            "message": e.message,
            "raw_line": e.raw_line,
        }
        for e in nearby_entries
    ]

    # Determine workspace path
    workspace_path = str(settings.workspace_dir / task.id)
    Path(workspace_path).mkdir(parents=True, exist_ok=True)

    # Fetch extra files (from file_fetcher)
    from app.services.file_fetcher import FileFetcher
    fetcher = FileFetcher(str(settings.upload_dir / task.id), workspace_path)
    extra_files = await fetcher.fetch_all(nearby_entries)

    return RuleContext(
        failure_event=fe_dict,
        log_entries=entry_dicts,
        traceback=failure.traceback or "",
        workspace_path=workspace_path,
        extra_files=extra_files,
    )


async def _evaluate_serial(
    db_rules: List[AnalysisRule],
    ctx: RuleContext,
    task_id: str,
    failure_id: str,
) -> dict:
    """串行评估规则，首次匹配即返回。

    Returns:
        {"match": {"rule": ..., "result": ...} | None,
         "evaluated": int,           # rules actually tried
         "total": int,               # total enabled rules
         "errors": list[str]}        # "rule_id: message" per crashed rule
    """
    from app.core.audit_logger import audit_logger
    import time as _time

    evaluated = 0
    errors: list[str] = []
    total = len(db_rules)

    for db_rule in db_rules:
        rule_instance = rule_registry.get_instance(db_rule.rule_id)
        if not rule_instance:
            errors.append(f"{db_rule.rule_id}: 规则实例未加载")
            continue
        evaluated += 1
        t_rule = _time.monotonic()
        try:
            result = await rule_instance.evaluate(ctx)
            duration_ms = int((_time.monotonic() - t_rule) * 1000)
            await audit_logger.rule_evaluate(
                task_id, rule_id=db_rule.rule_id, failure_id=failure_id,
                matched=result.matched, category=result.category or "",
                confidence=result.confidence, duration_ms=duration_ms,
            )
            if result.matched:
                return {"match": {"rule": db_rule, "result": result},
                        "evaluated": evaluated, "total": total, "errors": errors}
        except Exception as e:
            duration_ms = int((_time.monotonic() - t_rule) * 1000)
            errors.append(f"{db_rule.rule_id}: {e}")
            await audit_logger.rule_evaluate(
                task_id, rule_id=db_rule.rule_id, failure_id=failure_id,
                matched=False, duration_ms=duration_ms, error=str(e),
            )

    return {"match": None, "evaluated": evaluated, "total": total, "errors": errors}


async def _evaluate_parallel(
    db_rules: List[AnalysisRule],
    ctx: RuleContext,
    task_id: str,
    failure_id: str,
) -> dict:
    """并行评估所有规则，返回最高优先级匹配。

    Returns:
        {"match": {"rule": ..., "result": ...} | None,
         "evaluated": int,           # rules actually tried
         "total": int,               # total enabled rules
         "errors": list[str]}        # "rule_id: message" per crashed rule
    """
    from app.core.audit_logger import audit_logger
    import time as _time

    errors: list[str] = []
    evaluated = 0
    total = len(db_rules)

    async def evaluate_one(db_rule):
        nonlocal evaluated
        rule_instance = rule_registry.get_instance(db_rule.rule_id)
        if not rule_instance:
            errors.append(f"{db_rule.rule_id}: 规则实例未加载")
            return None
        evaluated += 1
        t_rule = _time.monotonic()
        try:
            result = await rule_instance.evaluate(ctx)
            duration_ms = int((_time.monotonic() - t_rule) * 1000)
            await audit_logger.rule_evaluate(
                task_id, rule_id=db_rule.rule_id, failure_id=failure_id,
                matched=result.matched, category=result.category or "",
                confidence=result.confidence, duration_ms=duration_ms,
            )
            if result.matched:
                return {"rule": db_rule, "result": result}
        except Exception as e:
            duration_ms = int((_time.monotonic() - t_rule) * 1000)
            errors.append(f"{db_rule.rule_id}: {e}")
            await audit_logger.rule_evaluate(
                task_id, rule_id=db_rule.rule_id, failure_id=failure_id,
                matched=False, duration_ms=duration_ms, error=str(e),
            )
        return None

    tasks_list = [evaluate_one(r) for r in db_rules]
    results = await asyncio.gather(*tasks_list)
    matches = [r for r in results if r is not None]

    if not matches:
        return {"match": None, "evaluated": evaluated, "total": total, "errors": errors}

    if settings.rule_first_match_wins:
        # Primary: lowest priority (most important), tie-break: highest confidence
        best = min(matches, key=lambda m: (m["rule"].priority, -m["result"].confidence))
        return {"match": best, "evaluated": evaluated, "total": total, "errors": errors}

    # Primary: highest confidence, tie-break: lowest priority (most important rule)
    best = max(matches, key=lambda m: (m["result"].confidence, -m["rule"].priority))
    return {"match": best, "evaluated": evaluated, "total": total, "errors": errors}


def _build_fallback_evidence(eval_info: dict) -> str:
    """根据评估元数据构造描述性证据，说明为什么没有规则匹配。"""
    total = eval_info.get("total", 0)
    evaluated = eval_info.get("evaluated", 0)
    errors = eval_info.get("errors", [])

    if total == 0:
        return "无已启用规则"
    if errors and evaluated == 0:
        return f"全部 {len(errors)} 条规则加载失败: {'; '.join(errors[:3])}"
    if errors:
        detail = "; ".join(errors[:3])
        suffix = "…" if len(errors) > 3 else ""
        return f"已评估 {evaluated}/{total} 条规则，{len(errors)} 条出错 ({detail}{suffix})，其余未匹配"
    return f"已评估 {evaluated} 条规则，均未匹配"


async def _audit_classified(task_id: str, failure, category: str,
                           confidence: float, evidence: str,
                           rule_id: str, *, is_fallback: bool) -> None:
    """记录分类决策审计事件。"""
    from app.core.audit_logger import audit_logger
    exc_type = failure.exception_type if hasattr(failure, "exception_type") else ""
    await audit_logger.failure_classified(
        task_id,
        failure_id=failure.id if hasattr(failure, "id") else "",
        is_fallback=is_fallback,
        category=category,
        confidence=confidence,
        evidence=evidence,
        rule_id=rule_id,
        exception_type=exc_type,
    )


async def _load_task_entries(task_id: str, db: AsyncSession) -> List[LogEntry]:
    result = await db.execute(
        select(LogEntry)
        .where(LogEntry.task_id == task_id)
        .order_by(LogEntry.line_number)
    )
    return list(result.scalars())


async def _get_or_create_category(db: AsyncSession, name: str, description: str) -> Category:
    result = await db.execute(select(Category).where(Category.name == name))
    cat = result.scalar_one_or_none()
    if not cat:
        cat = Category(name=name, description=description)
        db.add(cat)
        await db.flush()
    return cat


async def _get_category_id(db: AsyncSession, name: str) -> str | None:
    """解析类别名为类别 id，支持 "大类/子类" 路径，缺失时自动创建。"""
    if "/" in name:
        parent_name, child_name = (s.strip() for s in name.split("/", 1))
        parent = (await db.execute(
            select(Category).where(Category.name == parent_name,
                                   Category.parent_id.is_(None))
        )).scalar_one_or_none()
        if not parent:
            parent = Category(name=parent_name)
            db.add(parent)
            await db.flush()
        child = (await db.execute(
            select(Category).where(Category.name == child_name,
                                   Category.parent_id == parent.id)
        )).scalar_one_or_none()
        if not child:
            child = Category(name=child_name, parent_id=parent.id)
            db.add(child)
            await db.flush()
        return child.id

    result = await db.execute(select(Category).where(Category.name == name))
    cat = result.scalars().first()
    if not cat:
        cat = Category(name=name)
        db.add(cat)
        await db.flush()
    return cat.id
