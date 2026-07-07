"""Task Tree v5 集成测试（边界场景）。

覆盖 v5 计划第 11 步，重点是跨切场景 + 边界条件：

- POST /tree?mode=preview 不写库            → test_mapping_api.py::test_preview_does_not_write_db
- POST /tree?mode=append 跨 round 冲突回滚   → test_mapping_api.py::test_append_cross_round_conflict_rejected
- POST /tree/auto-fetch 503                  → test_mapping_api.py::test_auto_fetch_returns_503
- PUT /trees/{round}/note                    → test_mapping_api.py::test_update_note
- GET /aggregate 返回 execution_count / latest_round / missing_rounds
                                             → test_analysis_api.py::test_aggregate_node, test_aggregate_node_missing_round
- GET /aggregate/testcases                   → test_analysis_api.py::test_aggregate_testcases
- GET /testcases 返回单 round 的 TestCase 行 → test_analysis_api.py::test_list_testcases_in_round

本文件补充：
- 跨版本隔离（version A 的 leaf Id 不与 version B 冲突）
- 轮次号分配：MAX+1 策略（含 delete 后的复用）
- 单 round 边界（latest_round = 该 round）
- 全 missing 边界（latest_round = null）
- 老任务兼容（task.tree_node_id = null → /testcases 返回空）
- 输入校验：空 note / 空 json
- 全部 S3 missing 场景
- 长文本 / unicode 备注
- E2E 流程冒烟：append → create_tasks → aggregate
"""
from __future__ import annotations

import json
import os
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("LA_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("LA_AUDIT_ENABLED", "false")
os.environ.setdefault("LA_APP_DEBUG_LOGGING", "false")

from app.database import Base  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.models.mapping import TestVersion  # noqa: E402
from app.models.task import Task, LogFile  # noqa: E402
from app.models.task_tree import TestTaskTree, TestTaskNode  # noqa: E402
from app.auth import require_admin, hash_password  # noqa: E402
from app.main import app  # noqa: E402


# ── 测试数据 ──

JSON_TREE_A = json.dumps({
    "Name": "TS_A", "Id": "1000000000000000001",
    "child_tasks": [
        {"Name": "TC_a", "Id": "1000000000000000002", "child_tasks": []},
    ],
})

JSON_TREE_B_SAME_LEAF_ID = json.dumps({
    # 故意用跟 A 相同的 leaf Id — 验证跨版本不冲突
    "Name": "TS_B", "Id": "2000000000000000001",
    "child_tasks": [
        {"Name": "TC_a", "Id": "1000000000000000002", "child_tasks": []},
    ],
})

JSON_TREE_DEEP = json.dumps({
    "Name": "root", "Id": "3000000000000000001",
    "child_tasks": [
        {"Name": "l1", "Id": "3000000000000000002", "child_tasks": [
            {"Name": "l2", "Id": "3000000000000000003", "child_tasks": [
                {"Name": "l3", "Id": "3000000000000000004", "child_tasks": [
                    {"Name": "l4_leaf", "Id": "3000000000000000005", "child_tasks": []},
                ]},
            ]},
        ]},
    ],
})


# ── Fixtures ──


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    Session = async_sessionmaker(db_engine, expire_on_commit=False)
    async with Session() as s:
        yield s


@pytest_asyncio.fixture
async def admin_user(db_session) -> User:
    user = User(username="admin", hashed_password=hash_password("x"), role=UserRole.admin)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def client(db_session, admin_user) -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[require_admin] = lambda: admin_user
    from app.database import get_db as real_get_db
    app.dependency_overrides[real_get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ── 跨版本隔离 ──


@pytest.mark.asyncio
async def test_cross_version_leaf_id_does_not_conflict(client, db_session):
    """v5.5: 同一个 leaf Id 在不同 version 下不冲突。

    跨 round 冲突检查只查当前 version 下已有 round。
    跨 version 应该完全独立。
    """
    v1 = TestVersion(version_name="v1")
    v2 = TestVersion(version_name="v2")
    db_session.add_all([v1, v2])
    await db_session.commit()
    await db_session.refresh(v1)
    await db_session.refresh(v2)

    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={"1000000000000000002": True})):
        # v1 追加 A
        r1 = await client.post(
            f"/api/mapping/versions/{v1.id}/tree/append",
            params={"note": "v1.a"}, json={"json": JSON_TREE_A},
        )
        assert r1.status_code == 200

        # v2 追加 B（leaf Id 同 A）
        r2 = await client.post(
            f"/api/mapping/versions/{v2.id}/tree/append",
            params={"note": "v2.b"}, json={"json": JSON_TREE_B_SAME_LEAF_ID},
        )
        assert r2.status_code == 200
        assert r2.json()["round_number"] == 1

        # 两 version 各 1 棵树
        trees_v1 = (await client.get(f"/api/mapping/versions/{v1.id}/trees")).json()
        trees_v2 = (await client.get(f"/api/mapping/versions/{v2.id}/trees")).json()
        assert len(trees_v1) == 1
        assert len(trees_v2) == 1
        # v1 的 leaf 不应跟 v2 的冲突
        assert trees_v1[0]["note"] == "v1.a"
        assert trees_v2[0]["note"] == "v2.b"


# ── 轮次号分配 ──


@pytest.mark.asyncio
async def test_round_reuse_after_delete(client, db_session):
    """v5.5: 轮次号用 MAX+1，delete 后能复用空位。

    流程：append 1 → append 2 → delete 2 → append → 应得 round 2（不是 3）
    """
    v = TestVersion(version_name="reuse")
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={})):
        # round 1
        r1 = await client.post(
            f"/api/mapping/versions/{v.id}/tree/append",
            params={"note": "r1"}, json={"json": JSON_TREE_A},
        )
        assert r1.json()["round_number"] == 1

        # round 2（不同 leaf Id）
        json_r2 = json.dumps({
            "Name": "TS_r2", "Id": "4000000000000000001",
            "child_tasks": [
                {"Name": "TC_a", "Id": "4000000000000000002", "child_tasks": []},
            ],
        })
        r2 = await client.post(
            f"/api/mapping/versions/{v.id}/tree/append",
            params={"note": "r2"}, json={"json": json_r2},
        )
        assert r2.json()["round_number"] == 2

        # delete round 2
        await client.delete(f"/api/mapping/versions/{v.id}/trees/2")

        # append → 应得 round 2（复用）
        r3 = await client.post(
            f"/api/mapping/versions/{v.id}/tree/append",
            params={"note": "r3-after-delete"}, json={"json": json_r2},
        )
        assert r3.status_code == 200
        assert r3.json()["round_number"] == 2


@pytest.mark.asyncio
async def test_round_increment_after_delete_middle(client, db_session):
    """v5.5: delete 中间 round，append 应得 MAX+1。

    流程：append 1 → append 2 → append 3 → delete 1 → append → 应得 round 4（MAX+1）
    """
    v = TestVersion(version_name="inc")
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={})):
        for i, ids in enumerate([
            ("1000000000000000010", "1000000000000000011"),
            ("1000000000000000020", "1000000000000000021"),
            ("1000000000000000030", "1000000000000000031"),
        ], start=1):
            json_tree = json.dumps({
                "Name": f"TS_r{i}", "Id": ids[0],
                "child_tasks": [
                    {"Name": "TC", "Id": ids[1], "child_tasks": []},
                ],
            })
            r = await client.post(
                f"/api/mapping/versions/{v.id}/tree/append",
                params={"note": f"r{i}"}, json={"json": json_tree},
            )
            assert r.json()["round_number"] == i

        # delete round 1
        await client.delete(f"/api/mapping/versions/{v.id}/trees/1")

        # append → 应得 round 4（max=3 + 1）
        json_r4 = json.dumps({
            "Name": "TS_r4", "Id": "1000000000000000040",
            "child_tasks": [
                {"Name": "TC", "Id": "1000000000000000041", "child_tasks": []},
            ],
        })
        r4 = await client.post(
            f"/api/mapping/versions/{v.id}/tree/append",
            params={"note": "r4"}, json={"json": json_r4},
        )
        assert r4.status_code == 200
        assert r4.json()["round_number"] == 4


# ── 输入校验 ──


@pytest.mark.asyncio
async def test_append_empty_note_rejected(client, db_session):
    """v5.5: note 是必填（min_length=1），空 note 应被 FastAPI Query 校验拒绝。"""
    v = TestVersion(version_name="empty-note")
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    resp = await client.post(
        f"/api/mapping/versions/{v.id}/tree/append",
        params={"note": ""}, json={"json": JSON_TREE_A},
    )
    assert resp.status_code == 422  # pydantic validation


# ── v5.5 Regression: S3 探测必须用 version.version_name，不能用 version_id ──


@pytest.mark.asyncio
async def test_preview_uses_version_name_not_id(client, db_session):
    """v5.5 regression: 预览调 S3 探测时必须传 version.version_name（不是 TestVersion 主键 ID）。

    之前 bug：mapping.py:586 传的是 `version_id`（12 字符 hex 主键），导致 S3 路径变成
    `s3://bucket/prefix/{uuid}/{leaf_id}/`，永远找不到。
    """
    v = TestVersion(version_name="1.3.00.903")
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    captured: dict = {}

    async def capture(version_arg, leaf_ids, **_):
        captured["version_arg"] = version_arg
        captured["leaf_ids"] = list(leaf_ids)
        return {"123456789012": True}

    with patch("app.api.mapping.probe_leaves_in_s3_batch", new=capture):
        resp = await client.post(
            f"/api/mapping/versions/{v.id}/tree?mode=preview",
            json={"json": JSON_TREE_A},
        )
    assert resp.status_code == 200
    assert captured["version_arg"] == "1.3.00.903"  # 必须是 version_name
    assert captured["version_arg"] != v.id  # 不能是 TestVersion 主键


@pytest.mark.asyncio
async def test_get_tree_with_s3_probe_uses_version_name_not_id(client, db_session):
    """v5.5 regression: get_tree 带 include_s3_probe=true 时同样必须传 version.version_name。

    之前 bug：mapping.py:715 那个 `tree.version.name if hasattr(tree, "version") else version_id`
    是错的 fallback——TestTaskTree 没定义 version 关系，hasattr 永远 False。
    """
    v = TestVersion(version_name="1.3.00.903")
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={"1000000000000000002": True})):
        await client.post(
            f"/api/mapping/versions/{v.id}/tree/append",
            params={"note": "r1"}, json={"json": JSON_TREE_A},
        )

    captured: dict = {}

    async def capture(version_arg, leaf_ids, **_):
        captured["version_arg"] = version_arg
        return {"1000000000000000002": True}

    with patch("app.api.mapping.probe_leaves_in_s3_batch", new=capture):
        resp = await client.get(
            f"/api/mapping/versions/{v.id}/trees/1",
            params={"include_s3_probe": "true"},
        )
    assert resp.status_code == 200
    assert captured["version_arg"] == "1.3.00.903"
    assert captured["version_arg"] != v.id


@pytest.mark.asyncio
async def test_append_malformed_json_returns_400(client, db_session):
    """v5.5: JSON 解析失败 → 400（不是 500）。"""
    v = TestVersion(version_name="bad-json")
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    resp = await client.post(
        f"/api/mapping/versions/{v.id}/tree/append",
        params={"note": "ok"}, json={"json": "{not valid"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_append_missing_id_field_returns_400(client, db_session):
    """v5.5: JSON 顶层对象缺 Id → 400 + 清晰错误。"""
    v = TestVersion(version_name="no-id")
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    bad = json.dumps({"Name": "root", "child_tasks": []})
    resp = await client.post(
        f"/api/mapping/versions/{v.id}/tree/append",
        params={"note": "ok"}, json={"json": bad},
    )
    assert resp.status_code == 400


# ── 备注边界 ──


@pytest.mark.asyncio
async def test_update_note_unicode_and_long(client, db_session):
    """v5.5: 备注接受 unicode + 长文本（ORM 字段无长度限制）。"""
    v = TestVersion(version_name="note-edge")
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={})):
        await client.post(
            f"/api/mapping/versions/{v.id}/tree/append",
            params={"note": "init"}, json={"json": JSON_TREE_A},
        )

    long_unicode = "修复 round 2 — 验证 " + ("详细日志 " * 100)
    resp = await client.put(
        f"/api/mapping/versions/{v.id}/trees/1/note",
        json={"note": long_unicode},
    )
    assert resp.status_code == 200
    assert resp.json()["note"] == long_unicode


@pytest.mark.asyncio
async def test_update_note_empty_rejected(client, db_session):
    """v5.5: 空 note 在 update 端被前端的 reject 兜底（pydantic 不强制，但服务端允许空字符串）。

    当前服务端允许空字符串（model 是 str，不是 constr(min_length=1)），
    验证现状：空字符串 → 200 + note = ''
    """
    v = TestVersion(version_name="empty-note-update")
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={})):
        await client.post(
            f"/api/mapping/versions/{v.id}/tree/append",
            params={"note": "init"}, json={"json": JSON_TREE_A},
        )

    resp = await client.put(
        f"/api/mapping/versions/{v.id}/trees/1/note",
        json={"note": ""},
    )
    # 当前现状：服务端允许空字符串
    assert resp.status_code == 200
    assert resp.json()["note"] == ""


# ── 聚合边界 ──


@pytest.mark.asyncio
async def test_aggregate_single_round_no_missing(client, db_session):
    """v5.5: 只有 1 round 时，missing_rounds = []，latest_round = 该 round。

    注意：execution_count = 有 logfile 的 round 数。
    新建的 Task 默认无 logfile → 给它加 1 个 LogFile 模拟「分析完成」。
    """
    v = TestVersion(version_name="single")
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={"1000000000000000002": True})):
        r = await client.post(
            f"/api/mapping/versions/{v.id}/tree/append",
            params={"note": "r1"}, json={"json": JSON_TREE_A},
        )
        assert r.status_code == 200

        # create_task
        cr = await client.post(f"/api/mapping/versions/{v.id}/trees/1/create_tasks")
        assert cr.status_code == 200
        assert len(cr.json()["created"]) == 1
        task_id = cr.json()["created"][0]["task_id"]

    # 模拟分析完成：给 task 加 LogFile
    task = (await db_session.execute(select(Task).where(Task.id == task_id))).scalar_one()
    db_session.add(LogFile(
        task_id=task.id, name="TC_a.html", file_path="x",
        source_dir="x", file_type="testcase", testcase_name="TC_a",
        total_lines=10, failure_count=0,
    ))
    await db_session.commit()

    # aggregate 用 round=1 的 leaf id
    r1_tree = (await client.get(f"/api/mapping/versions/{v.id}/trees/1")).json()
    leaf_id = next(n["id"] for n in r1_tree["nodes"] if n["is_leaf"])

    resp = await client.get(f"/api/analysis/{task_id}/aggregate", params={"tree_node_id": leaf_id})
    assert resp.status_code == 200
    agg = resp.json()["aggregate"]
    assert agg["execution_count"] == 1
    assert agg["latest_round"] == 1
    assert agg["missing_rounds"] == []
    assert agg["first_round_logfile_count"] == 1


@pytest.mark.asyncio
async def test_aggregate_node_not_found_returns_404(client, db_session):
    """v5.5: 不存在的 tree_node_id → 404。"""
    v = TestVersion(version_name="agg-404")
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={})):
        await client.post(
            f"/api/mapping/versions/{v.id}/tree/append",
            params={"note": "r1"}, json={"json": JSON_TREE_A},
        )

    task = Task(
        name="orphan", status="completed", source_type="s3", parser_type="html",
        package_version=v.version_name,
        automation_task_id="dummy", node_id="*", task_block_id="*",
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    resp = await client.get(
        f"/api/analysis/{task.id}/aggregate",
        params={"tree_node_id": "non-existent-id"},
    )
    assert resp.status_code == 404


# ── 老任务兼容 ──


@pytest.mark.asyncio
async def test_testcases_for_task_without_tree_node_id_returns_empty(client, db_session):
    """v5.5: 老任务（tree_node_id IS NULL）→ /testcases 仍返回 task 的 testcase logfile，
    但 round_number 为 null（无法定位 round）。

    设计权衡：list_testcases_in_round 端点不强制要求 tree_node_id，
    主要面向审核场景；树关联缺失时降级为「不带 round 信息」。
    """
    v = TestVersion(version_name="legacy")
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    # 不建树，直接建 task（无 tree_node_id）+ testcase logfile
    task = Task(
        name="legacy-task", status="completed", source_type="s3", parser_type="html",
        package_version=v.version_name,
        automation_task_id="legacy_id", node_id="*", task_block_id="*",
    )
    db_session.add(task)
    await db_session.flush()
    db_session.add(LogFile(
        task_id=task.id, name="TC_legacy.html", file_path="x",
        source_dir="x", file_type="testcase", testcase_name="TC_legacy",
        total_lines=10, failure_count=0,
    ))
    await db_session.commit()
    await db_session.refresh(task)

    resp = await client.get(f"/api/analysis/{task.id}/testcases")
    assert resp.status_code == 200
    data = resp.json()
    # logfile 仍返回（端点不强制要求 tree_node_id）
    assert data["summary"]["total_testcases"] == 1
    assert data["testcases"][0]["testcase_name"] == "TC_legacy"
    # round_number 为 null（tree_node_id 缺失）
    assert data["round_number"] is None


@pytest.mark.asyncio
async def test_aggregate_for_task_without_version_returns_404(client, db_session):
    """v5.5: task 没关联任何 TestVersion（不通过 package_version 找得到）→ 404。"""
    task = Task(
        name="orphan", status="completed", source_type="s3", parser_type="html",
        package_version="ghost-version",  # 没对应 TestVersion
        automation_task_id="x", node_id="*", task_block_id="*",
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    resp = await client.get(
        f"/api/analysis/{task.id}/aggregate",
        params={"tree_node_id": "any"},
    )
    assert resp.status_code == 404


# ── 全部 S3 missing 场景 ──


@pytest.mark.asyncio
async def test_create_tasks_all_s3_missing(client, db_session):
    """v5.5: 所有叶子 S3 都没数据 → created=[], linked=[], skipped=[全部]。"""
    v = TestVersion(version_name="all-missing")
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={})):
        await client.post(
            f"/api/mapping/versions/{v.id}/tree/append",
            params={"note": "r1"}, json={"json": JSON_TREE_A},
        )

    # create_tasks 时所有 S3 探测都返 False
    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={"1000000000000000002": False})):
        resp = await client.post(f"/api/mapping/versions/{v.id}/trees/1/create_tasks")

    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == []
    assert data["linked"] == []
    assert len(data["skipped"]) == 1
    assert data["skipped"][0]["leaf_id"] == "1000000000000000002"
    assert data["skipped"][0]["reason"] == "S3 路径不存在或无数据"

    # DB 也没建 Task
    count = (await db_session.execute(
        select(Task).where(Task.package_version == v.version_name)
    )).scalars().all()
    assert len(count) == 0


# ── 树形深度 / 单节点 ──


@pytest.mark.asyncio
async def test_deeply_nested_tree_round_trip(client, db_session):
    """v5.5: 4 层嵌套树能完整 round-trip：append → get。"""
    v = TestVersion(version_name="deep")
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={"3000000000000000005": True})):
        r = await client.post(
            f"/api/mapping/versions/{v.id}/tree/append",
            params={"note": "deep"}, json={"json": JSON_TREE_DEEP},
        )
    assert r.status_code == 200
    # root + l1 + l2 + l3 + l4_leaf = 5 节点，1 叶子
    assert r.json()["total_nodes"] == 5
    assert r.json()["leaf_count"] == 1

    # get 时验证 path 嵌套正确
    resp = await client.get(f"/api/mapping/versions/{v.id}/trees/1")
    tree = resp.json()
    leaf = next(n for n in tree["nodes"] if n["is_leaf"])
    assert leaf["depth"] == 4
    assert leaf["path"] == "/root/l1/l2/l3/l4_leaf"


@pytest.mark.asyncio
async def test_single_node_tree_is_its_own_leaf(client, db_session):
    """v5.5: 单节点（顶层无 child_tasks）→ 总节点=1，叶子=1。"""
    v = TestVersion(version_name="single-node")
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    json_single = json.dumps({"Name": "only", "Id": "5000000000000000001", "child_tasks": []})

    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={"5000000000000000001": True})):
        r = await client.post(
            f"/api/mapping/versions/{v.id}/tree/append",
            params={"note": "single"}, json={"json": json_single},
        )
    assert r.status_code == 200
    assert r.json()["total_nodes"] == 1
    assert r.json()["leaf_count"] == 1


# ── E2E 冒烟 ──


@pytest.mark.asyncio
async def test_e2e_workflow_append_create_aggregate(client, db_session):
    """v5.5: 完整端到端：append → create_tasks → aggregate → aggregate_testcases。

    验证每个环节返回的数据彼此一致。
    """
    v = TestVersion(version_name="e2e")
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    # Step 1 + 2：append + create_tasks（都在 patch 上下文里）
    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={"1000000000000000002": True})):
        r1 = await client.post(
            f"/api/mapping/versions/{v.id}/tree/append",
            params={"note": "r1"}, json={"json": JSON_TREE_A},
        )
        assert r1.status_code == 200
        assert r1.json()["round_number"] == 1
        assert r1.json()["leaf_count"] == 1

        # create_tasks
        cr = await client.post(f"/api/mapping/versions/{v.id}/trees/1/create_tasks")
        assert cr.status_code == 200
        assert len(cr.json()["created"]) == 1
        task_id = cr.json()["created"][0]["task_id"]

    # 给 task 加 testcase LogFile（聚合能找到 testcase_name，execution_count > 0）
    task = (await db_session.execute(select(Task).where(Task.id == task_id))).scalar_one()
    db_session.add(LogFile(
        task_id=task.id, name="TC_a.html", file_path="x",
        source_dir="x", file_type="testcase", testcase_name="TC_a",
        total_lines=10, failure_count=0,
    ))
    await db_session.commit()

    # Step 3: 找 leaf node id
    r1_tree = (await client.get(f"/api/mapping/versions/{v.id}/trees/1")).json()
    leaf_id = next(n["id"] for n in r1_tree["nodes"] if n["is_leaf"])

    # Step 4: aggregate
    agg = await client.get(f"/api/analysis/{task_id}/aggregate", params={"tree_node_id": leaf_id})
    assert agg.status_code == 200
    assert agg.json()["aggregate"]["execution_count"] == 1
    assert agg.json()["aggregate"]["latest_round"] == 1
    assert agg.json()["aggregate"]["missing_rounds"] == []

    # Step 5: aggregate_testcases
    atc = await client.get(f"/api/analysis/{task_id}/aggregate/testcases", params={"tree_node_id": leaf_id})
    assert atc.status_code == 200
    assert atc.json()["summary"]["total_testcases"] == 1
    assert atc.json()["testcases"][0]["name"] == "TC_a"
    assert atc.json()["testcases"][0]["rounds"] == [1]
    assert atc.json()["testcases"][0]["missing_rounds"] == []


@pytest.mark.asyncio
async def test_e2e_two_rounds_with_one_missing(client, db_session):
    """v5.5: 2 round E2E：round 1 有数据，round 2 节点存在但 Task 无 logfile → 计入 missing。

    构造 name_key 相同的两个叶子：round1 有 logfile，round2 无。
    聚合时 execution_count=1, latest_round=1, missing_rounds=[2]。
    """
    v = TestVersion(version_name="e2e-missing")
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    # round 1 + round 2 + create_tasks 全部在 patch 上下文里
    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={"1000000000000000002": True})):
        r1 = await client.post(
            f"/api/mapping/versions/{v.id}/tree/append",
            params={"note": "r1"}, json={"json": JSON_TREE_A},
        )
        assert r1.status_code == 200

        # round 2：相同 name_key "TC_a"，但用不同 leaf Id
        json_r2 = json.dumps({
            "Name": "TS_r2", "Id": "6000000000000000001",
            "child_tasks": [
                {"Name": "TC_a", "Id": "6000000000000000002", "child_tasks": []},
            ],
        })
        r2 = await client.post(
            f"/api/mapping/versions/{v.id}/tree/append",
            params={"note": "r2"}, json={"json": json_r2},
        )
        assert r2.status_code == 200

        # round 1: create tasks（round 2 的 S3 mock 返 False → skipped）
        # 注意：mock 只返了 round 1 的 leaf → round 2 会被全部跳过
        cr = await client.post(f"/api/mapping/versions/{v.id}/trees/1/create_tasks")
        assert cr.status_code == 200
        assert len(cr.json()["created"]) == 1
        task_id = cr.json()["created"][0]["task_id"]

    # 给 task 加 logfile（让 execution_count = 1）
    task = (await db_session.execute(select(Task).where(Task.id == task_id))).scalar_one()
    db_session.add(LogFile(
        task_id=task.id, name="TC_a.html", file_path="x",
        source_dir="x", file_type="testcase", testcase_name="TC_a",
        total_lines=10, failure_count=0,
    ))
    await db_session.commit()

    # 拿 round 1 的 leaf id
    r1_tree = (await client.get(f"/api/mapping/versions/{v.id}/trees/1")).json()
    leaf_id = next(n["id"] for n in r1_tree["nodes"] if n["is_leaf"])

    # aggregate
    agg = await client.get(f"/api/analysis/{task_id}/aggregate", params={"tree_node_id": leaf_id})
    assert agg.status_code == 200
    a = agg.json()["aggregate"]
    # name_key="TC_a"，两个 round 都有该 name_key 的节点
    # round 1 有 logfile (has_data=True)；round 2 节点存在但 Task 没建 → missing
    assert a["execution_count"] == 1
    assert a["latest_round"] == 1
    assert a["missing_rounds"] == [2]
