"""Multi-source purpose execution discovery, ingestion and result aggregation."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mapping import TestPurpose, TestVersion
from app.models.purpose_execution import (
    CaseOccurrence,
    ExecutionSuite,
    PurposeExecution,
    TaskBlock,
    TaskSource,
)
from app.models.task import AnalysisResult, Category, LogFile, Task
from app.services import summary_report as sr
from app.services.storage.provider_manager import provider_manager
from app.services.task_tree import parse_task_tree


class ManualExecutionTreeAdapter:
    """Replaceable boundary for retrieving an execution JSON tree.

    The current release deliberately supports manual JSON only. A future adapter
    can use ``external_task_id`` without changing the API or persistence layer.
    """

    async def get_json(self, external_task_id: str, manual_json: Optional[str]) -> str:
        if manual_json and manual_json.strip():
            return manual_json
        raise ValueError("当前尚未接入 JSON 自动查询，请手工输入 JSON")


execution_tree_adapter = ManualExecutionTreeAdapter()


def _normalize(value: Any) -> tuple[str, str]:
    return sr.normalize_status(value)


async def discover_source_blocks(version_name: str, source_task_id: str) -> dict:
    """Expand ``version/task_id/node_id/task_block_id`` without mutating storage."""
    base = f"{version_name.strip('/')}/{source_task_id.strip('/')}"
    blocks: list[dict] = []
    errors: list[str] = []
    order = 0
    try:
        node_entries = await provider_manager.list_dir("s3", base)
    except Exception as exc:
        return {"blocks": [], "errors": [f"{base}: {exc}"]}

    for node in node_entries:
        if not node.is_dir:
            continue
        try:
            block_entries = await provider_manager.list_dir("s3", node.path)
        except Exception as exc:
            errors.append(f"{node.path}: {exc}")
            continue
        for block in block_entries:
            if not block.is_dir:
                continue
            upload_path = f"{block.path.rstrip('/')}/upload"
            blocks.append({
                "node_id": node.name,
                "task_block_id": block.name,
                "upload_path": upload_path,
                "summary_path": f"{upload_path}/metadata/summary_report.yaml",
                "discovery_order": order,
            })
            order += 1
    if not blocks and not errors:
        errors.append(f"{base}: 未发现 node_id/task_block_id")
    return {"blocks": blocks, "errors": errors}


async def preview_execution(
    version: TestVersion, external_task_id: str, manual_json: Optional[str]
) -> dict:
    raw_json = await execution_tree_adapter.get_json(external_task_id, manual_json)
    parsed = parse_task_tree(raw_json)
    sources = []
    block_count = 0
    for index, leaf in enumerate(parsed["leaves"]):
        discovered = await discover_source_blocks(version.version_name, leaf["node_id"])
        block_count += len(discovered["blocks"])
        sources.append({
            "name": leaf["name"],
            "task_id": leaf["node_id"],
            "discovery_order": index,
            **discovered,
        })
    return {
        "external_task_id": external_task_id,
        "raw_json": raw_json,
        "tree": parsed["tree"],
        "leaf_count": len(parsed["leaves"]),
        "block_count": block_count,
        "sources": sources,
        "warnings": [error for source in sources for error in source["errors"]],
    }


async def persist_execution_preview(
    db: AsyncSession,
    purpose: TestPurpose,
    preview: dict,
    note: Optional[str] = None,
) -> tuple[PurposeExecution, Task]:
    rounds = await db.execute(
        select(PurposeExecution.round_number).where(PurposeExecution.purpose_id == purpose.id)
    )
    round_number = max(rounds.scalars().all() or [0]) + 1
    execution = PurposeExecution(
        purpose_id=purpose.id,
        round_number=round_number,
        external_task_id=preview["external_task_id"],
        raw_json=preview["raw_json"],
        note=note,
    )
    db.add(execution)
    await db.flush()

    version = (await db.execute(
        select(TestVersion).where(TestVersion.id == purpose.version_id)
    )).scalar_one()
    task = Task(
        name=f"{purpose.name} - 第 {round_number} 轮",
        status="pending",
        source_type="s3",
        parser_type="html",
        bucket=version.bucket,
        prefix=version.prefix,
        package_version=version.version_name,
        automation_task_id=preview["external_task_id"],
        node_id="*",
        task_block_id="*",
        purpose_execution_id=execution.id,
    )
    db.add(task)

    for source_data in preview["sources"]:
        errors = source_data.get("errors") or []
        source = TaskSource(
            execution_id=execution.id,
            name=source_data["name"],
            source_task_id=source_data["task_id"],
            discovery_order=source_data["discovery_order"],
            status="pending" if source_data["blocks"] else "failed",
            error_message="; ".join(errors) or None,
        )
        db.add(source)
        await db.flush()
        for block_data in source_data["blocks"]:
            db.add(TaskBlock(source_id=source.id, **block_data))
    await db.commit()
    await db.refresh(execution)
    await db.refresh(task)
    return execution, task


async def _read_strict_summary(block: TaskBlock) -> tuple[Optional[dict], str, Optional[str]]:
    try:
        fc = await provider_manager.read_file("s3", block.summary_path, max_bytes=2 * 1024 * 1024)
        import yaml
        document = yaml.safe_load(fc.content) if fc.content else None
    except FileNotFoundError as exc:
        return None, "missing_summary", str(exc)
    except Exception as exc:
        return None, "invalid_summary", str(exc)
    if not isinstance(document, dict) or not isinstance(document.get("testsuites"), list):
        return None, "invalid_summary", "summary_report.yaml 缺少 testsuites 列表"
    suites = document["testsuites"]
    if len(suites) != 1:
        return None, "multiple_suites" if len(suites) > 1 else "invalid_summary", (
            f"每个任务块必须且只能包含一个 testsuite，实际为 {len(suites)}"
        )
    if not isinstance(suites[0], dict):
        return None, "invalid_summary", "testsuites 中的唯一元素必须是对象"
    return suites[0], "ready", None


async def _scan_block_logs(
    task: Task, block: TaskBlock, occurrences: list[CaseOccurrence], db: AsyncSession
) -> list[dict]:
    """Create LogFile rows and return parsed entry dictionaries for one block."""
    from app.services.log_parser import _create_log_file, _mark_blocked, _parse_content

    targets: list[dict] = []

    async def safe_list(path: str):
        try:
            return await provider_manager.list_dir("s3", path)
        except Exception:
            return []

    suite_dir = f"{block.upload_path}/artifacts/testsuite"
    for entry in await safe_list(suite_dir):
        if entry.is_file and entry.name.lower().endswith((".html", ".htm")):
            targets.append({"entry": entry, "type": "testsuite", "case_name": None, "dir": suite_dir})

    case_root = f"{block.upload_path}/artifacts/testcases"
    for case_dir in await safe_list(case_root):
        if case_dir.is_file:
            continue
        main_dir = f"{case_dir.path.rstrip('/')}/main"
        for entry in await safe_list(main_dir):
            if entry.is_file and entry.name.lower().endswith((".html", ".htm")):
                targets.append({"entry": entry, "type": "testcase", "case_name": case_dir.name, "dir": main_dir})

    parsed_entries: list[dict] = []
    occurrence_by_key: dict[str, list[CaseOccurrence]] = defaultdict(list)
    for occurrence in occurrences:
        for key in (occurrence.case_id, occurrence.case_name):
            if key:
                occurrence_by_key[str(key).lower()].append(occurrence)

    for target in targets:
        entry = target["entry"]
        occurrence = None
        if target["type"] == "testcase":
            candidates = occurrence_by_key.get(str(target["case_name"]).lower(), [])
            if not candidates:
                candidates = occurrence_by_key.get(sr.stem(entry.name), [])
            occurrence = next((item for item in candidates if item.log_file_id is None), None)
        try:
            log_file = await _create_log_file(
                task, db=db,
                name=entry.name,
                path=entry.path,
                source_dir=target["dir"],
                file_type=target["type"],
                testcase_name=target["case_name"],
            )
            if occurrence:
                occurrence.log_file_id = log_file.id
                if occurrence.normalized_status == "blocked":
                    await _mark_blocked(task, log_file, {
                        "fail_detail": occurrence.fail_detail,
                    }, db)
                    continue
            fc = await provider_manager.read_file("s3", entry.path, max_bytes=10 * 1024 * 1024)
            if fc.content:
                items = _parse_content(
                    task, fc.content, start_line=len(parsed_entries), log_file=log_file, force_html=True
                )
                parsed_entries.extend(items)
        except Exception:
            continue
    return parsed_entries


async def run_execution_pipeline(task: Task, db: AsyncSession) -> str:
    """Run all sources and return the terminal Task status."""
    execution = (await db.execute(
        select(PurposeExecution).where(PurposeExecution.id == task.purpose_execution_id)
    )).scalar_one()
    sources = (await db.execute(
        select(TaskSource).where(TaskSource.execution_id == execution.id).order_by(TaskSource.discovery_order)
    )).scalars().all()
    blocks = (await db.execute(
        select(TaskBlock).where(TaskBlock.source_id.in_([s.id for s in sources] or [""]))
        .order_by(TaskBlock.discovery_order)
    )).scalars().all()

    all_entries: list[dict] = []
    valid_blocks = 0
    warning_count = 0
    occurrence_total = 0
    for block in blocks:
        suite_data, block_status, error = await _read_strict_summary(block)
        block.status = block_status
        block.error_message = error
        occurrences: list[CaseOccurrence] = []
        if suite_data is not None:
            statuses = Counter()
            cases = [item for item in (suite_data.get("testcases") or []) if isinstance(item, dict)]
            suite_display, suite_status = _normalize(suite_data.get("result"))
            suite = ExecutionSuite(
                task_block_id=block.id,
                suite_id=str(suite_data.get("id")) if suite_data.get("id") is not None else None,
                name=suite_data.get("desc") or suite_data.get("name") or suite_data.get("id"),
                raw_result=suite_display,
                normalized_status=suite_status,
                start_time=str(suite_data.get("start_time")) if suite_data.get("start_time") is not None else None,
                end_time=str(suite_data.get("end_time")) if suite_data.get("end_time") is not None else None,
                fail_detail=str(suite_data.get("fail_detail") or "") or None,
                total_count=len(cases),
            )
            db.add(suite)
            await db.flush()
            for index, case in enumerate(cases):
                display, normalized = _normalize(case.get("result"))
                statuses[normalized] += 1
                occurrence = CaseOccurrence(
                    task_block_id=block.id,
                    suite_id=suite.id,
                    case_id=str(case.get("id") or case.get("desc") or f"unknown-{index + 1}"),
                    case_name=case.get("desc") or case.get("id"),
                    raw_result=display,
                    normalized_status=normalized,
                    start_time=str(case.get("start_time")) if case.get("start_time") is not None else None,
                    end_time=str(case.get("end_time")) if case.get("end_time") is not None else None,
                    fail_detail=str(case.get("fail_detail") or "") or None,
                    discovery_order=index,
                )
                db.add(occurrence)
                occurrences.append(occurrence)
            suite.success_count = statuses["success"]
            suite.failed_count = statuses["failed"]
            suite.blocked_count = statuses["blocked"]
            suite.unknown_count = statuses["unknown"]
            occurrence_total += len(occurrences)
            valid_blocks += 1
            if suite.unknown_count:
                warning_count += 1
                block.error_message = f"{suite.unknown_count} 个用例包含未知状态"
            await db.flush()
        else:
            warning_count += 1

        all_entries.extend(await _scan_block_logs(task, block, occurrences, db))

    from app.services.log_parser import _insert_entries
    from app.services.failure_detector import detect_failures
    from app.services.rule_executor import classify_failures

    if all_entries:
        await _insert_entries(task, db, all_entries)
        failures = await detect_failures(task, db)
        await classify_failures(task, failures, db)
    from app.models.task import FailureEvent
    task.failure_count = (await db.execute(
        select(func.count(FailureEvent.id)).where(FailureEvent.task_id == task.id)
    )).scalar() or 0
    task.total_testcases = occurrence_total

    blocks_by_source: dict[str, list[TaskBlock]] = defaultdict(list)
    for block in blocks:
        blocks_by_source[block.source_id].append(block)
    for source in sources:
        source_blocks = blocks_by_source.get(source.id, [])
        good = sum(block.status == "ready" for block in source_blocks)
        bad = len(source_blocks) - good
        if good and (bad or source.error_message):
            source.status = "completed_with_warnings"
        elif good:
            source.status = "completed"
        else:
            source.status = "failed"
        if source.status != "completed":
            warning_count += 1

    if valid_blocks == 0:
        terminal_status = "failed"
    elif warning_count or valid_blocks < len(blocks):
        terminal_status = "completed_with_warnings"
    else:
        terminal_status = "completed"

    warning_messages = [
        message
        for message in (
            [source.error_message for source in sources]
            + [block.error_message for block in blocks]
        )
        if message
    ]
    task.error_message = "; ".join(dict.fromkeys(warning_messages)) or None
    return terminal_status


def _parse_end_time(value: Optional[str]) -> float:
    if not value:
        return float("-inf")
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt).timestamp()
            except ValueError:
                pass
    return float("-inf")


async def _category_names(db: AsyncSession) -> dict[str, str]:
    rows = (await db.execute(select(Category))).scalars().all()
    by_id = {row.id: row for row in rows}
    result = {}
    for row in rows:
        parent = by_id.get(row.parent_id) if row.parent_id else None
        result[row.id] = f"{parent.name} / {row.name}" if parent else row.name
    return result


async def _root_cause(db: AsyncSession, occurrence: CaseOccurrence, categories: dict[str, str]) -> Optional[str]:
    log_file = occurrence.log_file
    if not log_file:
        return "测试套阻塞" if occurrence.normalized_status == "blocked" else None
    if log_file.review_status == "overridden" and log_file.override_category_id:
        return categories.get(log_file.override_category_id, "未识别")
    primary = (await db.execute(
        select(AnalysisResult).where(
            AnalysisResult.log_file_id == log_file.id,
            AnalysisResult.rank == 1,
        )
    )).scalar_one_or_none()
    return categories.get(primary.category_id, "未识别") if primary else None


async def load_purpose_result_context(db: AsyncSession, execution_id: str):
    execution = (await db.execute(
        select(PurposeExecution).where(PurposeExecution.id == execution_id)
    )).scalar_one_or_none()
    if not execution:
        return None
    executions = (await db.execute(
        select(PurposeExecution).where(PurposeExecution.purpose_id == execution.purpose_id)
        .order_by(PurposeExecution.round_number)
    )).scalars().all()
    execution_ids = [item.id for item in executions]
    sources = (await db.execute(
        select(TaskSource).where(TaskSource.execution_id.in_(execution_ids or [""]))
        .order_by(TaskSource.discovery_order)
    )).scalars().all()
    blocks = (await db.execute(
        select(TaskBlock).where(TaskBlock.source_id.in_([item.id for item in sources] or [""]))
        .order_by(TaskBlock.discovery_order)
    )).scalars().all()
    suites = (await db.execute(
        select(ExecutionSuite).where(ExecutionSuite.task_block_id.in_([item.id for item in blocks] or [""]))
    )).scalars().all()
    occurrences = (await db.execute(
        select(CaseOccurrence).where(CaseOccurrence.task_block_id.in_([item.id for item in blocks] or [""]))
    )).scalars().all()
    tasks = (await db.execute(
        select(Task).where(Task.purpose_execution_id.in_(execution_ids or [""]))
    )).scalars().all()
    return execution, executions, sources, blocks, suites, occurrences, tasks


async def suite_rows(db: AsyncSession, execution_id: str) -> list[dict]:
    context = await load_purpose_result_context(db, execution_id)
    if not context:
        return []
    _, executions, sources, blocks, suites, _, tasks = context
    execution_by_id = {item.id: item for item in executions}
    source_by_id = {item.id: item for item in sources}
    suite_by_block = {item.task_block_id: item for item in suites}
    task_by_execution = {item.purpose_execution_id: item for item in tasks}
    rows = []
    ordered_blocks = sorted(blocks, key=lambda item: (
        execution_by_id[source_by_id[item.source_id].execution_id].round_number,
        source_by_id[item.source_id].discovery_order,
        item.discovery_order,
    ))
    for block in ordered_blocks:
        source = source_by_id[block.source_id]
        execution = execution_by_id[source.execution_id]
        task = task_by_execution.get(execution.id)
        suite = suite_by_block.get(block.id)
        log_files = []
        if task:
            all_logs = (await db.execute(select(LogFile).where(LogFile.task_id == task.id))).scalars().all()
            log_files = [item for item in all_logs if item.file_path.startswith(block.upload_path)]
        total = suite.total_count if suite else 0
        blocked = suite.blocked_count if suite else 0
        rows.append({
            "execution_id": execution.id,
            "task_id": task.id if task else None,
            "round_number": execution.round_number,
            "feature": source.name,
            "source_task_id": source.source_task_id,
            "node_id": block.node_id,
            "task_block_id": block.task_block_id,
            "block_status": block.status,
            "anomaly": block.error_message,
            "suite_id": suite.suite_id if suite else None,
            "suite_name": suite.name if suite else None,
            "suite_result": suite.raw_result if suite else None,
            "suite_normalized_status": suite.normalized_status if suite else None,
            "success": suite.success_count if suite else 0,
            "failed": suite.failed_count if suite else 0,
            "blocked": blocked,
            "unknown": suite.unknown_count if suite else 0,
            "total": total,
            "suite_blocked": total > 0 and blocked == total,
            "environment": None,
            "logs": [{"id": item.id, "name": item.name, "file_type": item.file_type} for item in log_files],
        })
    return rows


async def testcase_rows(db: AsyncSession, execution_id: str) -> list[dict]:
    context = await load_purpose_result_context(db, execution_id)
    if not context:
        return []
    _, executions, sources, blocks, suites, occurrences, _ = context
    execution_by_id = {item.id: item for item in executions}
    source_by_id = {item.id: item for item in sources}
    block_by_id = {item.id: item for item in blocks}
    suite_by_id = {item.id: item for item in suites}
    categories = await _category_names(db)
    groups: dict[str, list[CaseOccurrence]] = defaultdict(list)
    for occurrence in occurrences:
        groups[occurrence.case_id].append(occurrence)

    def meta(item: CaseOccurrence):
        block = block_by_id[item.task_block_id]
        source = source_by_id[block.source_id]
        execution = execution_by_id[source.execution_id]
        return execution, source, block, suite_by_id.get(item.suite_id)

    rows = []
    for case_id, items in groups.items():
        first = min(items, key=lambda item: (
            meta(item)[0].round_number,
            meta(item)[1].discovery_order,
            meta(item)[2].discovery_order,
            item.discovery_order,
        ))
        latest = max(items, key=lambda item: (
            meta(item)[0].round_number,
            _parse_end_time(item.end_time),
            meta(item)[1].discovery_order,
            meta(item)[2].discovery_order,
            item.discovery_order,
        ))
        _, first_source, _, _ = meta(first)
        latest_execution, _, latest_block, latest_suite = meta(latest)
        rows.append({
            "case_id": case_id,
            "first_feature": first_source.name,
            "last_suite": latest_suite.name if latest_suite else None,
            "execution_count": len(items),
            "last_result": latest.raw_result,
            "last_normalized_status": latest.normalized_status,
            "final_root_cause": await _root_cause(db, latest, categories),
            "review_status": latest.log_file.review_status if latest.log_file else None,
            "latest_occurrence_id": latest.id,
            "latest_round": latest_execution.round_number,
            "latest_task_block": latest_block.task_block_id,
            "log_file_id": latest.log_file_id,
        })
    return sorted(rows, key=lambda item: item["case_id"])


async def testcase_history(db: AsyncSession, execution_id: str, case_id: str) -> list[dict]:
    context = await load_purpose_result_context(db, execution_id)
    if not context:
        return []
    _, executions, sources, blocks, suites, occurrences, _ = context
    execution_by_id = {item.id: item for item in executions}
    source_by_id = {item.id: item for item in sources}
    block_by_id = {item.id: item for item in blocks}
    suite_by_id = {item.id: item for item in suites}
    categories = await _category_names(db)
    result = []
    ordered_occurrences = sorted(occurrences, key=lambda item: (
        execution_by_id[source_by_id[block_by_id[item.task_block_id].source_id].execution_id].round_number,
        _parse_end_time(item.end_time),
        source_by_id[block_by_id[item.task_block_id].source_id].discovery_order,
        block_by_id[item.task_block_id].discovery_order,
        item.discovery_order,
    ))
    for item in ordered_occurrences:
        if item.case_id != case_id:
            continue
        block = block_by_id[item.task_block_id]
        source = source_by_id[block.source_id]
        execution = execution_by_id[source.execution_id]
        suite = suite_by_id.get(item.suite_id)
        result.append({
            "occurrence_id": item.id,
            "round_number": execution.round_number,
            "end_time": item.end_time,
            "feature": source.name,
            "suite": suite.name if suite else None,
            "task_block_id": block.task_block_id,
            "raw_result": item.raw_result,
            "normalized_status": item.normalized_status,
            "analysis_conclusion": await _root_cause(db, item, categories),
            "review_status": item.log_file.review_status if item.log_file else None,
            "log_file_id": item.log_file_id,
        })
    return result
