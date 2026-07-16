"""任务映射 API：管理测试版本、测试目的和 S3 任务引用。

接口：
  GET  /api/mapping/versions           — 列出版本
  POST /api/mapping/versions           — 手动创建版本
  GET  /api/mapping/versions/{id}/discover  — 自动发现 S3 task_id 列表
  POST /api/mapping/purposes           — 创建测试目的
  GET  /api/mapping/purposes?version_id=  — 列出某版本下的目的
  PUT  /api/mapping/purposes/{id}      — 编辑目的（追加 task_refs）
  DELETE /api/mapping/purposes/{id}    — 删除目的
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.mapping import TestVersion, TestPurpose, TaskReference
from app.models.user import User
from app.auth import require_admin

router = APIRouter()

# ── Schemas ──

class CreateVersionRequest(BaseModel):
    version_name: str

class TaskRefInput(BaseModel):
    task_id: str
    round_number: int = 1

class CreatePurposeRequest(BaseModel):
    version_id: str
    name: str
    description: Optional[str] = None
    environment: Optional[str] = None
    task_refs: List[TaskRefInput] = []

class UpdatePurposeRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    environment: Optional[str] = None
    task_refs: List[TaskRefInput] = []


# ── Helpers ──

def _purpose_dict(p: TestPurpose) -> dict:
    return {
        "id": p.id,
        "version_id": p.version_id,
        "name": p.name,
        "description": p.description,
        "environment": p.environment,
        "created_at": p.created_at,
        "task_refs": [
            {"id": tr.id, "task_id": tr.task_id, "round_number": tr.round_number}
            for tr in (p.task_refs or [])
        ],
    }


# ── Versions ──

@router.get("/versions")
async def list_versions(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """列出所有测试版本。"""
    rows = (await db.execute(
        select(TestVersion).order_by(TestVersion.created_at.desc())
    )).scalars().all()
    return [
        {"id": v.id, "version_name": v.version_name, "created_at": v.created_at}
        for v in rows
    ]


@router.post("/versions")
async def create_version(
    req: CreateVersionRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """手动创建测试版本。"""
    existing = (await db.execute(
        select(TestVersion).where(TestVersion.version_name == req.version_name)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(400, "版本名称已存在")

    ver = TestVersion(
        version_name=req.version_name,
    )
    db.add(ver)
    await db.commit()
    await db.refresh(ver)
    return {"id": ver.id, "version_name": ver.version_name}


@router.post("/versions/{version_id}/discover")
async def discover_tasks(
    version_id: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """从 S3 自动发现版本下的 task_id 列表。

    扫描 s3://<bucket>/<prefix>/<version_name>/ 下的直接子目录作为 task_id。
    """
    ver = (await db.execute(
        select(TestVersion).where(TestVersion.id == version_id)
    )).scalar_one_or_none()
    if not ver:
        raise HTTPException(404, "版本不存在")

    discovered: list[str] = []
    error = None

    from app.config import settings
    bucket = settings.s3_bucket

    if bucket:
        from app.services.storage.provider_manager import provider_manager

        s3_provider = provider_manager.get("s3")
        if s3_provider:
            # list_dir 内部会通过 _s3_key() 自动拼接 prefix，这里只传版本名即可
            base = ver.version_name
            try:
                entries = await s3_provider.list_dir(base)
                for e in entries:
                    if e.is_dir:
                        discovered.append(e.name)
            except Exception as exc:
                error = str(exc)
        else:
            error = "S3 provider 未配置（请检查 LA_S3_ENABLED / LA_S3_BUCKET / LA_S3_ENDPOINT_URL / LA_S3_ACCESS_KEY / LA_S3_SECRET_KEY）"
    else:
        error = "未配置 S3 Bucket（请在 .env 中设置 LA_S3_BUCKET）"

    return {
        "version_name": ver.version_name,
        "discovered_task_ids": discovered,
        "count": len(discovered),
        "error": error,
    }


# ── Purposes ──

@router.get("/purposes")
async def list_purposes(
    version_id: Optional[str] = Query(None),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """列出测试目的（可按版本过滤）。"""
    query = select(TestPurpose).order_by(TestPurpose.created_at.desc())
    if version_id:
        query = query.where(TestPurpose.version_id == version_id)
    rows = (await db.execute(query)).scalars().all()
    return [_purpose_dict(p) for p in rows]


@router.post("/purposes")
async def create_purpose(
    req: CreatePurposeRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """创建测试目的（含关联的 task_id 列表）。"""
    ver = (await db.execute(
        select(TestVersion).where(TestVersion.id == req.version_id)
    )).scalar_one_or_none()
    if not ver:
        raise HTTPException(404, "版本不存在")

    purpose = TestPurpose(
        version_id=req.version_id,
        name=req.name,
        description=req.description,
        environment=req.environment,
    )
    db.add(purpose)
    await db.flush()

    for tr in req.task_refs:
        db.add(TaskReference(
            purpose_id=purpose.id,
            task_id=tr.task_id,
            round_number=tr.round_number,
        ))

    await db.commit()
    await db.refresh(purpose)
    return _purpose_dict(purpose)


@router.put("/purposes/{purpose_id}")
async def update_purpose(
    purpose_id: str,
    req: UpdatePurposeRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """编辑测试目的：更新基本字段并可追加/替换 task_refs。"""
    p = (await db.execute(
        select(TestPurpose).where(TestPurpose.id == purpose_id)
    )).scalar_one_or_none()
    if not p:
        raise HTTPException(404, "测试目的不存在")

    if req.name is not None:
        p.name = req.name
    if req.description is not None:
        p.description = req.description
    if req.environment is not None:
        p.environment = req.environment

    if req.task_refs:
        # Replace all task_refs (delete old, insert new)
        old_refs = (await db.execute(
            select(TaskReference).where(TaskReference.purpose_id == p.id)
        )).scalars().all()
        for old in old_refs:
            await db.delete(old)
        for tr in req.task_refs:
            db.add(TaskReference(
                purpose_id=p.id,
                task_id=tr.task_id,
                round_number=tr.round_number,
            ))

    await db.commit()
    await db.refresh(p)
    return _purpose_dict(p)


@router.delete("/purposes/{purpose_id}")
async def delete_purpose(
    purpose_id: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除测试目的及其所有 task_refs。"""
    p = (await db.execute(
        select(TestPurpose).where(TestPurpose.id == purpose_id)
    )).scalar_one_or_none()
    if not p:
        raise HTTPException(404, "测试目的不存在")

    # Delete task_refs first
    refs = (await db.execute(
        select(TaskReference).where(TaskReference.purpose_id == p.id)
    )).scalars().all()
    for ref in refs:
        await db.delete(ref)

    await db.delete(p)
    await db.commit()
    return {"ok": True}


# ── Aggregated Stats ──

@router.get("/purposes/{purpose_id}/stats")
async def purpose_stats(
    purpose_id: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """获取测试目的下所有关联任务的聚合统计。"""
    from app.models.task import Task, LogFile

    p = (await db.execute(
        select(TestPurpose).where(TestPurpose.id == purpose_id)
    )).scalar_one_or_none()
    if not p:
        raise HTTPException(404, "测试目的不存在")

    ver = (await db.execute(
        select(TestVersion).where(TestVersion.id == p.version_id)
    )).scalar_one_or_none()

    refs = (await db.execute(
        select(TaskReference).where(TaskReference.purpose_id == purpose_id)
    )).scalars().all()

    task_ids = [r.task_id for r in refs]
    if not task_ids:
        return {"purpose_name": p.name, "version": ver.version_name if ver else "",
                "tasks": [], "total_files": 0, "auto_analyzed": 0, "auto_analyzed_pct": 0,
                "human_reviewed": 0, "human_overridden": 0, "remaining_unreviewed": 0}

    # Find all Tasks matching these task_ids and version
    tasks = (await db.execute(
        select(Task).where(
            Task.automation_task_id.in_(task_ids),
            Task.package_version == ver.version_name if ver else True,
            Task.source_type == "s3",
        )
    )).scalars().all()

    # Aggregate across all matching tasks
    all_files = []
    for task in tasks:
        lf_rows = (await db.execute(
            select(LogFile).where(LogFile.task_id == task.id)
        )).scalars().all()
        all_files.append({
            "task_id": task.id,
            "task_name": task.name,
            "s3_task_id": task.automation_task_id,
            "status": task.status,
            "files": len(lf_rows),
            "failures": task.failure_count,
            "classified": task.classified_count,
            "unrecognized": task.unrecognized_count,
        })

    # Aggregate file-level stats
    total_files = sum(t["files"] for t in all_files)
    file_rows = []
    for task in tasks:
        rows = (await db.execute(
            select(LogFile).where(LogFile.task_id == task.id)
        )).scalars().all()
        file_rows.extend(rows)

    auto_analyzed = sum(1 for f in file_rows if f.failure_count > 0)
    human_reviewed = sum(1 for f in file_rows if f.review_status in ("confirmed", "overridden"))
    human_overridden = sum(1 for f in file_rows if f.review_status == "overridden")
    remaining_unreviewed = sum(1 for f in file_rows if f.review_status == "pending" and f.failure_count > 0)

    testsuite_count = sum(1 for f in file_rows if f.file_type == "testsuite")
    testcase_count = sum(1 for f in file_rows if f.file_type == "testcase")

    return {
        "purpose_name": p.name,
        "version": ver.version_name if ver else "",
        "task_count": len(tasks),
        "tasks": all_files,
        "total_testsuite_files": testsuite_count,
        "total_testcase_files": testcase_count,
        "total_files": total_files or 1,
        "auto_analyzed": auto_analyzed,
        "auto_analyzed_pct": round(auto_analyzed / (total_files or 1) * 100, 1),
        "human_reviewed": human_reviewed,
        "human_overridden": human_overridden,
        "remaining_unreviewed": remaining_unreviewed,
    }


# ════════════════════════════════════════════════════════════════
# v5: JSON 树管理（按轮次）
# ════════════════════════════════════════════════════════════════

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete, func, update

from app.models.task import Task, LogFile
from app.models.task_tree import TestTaskTree, TestTaskNode
from app.services.task_tree import (
    parse_task_tree,
    check_cross_round_id_conflict,
)
from app.services.task_tree_s3 import probe_leaves_in_s3_batch

logger = logging.getLogger("app.mapping")


# ── v5 Schemas ──


class TreeJsonRequest(BaseModel):
    """预览 / 追加 JSON 树的请求体。"""
    model_config = {"protected_namespaces": ()}
    json_text: str = Field(..., alias="json", description="原始 JSON 字符串")


class UpdateNoteRequest(BaseModel):
    """改备注的请求体。"""
    note: str


# ── 辅助函数 ──


async def _get_version_or_404(db: AsyncSession, version_id: str) -> TestVersion:
    ver = (await db.execute(
        select(TestVersion).where(TestVersion.id == version_id)
    )).scalar_one_or_none()
    if not ver:
        raise HTTPException(404, "版本不存在")
    return ver


async def _get_tree_or_404(
    db: AsyncSession, version_id: str, round_number: int
) -> TestTaskTree:
    tree = (await db.execute(
        select(TestTaskTree).where(
            TestTaskTree.version_id == version_id,
            TestTaskTree.round_number == round_number,
        )
    )).scalar_one_or_none()
    if not tree:
        raise HTTPException(404, f"轮次 {round_number} 不存在")
    return tree


async def _next_round_number(db: AsyncSession, version_id: str) -> int:
    """下一个 round_number = max(已有) + 1；首个 = 1。"""
    result = await db.execute(
        select(func.max(TestTaskTree.round_number)).where(
            TestTaskTree.version_id == version_id
        )
    )
    max_round = result.scalar() or 0
    return max_round + 1


def _parse_to_pydantic_nodes(parsed: dict) -> Tuple[dict, List[Dict[str, Any]]]:
    """把 parse_task_tree 的 nodes 转成 TestTaskNode 字段 dict 列表（不写库）。"""
    nodes_payload: List[Dict[str, Any]] = []
    # 解析器产生的 nodes 列表里没有 "id"（id 是解析时分配的临时 id）
    # 这里直接用解析器给的字段，不需要新分配
    for n in parsed["nodes"]:
        nodes_payload.append({
            "internal_id": n["id"],  # 解析时分配的临时 id（用于 parent_id 关联）
            "parent_internal_id": n["parent_id"],
            "name": n["name"],
            "name_key": n["name_key"],
            "node_id": n["node_id"],
            "depth": n["depth"],
            "path": n["path"],
            "is_leaf": n["is_leaf"],
            "sort_order": n["sort_order"],
            "extra": n["extra"],
        })
    return parsed["tree"], nodes_payload


async def _persist_tree(
    db: AsyncSession,
    version_id: str,
    round_number: int,
    raw_json: str,
    note: str,
) -> TestTaskTree:
    """解析 JSON + 写 test_task_trees + test_task_nodes。事务内执行。"""
    parsed = parse_task_tree(raw_json)
    tree_dict, nodes_payload = _parse_to_pydantic_nodes(parsed)

    tree = TestTaskTree(
        version_id=version_id,
        round_number=round_number,
        root_name=tree_dict["name"],
        root_id=tree_dict["node_id"],
        raw_json=raw_json,
        note=note,
        parsed_at=datetime.utcnow(),
    )
    db.add(tree)
    await db.flush()  # 拿到 tree.id

    # 第二遍：建立 internal_id → db_id 的映射，写 TestTaskNode
    id_map: Dict[str, str] = {}
    for n in nodes_payload:
        node = TestTaskNode(
            tree_id=tree.id,
            parent_id=None,  # 下面再 update
            name=n["name"],
            name_key=n["name_key"],
            node_id=n["node_id"],
            depth=n["depth"],
            path=n["path"],
            is_leaf=n["is_leaf"],
            sort_order=n["sort_order"],
            extra=n["extra"],
        )
        db.add(node)
        await db.flush()
        id_map[n["internal_id"]] = node.id

    # 第三遍：回填 parent_id
    for n in nodes_payload:
        parent_internal = n["parent_internal_id"]
        if parent_internal and parent_internal in id_map:
            await db.execute(
                update(TestTaskNode)
                .where(TestTaskNode.id == id_map[n["internal_id"]])
                .values(parent_id=id_map[parent_internal])
            )

    await db.commit()
    await db.refresh(tree)
    return tree


def _build_tree_response_dict(
    tree: TestTaskTree,
    s3_probe: Optional[Dict[str, bool]] = None,
) -> dict:
    """把 TestTaskTree + 节点列表组装成 API 响应。

    响应字段：
      nodes  — 扁平节点列表（保留兼容老前端/旧调用方）
      tree   — 嵌套树形结构（root dict + children 递归；前端 TaskTreeNode 用这个）
    """
    s3_probe = s3_probe or {}
    nodes_resp: List[dict] = []
    leaf_count = 0
    children_map: Dict[Optional[str], List[dict]] = {}
    node_by_id: Dict[str, dict] = {}

    for n in tree.nodes:
        item = {
            "id": n.id,
            "parent_id": n.parent_id,
            "name": n.name,
            "name_key": n.name_key,
            "node_id": n.node_id,
            "depth": n.depth,
            "path": n.path,
            "is_leaf": n.is_leaf,
            "sort_order": n.sort_order,
            "extra": n.extra,
            "s3_matched": s3_probe.get(n.node_id) if n.is_leaf else None,
            "children": [],
        }
        nodes_resp.append(item)
        node_by_id[n.id] = item
        children_map.setdefault(n.parent_id, []).append(item)
        if n.is_leaf:
            leaf_count += 1

    # 回填 children 引用
    for parent_id, kids in children_map.items():
        if parent_id is None:
            continue
        parent_node = node_by_id.get(parent_id)
        if parent_node is not None:
            parent_node["children"] = kids

    # 找 root（parent_id is None）
    root = next(
        (v for v in node_by_id.values() if v["parent_id"] is None),
        None,
    )

    return {
        "id": tree.id,
        "version_id": tree.version_id,
        "round_number": tree.round_number,
        "root_name": tree.root_name,
        "root_id": tree.root_id,
        "note": tree.note,
        "total_nodes": len(nodes_resp),
        "leaf_count": leaf_count,
        "nodes": nodes_resp,
        "tree": root,  # 嵌套树形结构；为 None 表示空树
        "created_at": tree.created_at,
        "parsed_at": tree.parsed_at,
    }


# ── v5 端点 ──


@router.post("/versions/{version_id}/tree")
async def manage_task_tree(
    version_id: str,
    req: TreeJsonRequest,
    mode: str = Query("preview", pattern="^(preview|append)$"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """任务树管理：mode=preview 仅解析 + 探测；mode=append 解析 + 写库。

    append 流程：
      1. 解析 JSON（解析失败 400）
      2. 跨 round 冲突检查（冲突 400 + 整次拒绝，不写库）
      3. 分配 round_number = max(existing) + 1
      4. 写 test_task_trees + test_task_nodes（事务内）
      5. 返回新树 + 叶子数 + 备注
    """
    await _get_version_or_404(db, version_id)

    # 1. 解析（parse_task_tree 抛 ValueError 会被 FastAPI 转 500，我们手动转 400）
    try:
        parsed = parse_task_tree(req.json_text)
    except ValueError as e:
        logger.info("[tree.%s] parse failed version_id=%s err=%s", mode, version_id, e)
        raise HTTPException(400, str(e))

    leaf_node_ids = [lf["node_id"] for lf in parsed["leaves"]]

    if mode == "preview":
        # 预览：S3 探测 + 跨 round 冲突检查（不写库）
        # v5.5 fix: 传 version.version_name，不是 version_id
        version = await _get_version_or_404(db, version_id)
        s3_probe = await probe_leaves_in_s3_batch(version.version_name, leaf_node_ids)
        conflicts = await check_cross_round_id_conflict(db, version_id, leaf_node_ids)

        logger.info(
            "[tree.preview] version_id=%s total_nodes=%d leaf_count=%d "
            "matched=%d conflict_count=%d",
            version_id, len(parsed["nodes"]), len(leaf_node_ids),
            sum(1 for v in s3_probe.values() if v), len(conflicts),
        )
        return {
            "mode": "preview",
            "total_nodes": len(parsed["nodes"]),
            "leaf_count": len(leaf_node_ids),
            "extra_fields_seen": parsed["extra_fields_seen"],
            "tree": parsed["tree"],
            "leaves": parsed["leaves"],
            "s3_probe": s3_probe,
            "conflicts": conflicts,
        }

    # mode == "append" —— 写库前需要 note，但 preview 模式不要求
    # 这里从 header X-Round-Note 取（避免改 body schema）
    from fastapi import Request  # noqa
    # 简化：note 从请求 header 取
    # 但更合理的做法：append 单独一个端点 / 改 mode 包含 note
    # 暂时：append 要求 note 也在 body 里 → 改成用 TreeJsonRequest 加 note 字段
    # 实际上：我们已经在 TreeJsonRequest 里只有 json，note 走 header 比较 hack
    # 改：append 端点用单独的 schema
    raise NotImplementedError("append 走单独端点 /tree/append")


@router.post("/versions/{version_id}/tree/append")
async def append_task_tree(
    version_id: str,
    req: TreeJsonRequest,
    note: str = Query(..., min_length=1, description="轮次备注（必填）"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """追加一轮 JSON 任务树。备注必填。

    流程：
      1. 解析 JSON
      2. 跨 round 冲突检查（冲突 400 + 整次拒绝，不写库）
      3. 分配 round_number
      4. 写库
    """
    await _get_version_or_404(db, version_id)

    # 1. 解析
    try:
        parsed = parse_task_tree(req.json_text)
    except ValueError as e:
        logger.info("[tree.append] parse failed version_id=%s err=%s", version_id, e)
        raise HTTPException(400, str(e))

    leaf_node_ids = [lf["node_id"] for lf in parsed["leaves"]]

    # 2. 跨 round 冲突检查（在写库前；冲突直接拒绝，不分配 round）
    conflicts = await check_cross_round_id_conflict(db, version_id, leaf_node_ids)
    if conflicts:
        logger.warning(
            "[tree.append] cross_round_conflict version_id=%s conflict_count=%d",
            version_id, len(conflicts),
        )
        raise HTTPException(
            400,
            {
                "message": f"Id 冲突：{len(conflicts)} 个 Id 已在其他轮次存在，本次追加中止",
                "conflicts": conflicts,
            },
        )

    # 3. 分配 round
    round_number = await _next_round_number(db, version_id)

    # 4. 写库
    tree = await _persist_tree(db, version_id, round_number, req.json_text, note)

    logger.info(
        "[tree.append] version_id=%s round_number=%d total_nodes=%d leaf_count=%d note_len=%d",
        version_id, round_number, len(parsed["nodes"]), len(leaf_node_ids), len(note),
    )

    return _build_tree_response_dict(tree, s3_probe={})


@router.get("/versions/{version_id}/trees")
async def list_task_trees(
    version_id: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """列出该 version 下所有轮次。"""
    await _get_version_or_404(db, version_id)
    rows = (await db.execute(
        select(TestTaskTree).where(TestTaskTree.version_id == version_id)
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


@router.get("/versions/{version_id}/trees/{round_number}")
async def get_task_tree(
    version_id: str,
    round_number: int,
    include_s3_probe: bool = Query(False),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """拉取指定轮次。include_s3_probe=true 时额外查 S3 探测。"""
    tree = await _get_tree_or_404(db, version_id, round_number)
    s3_probe: Dict[str, bool] = {}
    if include_s3_probe:
        leaf_ids = [n.node_id for n in (tree.nodes or []) if n.is_leaf]
        # v5.5 fix: 必须用 version.version_name（之前 fallback 错了，传的是 version_id 主键）
        version = await _get_version_or_404(db, version_id)
        s3_probe = await probe_leaves_in_s3_batch(version.version_name, leaf_ids)
    return _build_tree_response_dict(tree, s3_probe=s3_probe)


@router.delete("/versions/{version_id}/trees/{round_number}")
async def delete_task_tree(
    version_id: str,
    round_number: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除指定轮次。Task 实体保留，tree_node_id 置 NULL。"""
    tree = await _get_tree_or_404(db, version_id, round_number)

    # 1. 把指向该轮次节点的 task.tree_node_id 置 NULL
    node_ids = [n.id for n in (tree.nodes or [])]
    if node_ids:
        await db.execute(
            update(Task)
            .where(Task.tree_node_id.in_(node_ids))
            .values(tree_node_id=None)
        )

    # 2. 删节点（cascaded by relationship）和树
    await db.execute(
        delete(TestTaskNode).where(TestTaskNode.tree_id == tree.id)
    )
    await db.delete(tree)
    await db.commit()

    logger.info(
        "[tree.delete] version_id=%s round_number=%d affected_task_count=%d",
        version_id, round_number, len(node_ids),
    )
    return {"ok": True, "deleted_round": round_number, "affected_task_count": len(node_ids)}


@router.post("/versions/{version_id}/trees/{round_number}/create_tasks")
async def create_tasks_from_tree(
    version_id: str,
    round_number: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """批量建任务：遍历该轮次 JSON 树的所有叶子 Id → S3 探测 → 创建/关联 Task。

    返回 created / linked / skipped 列表。
    """
    from app.config import settings

    tree = await _get_tree_or_404(db, version_id, round_number)
    version = (await db.execute(
        select(TestVersion).where(TestVersion.id == version_id)
    )).scalar_one()

    leaf_nodes = [n for n in (tree.nodes or []) if n.is_leaf]
    leaf_ids = [n.node_id for n in leaf_nodes]

    # 1. S3 探测
    s3_probe = await probe_leaves_in_s3_batch(version.version_name, leaf_ids)

    # 2. 已建 Task 集合（按 automation_task_id + package_version + source_type 识别）
    existing_rows = (await db.execute(
        select(Task).where(
            Task.package_version == version.version_name,
            Task.automation_task_id.in_(leaf_ids),
            Task.source_type == "s3",
        )
    )).scalars().all()
    existing_by_node_id: Dict[str, Task] = {t.automation_task_id: t for t in existing_rows}

    created: List[dict] = []
    linked: List[dict] = []
    skipped: List[dict] = []

    # 3. 为每个 leaf 处理
    for node in leaf_nodes:
        nid = node.node_id
        if not s3_probe.get(nid, False):
            skipped.append({
                "tree_node_id": node.id,
                "leaf_id": nid,
                "name": node.name,
                "reason": "S3 路径不存在或无数据",
            })
            continue

        if nid in existing_by_node_id:
            t = existing_by_node_id[nid]
            t.tree_node_id = node.id  # 关联
            linked.append({
                "task_id": t.id,
                "tree_node_id": node.id,
                "leaf_id": nid,
            })
        else:
            t = Task(
                name=f"{tree.root_name or version.version_name} - {nid[:8]}",
                status="pending",
                source_type="s3",
                parser_type="html",
                bucket=settings.s3_bucket or None,
                prefix=settings.s3_prefix or None,
                package_version=version.version_name,
                automation_task_id=nid,
                node_id="*",
                task_block_id="*",
                tree_node_id=node.id,
            )
            db.add(t)
            await db.flush()
            created.append({
                "task_id": t.id,
                "tree_node_id": node.id,
                "leaf_id": nid,
                "name": t.name,
            })

    await db.commit()

    logger.info(
        "[create_tasks] version_id=%s round_number=%d created=%d linked=%d skipped=%d",
        version_id, round_number, len(created), len(linked), len(skipped),
    )
    return {
        "round_number": round_number,
        "created": created,
        "linked": linked,
        "skipped": skipped,
    }


@router.post("/versions/{version_id}/tree/auto-fetch")
async def auto_fetch_task_tree(
    version_id: str,
    execution_id: str = Query(..., min_length=1, description="执行 ID（占位接口）"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """占位接口：未来插 Python 函数根据 execution_id 自动获取 JSON。

    当前实现：返回 503 + "即将推出"。
    """
    logger.info(
        "[tree.auto_fetch] version_id=%s execution_id=%s (placeholder)",
        version_id, execution_id,
    )
    raise HTTPException(
        503,
        {
            "status": "not_implemented",
            "message": "auto-fetch 即将推出，请手动粘贴 JSON",
        },
    )


@router.put("/versions/{version_id}/trees/{round_number}/note")
async def update_tree_note(
    version_id: str,
    round_number: int,
    req: UpdateNoteRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """改备注。"""
    tree = await _get_tree_or_404(db, version_id, round_number)
    tree.note = req.note
    await db.commit()

    logger.info(
        "[tree.update_note] version_id=%s round_number=%d note_length=%d",
        version_id, round_number, len(req.note),
    )
    return {"ok": True, "round_number": round_number, "note": tree.note}

