"""任务树 JSON 解析与跨 round 冲突检查。

输入示例（见仓库根目录 example_task_result.json / example_task_result2.json）：
    {
        "Name": "S1-10G-8S28/R45_B2B_part1",
        "Id": "3806765545196879872",
        "child_tasks": [
            { "Name": "...", "Id": "...", "child_tasks": [...] }
        ]
    }

解析规则：
- 顶层必须是 dict
- 节点必填 Id（name / id / ID 等大小写变体都接受）
- child_tasks 是数组：[] / null / 缺失 = 叶子
- name_key = name.rsplit('_', 1)[0]（用于跨 round 聚合同名节点）
- 其他字段原样存到 extra（JSON 字符串）

错误统一抛 ValueError(message)。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger("app.services.task_tree")


# ── 字段大小写映射 ──

_NAME_KEYS = ("name", "Name", "NAME")
_ID_KEYS = ("id", "Id", "ID")
_CHILD_KEYS = ("child_tasks", "ChildTasks", "childTasks", "childtasks")


def _pick(d: dict, keys: tuple, *, required: bool = True, default=None):
    """大小写不敏感地从 dict 里取字段。"""
    for k in keys:
        if k in d:
            return d[k]
    if required:
        raise ValueError(f"缺少字段 {keys[0]}/{keys[-1]}")
    return default


# ── 核心工具 ──


def compute_name_key(name: str) -> str:
    """聚合键 = name.rsplit('_', 1)[0]（按最后一个 _ 分割取前面部分）。

    规则：所有 _ 都切最后一段。
    例：
        "TC_id_1"           -> "TC_id"
        "TC_id_1_a8b3c"     -> "TC_id_1"
        "统计分析__2"        -> "统计分析_"
        "统计分析__2_x9y2z" -> "统计分析__2"
        "BGP0_reRun6458"    -> "BGP0"
        ""                  -> ""

    局限性：对"BGP0_reRun6458" 这种"基础名 = 整段名字"的节点会切错最后一段。
    v5 范围：接受这个误伤。如果实际场景切错率太高，后续可加"测试系统后缀白名单"或正则规则。
    """
    if not name:
        return ""
    if "_" not in name:
        return name
    return name.rsplit("_", 1)[0]


# ── 主解析流程 ──


def parse_task_tree(raw_json: str) -> dict:
    """解析 JSON 字符串，返回结构化结果。

    Returns:
        {
            "tree": { ... },           # 嵌套 dict 形式（带 children 字段）
            "nodes": [ ... ],          # 扁平化节点列表（每个含 parent_id, depth, path, is_leaf, extra）
            "leaves": [ ... ],         # 叶子节点列表（仅 id 字段）
            "extra_fields_seen": [ ... ],  # 解析过程中见到的非 Name/Id/child_tasks 字段名
        }
    Raises:
        ValueError: 解析错误（顶层不是对象 / 缺 Id / child_tasks 非数组 / 同树 Id 重复）
    """
    if not raw_json or not raw_json.strip():
        raise ValueError("JSON 字符串为空")

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 格式错误: {e}")

    if not isinstance(data, dict):
        raise ValueError("JSON 顶层必须是对象")

    seen_ids: set[str] = set()
    extra_fields_seen: set[str] = set()

    nodes: list[dict] = []
    leaves: list[dict] = []

    def _walk(node: dict, parent_id: Optional[str], depth: int, path: str) -> str:
        if not isinstance(node, dict):
            raise ValueError(f"节点 {path!r} 不是对象")

        # 计算当前节点 path（用于错误信息）
        name = _pick(node, _NAME_KEYS, required=False, default="")
        node_path = f"{path}/{name}" if path else f"/{name}"

        # 必填字段
        node_id = _pick(node, _ID_KEYS, required=True)
        node_id_str = str(node_id)
        if node_id_str in seen_ids:
            raise ValueError(f"Id 重复: {node_id_str}（路径: {node_path}）")
        seen_ids.add(node_id_str)

        # child_tasks 可选（缺失/空/null = 叶子）
        if any(k in node for k in _CHILD_KEYS):
            child_raw = _pick(node, _CHILD_KEYS, required=False, default=[])
            if child_raw is None:
                child_raw = []
            if not isinstance(child_raw, list):
                raise ValueError(f"节点 {node_path!r} 的 child_tasks 必须是数组")
        else:
            child_raw = []

        is_leaf = len(child_raw) == 0

        # 收集 extra 字段（除 Name/Id/child_tasks 之外）
        extra: dict[str, Any] = {}
        for k, v in node.items():
            kl = k.lower()
            if kl in {"name", "id", "child_tasks"}:
                continue
            extra[k] = v
            extra_fields_seen.add(k)
        extra_json = json.dumps(extra, ensure_ascii=False) if extra else None

        # 生成内部 id（用于 parent_id 关联）
        from app.models.task import gen_uuid
        internal_id = gen_uuid()

        # 新增 node（path 已在上面计算）
        node_rec = {
            "id": internal_id,
            "parent_id": parent_id,
            "name": str(name) if name else "",
            "name_key": compute_name_key(str(name) if name else ""),
            "node_id": node_id_str,
            "depth": depth,
            "path": node_path,
            "is_leaf": is_leaf,
            "sort_order": 0,  # 由调用方按遍历顺序填充
            "extra": extra_json,
        }
        nodes.append(node_rec)
        if is_leaf:
            leaves.append({"id": internal_id, "node_id": node_id_str, "name": node_rec["name"]})

        # 递归处理子节点
        for i, child in enumerate(child_raw):
            child_id = _walk(child, internal_id, depth + 1, node_path)
            # 记录子节点的 sort_order（在 child 节点已经 push 到 nodes 里，修改其 sort_order）
            for n in reversed(nodes):
                if n["id"] == child_id:
                    n["sort_order"] = i
                    break

        return internal_id

    root_internal_id = _walk(data, None, 0, "")

    # 树形结构（给前端展示用）
    children_map: dict[str, list[dict]] = {}
    for n in nodes:
        parent = n["parent_id"]
        if parent:
            children_map.setdefault(parent, []).append(
                {k: v for k, v in n.items() if k != "parent_id"}
            )
    root_node = next(n for n in nodes if n["id"] == root_internal_id)
    tree = {
        "id": root_node["id"],
        "name": root_node["name"],
        "name_key": root_node["name_key"],
        "node_id": root_node["node_id"],
        "depth": root_node["depth"],
        "path": root_node["path"],
        "is_leaf": root_node["is_leaf"],
        "extra": root_node["extra"],
        "children": children_map.get(root_internal_id, []),
    }

    logger.info(
        "[parse_task_tree] total_nodes=%d leaf_count=%d extra_fields=%s",
        len(nodes), len(leaves), sorted(extra_fields_seen),
    )

    return {
        "tree": tree,
        "nodes": nodes,
        "leaves": leaves,
        "extra_fields_seen": sorted(extra_fields_seen),
    }


def check_cross_round_id_conflict(
    db,
    version_id: str,
    new_leaf_ids: list[str],
) -> list[dict]:
    """检查 new_leaf_ids 是否与该 version 下已有 round 的节点 Id 冲突。

    Returns:
        冲突列表: [{ "node_id": "...", "conflicting_round": N, "conflicting_node_id": "..." }]
        空列表 = 无冲突
    """
    from sqlalchemy import select
    from app.models.task_tree import TestTaskNode, TestTaskTree

    if not new_leaf_ids:
        return []

    stmt = (
        select(TestTaskNode.node_id, TestTaskTree.round_number, TestTaskNode.id)
        .join(TestTaskTree, TestTaskNode.tree_id == TestTaskTree.id)
        .where(
            TestTaskTree.version_id == version_id,
            TestTaskNode.node_id.in_(new_leaf_ids),
        )
    )
    rows = db.execute(stmt).all()
    conflicts: list[dict] = []
    for node_id, round_number, tn_id in rows:
        conflicts.append({
            "node_id": node_id,
            "conflicting_round": round_number,
            "conflicting_tree_node_id": tn_id,
        })
    if conflicts:
        logger.warning(
            "[cross_round_conflict] version_id=%s conflict_count=%d",
            version_id, len(conflicts),
        )
    return conflicts
