"""Current-state aggregation for version and test-purpose reports."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import AnalysisResult, AnalysisRule, Category, LogFile, Task
from app.models.purpose_execution import CaseOccurrence, PurposeExecution, TaskBlock, TaskSource
from app.models.rule import Rule as RuleMeta, RuleStatus
from app.services import summary_report as sr
import app.core.audit_logger as audit_log_module


@dataclass
class _FileSummary:
    file: LogFile
    task: Task
    summary: dict | None


def _summary_status(record: dict | None) -> str:
    value = str((record or {}).get("display_result") or "").strip().lower()
    return value if value in {"success", "failed", "blocked"} else "unknown"


def _primary_result(log_file: LogFile) -> AnalysisResult | None:
    return next((item for item in log_file.analysis_results if item.rank == 1), None)


def _category_label(category_id: str | None, categories: dict[str, Category]) -> str:
    if not category_id:
        return "Unrecognized"
    category = categories.get(category_id)
    if not category:
        return "Unrecognized"
    parent = categories.get(category.parent_id) if category.parent_id else None
    return f"{parent.name} / {category.name}" if parent else category.name


def _rule_audit_statistics(task_ids: list[str]) -> dict:
    return audit_log_module.audit_logger.collect_rule_statistics(task_ids)


async def _load_file_summaries(
    tasks: list[Task], log_files: list[LogFile]
) -> tuple[list[_FileSummary], dict[tuple[str, str], dict]]:
    """Resolve summary_report records once per source report path."""
    tasks_by_id = {task.id: task for task in tasks}
    report_cache: dict = {}
    lookups: dict[tuple[str, str], dict] = {}
    records: list[_FileSummary] = []

    for log_file in log_files:
        task = tasks_by_id[log_file.task_id]
        summary = None
        located = sr.summary_report_path(log_file, task)
        if located:
            provider, report_path = located
            lookup = await sr.load_summary_lookup(provider, report_path, report_cache)
            if lookup:
                lookups[(task.id, report_path)] = lookup
                summary = sr.summary_for_file(log_file, lookup, report_path)
        records.append(_FileSummary(file=log_file, task=task, summary=summary))
    return records, lookups


def _unique_cases(lookups: dict[tuple[str, str], dict]) -> Iterable[tuple[str, str, dict]]:
    """Yield every YAML testcase once, even though the lookup has multiple keys per case."""
    for (task_id, report_path), lookup in lookups.items():
        seen: set[int] = set()
        for case in lookup.get("cases", {}).values():
            marker = id(case)
            if marker in seen:
                continue
            seen.add(marker)
            yield task_id, report_path, case


async def build_current_report(db: AsyncSession, tasks: list[Task]) -> dict:
    """Build a real-time report from the latest persisted task data.

    Re-analysis replaces a task's detail rows, so this function deliberately has no
    historical state. It always reports the latest successful analysis rows.
    """
    if not tasks:
        return _empty_report()

    task_ids = [task.id for task in tasks]
    log_files = (await db.execute(
        select(LogFile).where(LogFile.task_id.in_(task_ids))
    )).scalars().all()
    result_rows = (await db.execute(
        select(AnalysisResult).where(AnalysisResult.log_file_id.in_([f.id for f in log_files] or [""]))
    )).scalars().all()
    enabled_rules = (await db.execute(
        select(AnalysisRule)
        .outerjoin(RuleMeta, RuleMeta.analysis_rule_id == AnalysisRule.id)
        .where(AnalysisRule.enabled.is_(True))
        .where(
            or_(
                RuleMeta.id.is_(None),
                and_(
                    RuleMeta.analysis_rule_id.is_not(None),
                    RuleMeta.status == RuleStatus.published.value,
                ),
            )
        )
        .order_by(AnalysisRule.name)
    )).scalars().all()
    results_by_file: dict[str, list[AnalysisResult]] = defaultdict(list)
    for result in result_rows:
        if result.log_file_id:
            results_by_file[result.log_file_id].append(result)
    for log_file in log_files:
        # Avoid lazy loading in the aggregation and make the primary-result rule explicit.
        log_file.analysis_results = results_by_file.get(log_file.id, [])

    category_ids = {
        category_id
        for log_file in log_files
        for category_id in (log_file.override_category_id,)
        if category_id
    }
    category_ids.update(result.category_id for result in result_rows if result.category_id)
    category_ids.update(rule.category_id for rule in enabled_rules if rule.category_id)
    categories: dict[str, Category] = {}
    if category_ids:
        initial = (await db.execute(
            select(Category).where(Category.id.in_(category_ids))
        )).scalars().all()
        categories.update({category.id: category for category in initial})
        parent_ids = {category.parent_id for category in initial if category.parent_id}
        if parent_ids:
            parents = (await db.execute(
                select(Category).where(Category.id.in_(parent_ids))
            )).scalars().all()
            categories.update({category.id: category for category in parents})

    file_summaries, lookups = await _load_file_summaries(tasks, log_files)
    report = _empty_report()
    report["tasks"] = {
        "total": len(tasks),
        "completed": sum(task.status in {"completed", "completed_with_warnings"} for task in tasks),
    }
    primary_by_file = {
        log_file.id: primary
        for log_file in log_files
        if (primary := _primary_result(log_file)) is not None
    }
    reviewed_primary_files = [
        log_file for log_file in log_files
        if log_file.id in primary_by_file
        and log_file.review_status in {"confirmed", "overridden"}
    ]
    adopted_files = sum(log_file.review_status == "confirmed" for log_file in reviewed_primary_files)
    report["tool_effectiveness"] = {
        "total_files": len(log_files),
        "analyzed_files": len(primary_by_file),
        "analysis_rate": round(len(primary_by_file) / len(log_files) * 100, 1) if log_files else 0,
        "reviewed_files": len(reviewed_primary_files),
        "adopted_files": adopted_files,
        "adoption_rate": round(adopted_files / len(reviewed_primary_files) * 100, 1)
        if reviewed_primary_files else None,
    }

    # Test execution counts use YAML cases, not log-file count, so testsuite files
    # cannot inflate testcase totals.
    yaml_cases = list(_unique_cases(lookups))
    report["results"]["total"] = len(yaml_cases)
    for _, _, case in yaml_cases:
        report["results"][_summary_status({"display_result": case.get("result")})] += 1

    by_case: dict[tuple[str, str, str], list[_FileSummary]] = defaultdict(list)
    suite_failures: dict[tuple[str, str, str], _FileSummary] = {}
    unmatched_testcase_files: list[_FileSummary] = []

    for item in file_summaries:
        if item.file.file_type == "testsuite" and item.summary:
            if _summary_status(item.summary) == "failed" and item.file.failure_count > 0:
                suite_id = item.summary.get("suite_id")
                if suite_id:
                    suite_failures[(item.task.id, item.summary["source_path"], str(suite_id))] = item
        elif item.file.file_type == "testcase":
            if item.summary and item.summary.get("case_id"):
                key = (item.task.id, item.summary["source_path"], str(item.summary["case_id"]))
                by_case[key].append(item)
            elif item.file.failure_count > 0:
                unmatched_testcase_files.append(item)

    # A failed/blocked YAML case without a testcase log is reportable data loss.
    for task_id, report_path, case in yaml_cases:
        case_id = str(case.get("id") or case.get("desc") or "")
        key = (task_id, report_path, case_id)
        status = _summary_status({"display_result": case.get("result")})
        if status in {"failed", "blocked"} and key not in by_case:
            report["exceptions"]["missing_log"].append({
                "task_id": task_id,
                "testcase": case.get("desc") or case.get("id"),
                "status": status,
            })

    review_file_ids: set[str] = set()
    final_categories: Counter[str] = Counter()
    transitions: Counter[tuple[str, str]] = Counter()

    def add_subject(items: list[_FileSummary], status: str, label: str) -> None:
        primary_items = [(item, _primary_result(item.file)) for item in items]
        primary_items = [(item, result) for item, result in primary_items if result]
        suite_item = None
        if not primary_items:
            first = items[0]
            suite_id = (first.summary or {}).get("suite_id")
            if suite_id:
                suite_item = suite_failures.get((first.task.id, first.summary["source_path"], str(suite_id)))

        has_failure = status in {"failed", "blocked"} or any(
            item.file.failure_count > 0 for item in items
        )
        if not has_failure:
            return
        report["analysis"]["subjects"] += 1
        if primary_items:
            file_item, primary = primary_items[0]
            review_file_ids.add(file_item.file.id)
            report["analysis"]["completed"] += 1
            if primary.is_fallback or not primary.category_id:
                report["analysis"]["fallback"] += 1
                auto_label = "Unrecognized"
            else:
                report["analysis"]["rule_result"] += 1
                auto_label = _category_label(primary.category_id, categories)
            final_label = _category_label(
                file_item.file.override_category_id or primary.category_id, categories
            )
            final_categories[final_label] += 1
            if file_item.file.review_status == "overridden":
                transitions[(auto_label, final_label)] += 1
        elif suite_item:
            review_file_ids.add(suite_item.file.id)
            report["analysis"]["completed"] += 1
            report["analysis"]["suite_failed"] += 1
            final_categories["Testsuite failed"] += 1
        else:
            report["analysis"]["no_conclusion"] += 1
            report["exceptions"]["no_conclusion"].append({
                "task_id": items[0].task.id,
                "testcase": (items[0].summary or {}).get("case_desc") or items[0].file.testcase_name,
                "status": status,
            })

    for items in by_case.values():
        add_subject(items, _summary_status(items[0].summary), "case")
    for item in unmatched_testcase_files:
        add_subject([item], "unknown", "file")

    review_files = {log_file.id: log_file for log_file in log_files if log_file.id in review_file_ids}
    report["review"]["eligible"] = len(review_files)
    for log_file in review_files.values():
        report["review"][log_file.review_status if log_file.review_status in {"pending", "confirmed", "overridden"} else "pending"] += 1

    for item in file_summaries:
        if item.file.file_type == "testcase" and item.summary is None:
            report["data_quality"]["summary_missing"] += 1
    report["data_quality"]["summary_matched"] = sum(
        item.file.file_type == "testcase" and item.summary is not None for item in file_summaries
    )
    report["categories"] = [
        {"name": name, "count": count}
        for name, count in final_categories.most_common()
    ]
    report["category_transitions"] = [
        {"automatic": automatic, "final": final, "count": count}
        for (automatic, final), count in transitions.most_common()
    ]
    audit_statistics = _rule_audit_statistics(task_ids)
    selected_by_rule = Counter(
        result.rule_id for result in primary_by_file.values() if result.rule_id
    )
    rule_statistics = []
    for rule in enabled_rules:
        audit = audit_statistics["rules"].get(rule.rule_id, {})
        evaluations = audit.get("evaluations", 0)
        matches = audit.get("matches", 0)
        selected = selected_by_rule.get(rule.id, 0)
        rule_statistics.append({
            "rule_id": rule.rule_id,
            "name": rule.name,
            "category": _category_label(rule.category_id, categories),
            "selected_count": selected,
            "selected_rate": round(selected / len(primary_by_file) * 100, 1)
            if primary_by_file else 0,
            "evaluation_count": evaluations if audit_statistics["available"] else None,
            "matched_count": matches if audit_statistics["available"] else None,
            "match_rate": (
                round(matches / evaluations * 100, 1) if evaluations else 0
            ) if audit_statistics["available"] else None,
            "error_count": audit.get("errors", 0) if audit_statistics["available"] else None,
        })
    report["rule_audit_status"] = {
        key: audit_statistics[key]
        for key in ("available", "available_task_count", "unavailable_task_count")
    }
    report["rule_statistics"] = rule_statistics
    return report


def _empty_report() -> dict:
    return {
        "tasks": {"total": 0, "completed": 0},
        "results": {"total": 0, "success": 0, "failed": 0, "blocked": 0, "unknown": 0},
        "analysis": {
            "subjects": 0, "completed": 0, "rule_result": 0,
            "suite_failed": 0, "fallback": 0, "no_conclusion": 0,
        },
        "review": {"eligible": 0, "pending": 0, "confirmed": 0, "overridden": 0},
        "tool_effectiveness": {
            "total_files": 0, "analyzed_files": 0, "analysis_rate": 0,
            "reviewed_files": 0, "adopted_files": 0, "adoption_rate": None,
        },
        "data_quality": {"summary_matched": 0, "summary_missing": 0},
        "categories": [],
        "category_transitions": [],
        "rule_audit_status": {
            "available": True, "available_task_count": 0, "unavailable_task_count": 0,
        },
        "rule_statistics": [],
        "exceptions": {"missing_log": [], "no_conclusion": []},
    }


async def build_latest_case_statuses(
    db: AsyncSession,
    legacy_tasks: list[Task],
    purpose_ids: list[str],
) -> dict[str, str]:
    """Merge legacy YAML cases with round-aware occurrences by case_id.

    New execution occurrences override matching legacy cases. Cases omitted from
    a rerun remain in the map with their previous result.
    """
    merged: dict[str, tuple[tuple, str]] = {}
    if legacy_tasks:
        legacy_files = (await db.execute(
            select(LogFile).where(LogFile.task_id.in_([task.id for task in legacy_tasks]))
        )).scalars().all()
        _, lookups = await _load_file_summaries(legacy_tasks, legacy_files)
        created = {task.id: task.created_at for task in legacy_tasks}
        for task_id, _, case in _unique_cases(lookups):
            case_id = str(case.get("id") or case.get("desc") or "")
            if not case_id:
                continue
            key = (0, created.get(task_id) or 0, task_id)
            status = _summary_status({"display_result": case.get("result")})
            if case_id not in merged or key > merged[case_id][0]:
                merged[case_id] = (key, status)

    if purpose_ids:
        rows = (await db.execute(
            select(CaseOccurrence, TaskBlock, TaskSource, PurposeExecution)
            .join(TaskBlock, CaseOccurrence.task_block_id == TaskBlock.id)
            .join(TaskSource, TaskBlock.source_id == TaskSource.id)
            .join(PurposeExecution, TaskSource.execution_id == PurposeExecution.id)
            .where(PurposeExecution.purpose_id.in_(purpose_ids))
        )).all()
        from app.services.purpose_execution import _parse_end_time
        for occurrence, block, _, execution in rows:
            key = (
                1,
                execution.round_number,
                _parse_end_time(occurrence.end_time),
                block.discovery_order,
                occurrence.discovery_order,
            )
            previous = merged.get(occurrence.case_id)
            if previous is None or key > previous[0]:
                merged[occurrence.case_id] = (key, occurrence.normalized_status)
    return {case_id: value[1] for case_id, value in merged.items()}


def apply_latest_case_counts(report: dict, statuses: dict[str, str]) -> None:
    counts = Counter(status if status in {"success", "failed", "blocked"} else "unknown" for status in statuses.values())
    report["results"] = {
        "total": len(statuses),
        "success": counts["success"],
        "failed": counts["failed"],
        "blocked": counts["blocked"],
        "unknown": counts["unknown"],
    }
