"""任务树聚合算法（v5）：跨 round 节点聚合 + TestCase 维度聚合 + 单 round TestCase 行。

输入：tree_node_id（来自 round=1 树的某个节点）
输出：聚合后的响应字典
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mapping import TestVersion
from app.models.task import LogFile, Task
from app.models.task_tree import TestTaskNode, TestTaskTree

logger = logging.getLogger("app.services.task_tree_aggregate")


# ── 工具函数 ──


async def resolve_node_subtree_leaf_ids(
    db: AsyncSession, target_node_id: str
) -> List[str]:
    """找 target_node 子树下所有叶子节点的 ID（包括自身）。"""
    # 拿到该节点所在 tree 的所有节点（树形）
    target = (await db.execute(
        select(TestTaskNode).where(TestTaskNode.id == target_node_id)
    )).scalar_one_or_none()
    if not target:
        return []
    # 用 path 前缀匹配（同 tree_id 下）
    target_path = target.path
    rows = (await db.execute(
        select(TestTaskNode).where(
            TestTaskNode.tree_id == target.tree_id,
            TestTaskNode.path.like(f"{target_path}%"),
        )
    )).scalars().all()
    return [n.id for n in rows if n.is_leaf]


async def get_task_logfile_count(db: AsyncSession, task_id: str) -> int:
    """某 Task 的 LogFile 数（含所有 file_type）。"""
    result = await db.execute(
        select(func.count(LogFile.id)).where(LogFile.task_id == task_id)
    )
    return result.scalar() or 0


# ── aggregate_by_name_key（跨 round 节点聚合）──


async def aggregate_by_name_key(
    db: AsyncSession, version_id: str, target_node_db_id: str
) -> dict:
    """跨 round 节点聚合：找同 name_key 的所有节点，计算每个 round 的执行情况。

    Returns:
        {
            "node": { id, name, name_key, path, extra },
            "aggregate": {
                execution_count, latest_round, latest_round_logfile_count,
                latest_round_result, first_round_logfile_count,
                missing_rounds, all_rounds
            }
        }
    """
    target = (await db.execute(
        select(TestTaskNode).where(TestTaskNode.id == target_node_db_id)
    )).scalar_one_or_none()
    if not target:
        return {"error": "node not found"}

    # 找该 version 下所有 name_key 相同的 node（跨所有 round）
    all_nodes = (await db.execute(
        select(TestTaskNode, TestTaskTree)
        .join(TestTaskTree, TestTaskNode.tree_id == TestTaskTree.id)
        .where(
            TestTaskTree.version_id == version_id,
            TestTaskNode.name_key == target.name_key,
        )
        .order_by(TestTaskTree.round_number)
    )).all()

    per_round: List[Dict[str, Any]] = []
    for node, tree in all_nodes:
        task = (await db.execute(
            select(Task).where(Task.tree_node_id == node.id)
        )).scalar_one_or_none()
        logfile_count = await get_task_logfile_count(db, task.id) if task else 0
        per_round.append({
            "round_number": tree.round_number,
            "task_id": task.id if task else None,
            "node_id": node.node_id,
            "node_name": node.name,
            "logfile_count": logfile_count,
            "has_data": logfile_count > 0,
        })

    # 执行次数 = 有数据的 round 数
    execution_count = sum(1 for r in per_round if r["has_data"])
    # 最新一次 = max(round where has_data)
    latest = next(
        (r for r in reversed(per_round) if r["has_data"]),
        None,
    )
    latest_round = latest["round_number"] if latest else None
    missing_rounds = [r["round_number"] for r in per_round if not r["has_data"]]
    first_round = per_round[0] if per_round else None
    first_round_logfile_count = first_round["logfile_count"] if first_round else 0

    logger.debug(
        "[aggregate_by_name_key] version_id=%s name_key=%s rounds=%d "
        "execution_count=%d latest=%s missing=%s",
        version_id, target.name_key, len(per_round), execution_count, latest_round, missing_rounds,
    )

    return {
        "node": {
            "id": target.id,
            "name": target.name,
            "name_key": target.name_key,
            "path": target.path,
            "extra": target.extra,
        },
        "aggregate": {
            "execution_count": execution_count,
            "first_round_logfile_count": first_round_logfile_count,
            "latest_round": latest_round,
            "latest_round_logfile_count": latest["logfile_count"] if latest else 0,
            "latest_round_result": None,  # 简化：暂时不算 summary_report 汇总
            "missing_rounds": missing_rounds,
            "all_rounds": per_round,
        },
    }


# ── aggregate_testcases_by_name_key（跨 round TestCase 聚合）──


async def aggregate_testcases_by_name_key(
    db: AsyncSession, version_id: str, target_node_db_id: str
) -> dict:
    """跨 round 按 testcase_name 聚合（按 LogFile.testcase_name 分组）。"""
    target = (await db.execute(
        select(TestTaskNode).where(TestTaskNode.id == target_node_db_id)
    )).scalar_one_or_none()
    if not target:
        return {"error": "node not found"}

    # 跨 round name_key 相同的 node
    all_nodes = (await db.execute(
        select(TestTaskNode, TestTaskTree)
        .join(TestTaskTree, TestTaskNode.tree_id == TestTaskTree.id)
        .where(
            TestTaskTree.version_id == version_id,
            TestTaskNode.name_key == target.name_key,
        )
        .order_by(TestTaskTree.round_number)
    )).all()

    # 按 (round, testcase_name) 收集 LogFile
    by_testcase: Dict[str, Dict[str, Any]] = {}
    all_round_nums: List[int] = []

    for node, tree in all_nodes:
        all_round_nums.append(tree.round_number)
        task = (await db.execute(
            select(Task).where(Task.tree_node_id == node.id)
        )).scalar_one_or_none()
        if not task:
            continue
        logfiles = (await db.execute(
            select(LogFile).where(
                LogFile.task_id == task.id,
                LogFile.file_type == "testcase",
            ).order_by(LogFile.testcase_name)
        )).scalars().all()

        for lf in logfiles:
            tc_name = lf.testcase_name or lf.name
            entry = by_testcase.setdefault(tc_name, {
                "name": tc_name,
                "rounds": [],
                "latest_lf": None,
                "latest_round": None,
            })
            entry["rounds"].append(tree.round_number)
            # 记录最新 round 的 logfile
            if entry["latest_round"] is None or tree.round_number > entry["latest_round"]:
                entry["latest_round"] = tree.round_number
                entry["latest_lf"] = lf

    # 计算每条 testcase 的统计
    testcases: List[Dict[str, Any]] = []
    for tc_name, data in by_testcase.items():
        rounds = sorted(set(data["rounds"]))
        latest_lf = data["latest_lf"]
        missing = [r for r in all_round_nums if r not in rounds]
        testcases.append({
            "name": tc_name,
            "execution_count": len(rounds),
            "rounds": rounds,
            "latest_round": data["latest_round"],
            "latest_logfile_id": latest_lf.id if latest_lf else None,
            "latest_logfile_status": latest_lf.review_status if latest_lf else None,
            "latest_round_file_count": 1 if latest_lf else 0,
            "missing_rounds": missing,
        })

    # 按 testcase_name 排序
    testcases.sort(key=lambda t: t["name"])

    # 摘要
    total = len(testcases)
    in_all = sum(1 for t in testcases if not t["missing_rounds"])
    missing_some = total - in_all
    missing_in_latest = sum(
        1 for t in testcases
        if t["latest_round"] is not None
        and max(all_round_nums) != t["latest_round"]
    )

    logger.info(
        "[aggregate_testcases] version_id=%s name_key=%s testcases=%d "
        "in_all_rounds=%d missing_some=%d",
        version_id, target.name_key, total, in_all, missing_some,
    )

    return {
        "node": {
            "id": target.id,
            "name": target.name,
            "name_key": target.name_key,
            "path": target.path,
        },
        "testcases": testcases,
        "summary": {
            "total_testcases": total,
            "executed_in_all_rounds": in_all,
            "missing_in_some_round": missing_some,
            "missing_testcases_in_latest": missing_in_latest,
        },
    }


# ── list_testcases_in_round（单 round TestCase 行）──


async def list_testcases_in_round(
    db: AsyncSession, task_id: str, tree_node_id: Optional[str]
) -> dict:
    """单 round 的 TestCase 行（按 LogFile.testcase_name 分组）。

    Args:
        task_id: 当前 Task.id
        tree_node_id: 当前选中的 tree_node_id（用于定位 round；None 时用 task 自身 round）

    Returns:
        { round_number, task_id, testcases: [...], summary }
    """
    # 找 task
    task = (await db.execute(
        select(Task).where(Task.id == task_id)
    )).scalar_one_or_none()
    if not task:
        return {"error": "task not found"}

    # 确定 round
    if tree_node_id:
        node = (await db.execute(
            select(TestTaskNode, TestTaskTree)
            .join(TestTaskTree, TestTaskNode.tree_id == TestTaskTree.id)
            .where(TestTaskNode.id == tree_node_id)
        )).first()
        if node:
            round_number = node[1].round_number
        else:
            round_number = None
    else:
        round_number = None

    # 拉 LogFile（file_type=testcase）
    logfiles = (await db.execute(
        select(LogFile).where(
            LogFile.task_id == task_id,
            LogFile.file_type == "testcase",
        ).order_by(LogFile.testcase_name)
    )).scalars().all()

    testcases: List[Dict[str, Any]] = []
    for lf in logfiles:
        testcases.append({
            "testcase_name": lf.testcase_name or lf.name,
            "logfile": {
                "id": lf.id,
                "name": lf.name,
                "file_path": lf.file_path,
                "total_lines": lf.total_lines,
                "failure_count": lf.failure_count,
                "review_status": lf.review_status,
                "is_overridden": lf.review_status == "overridden",
            },
        })

    with_failure = sum(1 for t in testcases if t["logfile"]["failure_count"] > 0)

    logger.info(
        "[list_testcases_in_round] task_id=%s tree_node_id=%s "
        "testcases=%d with_failure=%d round=%s",
        task_id, tree_node_id, len(testcases), with_failure, round_number,
    )

    return {
        "round_number": round_number,
        "task_id": task_id,
        "testcases": testcases,
        "summary": {
            "total_testcases": len(testcases),
            "with_failure": with_failure,
        },
    }
