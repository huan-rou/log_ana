"""Mapping API v5 集成测试：JSON 树管理（按轮次）。

覆盖：
- preview 模式不写库
- append 模式写库 + 跨 round 冲突回滚
- append 跨 round 无冲突 → 200
- list / get / delete
- create_tasks (with mocked S3 probe)
- auto_fetch 占位返回 503
- update_note 改备注
"""
from __future__ import annotations

import json
import os
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 在 import app 前确保环境
os.environ.setdefault("LA_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("LA_AUDIT_ENABLED", "false")
os.environ.setdefault("LA_APP_DEBUG_LOGGING", "false")

from app.database import Base, async_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.models.mapping import TestVersion  # noqa: E402
from app.models.mapping import TestPurpose, TaskReference  # noqa: E402
from app.models.task import AnalysisResult, AnalysisRule, Category, FailureEvent, LogFile, Task  # noqa: E402
from app.models.rule import Rule, RuleStatus  # noqa: E402
from app.auth import require_admin, hash_password  # noqa: E402


SAMPLE_JSON_3LEVEL = json.dumps({
    "Name": "TS_top",
    "Id": "1111111111111111111",
    "child_tasks": [
        {
            "Name": "TC_a",
            "Id": "2222222222222222222",
            "child_tasks": [
                {"Name": "TC_a_1", "Id": "3333333333333333333", "child_tasks": []},
            ],
        },
        {
            "Name": "TC_b",
            "Id": "4444444444444444444",
            "child_tasks": [],
        },
    ],
})

SAMPLE_JSON_OVERLAP = json.dumps({
    "Name": "TS_top",
    "Id": "9999999999999999999",
    "child_tasks": [
        # 故意用跟 SAMPLE_JSON_3LEVEL 相同的 leaf Id，触发跨 round 冲突
        {"Name": "TC_b", "Id": "4444444444444444444", "child_tasks": []},
    ],
})


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """每次测试用全新的内存 SQLite。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    yield Session()
    await engine.dispose()


@pytest_asyncio.fixture
async def admin_user(db_session) -> User:
    user = User(
        username="admin",
        hashed_password=hash_password("admin123"),
        role=UserRole.admin,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def version(db_session) -> TestVersion:
    v = TestVersion(version_name="1.2.3")
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)
    return v


@pytest_asyncio.fixture
async def client(db_session, admin_user, monkeypatch) -> AsyncGenerator[AsyncClient, None]:
    """用 FastAPI app + 内存 DB + 跳过 auth + 替换全局 async_session 的客户端。"""
    from app.database import async_session as real_async_session

    # 替换全局 async_session 为测试用的
    TestSession = async_sessionmaker(
        bind=create_async_engine("sqlite+aiosqlite:///:memory:"),
        expire_on_commit=False,
    )

    # 重建所有表（admin_user / version fixture 已经在 db_session 里创建）
    # 把 db_session 的数据搬到 TestSession
    # 简化：直接复用 db_session 的连接（不另起）
    # 实际方案：把 app 的 get_db 依赖 override 为返回 db_session
    async def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[require_admin] = lambda: admin_user
    app.dependency_overrides[lambda: None] = lambda: None  # placeholder
    from app.database import get_db as real_get_db
    app.dependency_overrides[real_get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ── preview 模式 ──


@pytest.mark.asyncio
async def test_preview_does_not_write_db(client, version, db_session):
    """preview 模式：解析 + 探测，不写库。"""
    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={"3333333333333333333": True, "4444444444444444444": True})):
        resp = await client.post(
            f"/api/mapping/versions/{version.id}/tree?mode=preview",
            json={"json": SAMPLE_JSON_3LEVEL},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "preview"
    assert data["total_nodes"] == 4
    assert data["leaf_count"] == 2
    # DB 没有写入
    from app.models.task_tree import TestTaskTree
    count = (await db_session.execute(
        __import__("sqlalchemy").select(__import__("sqlalchemy").func.count(TestTaskTree.id))
    )).scalar()
    assert count == 0


@pytest.mark.asyncio
async def test_preview_invalid_json_400(client, version):
    resp = await client.post(
        f"/api/mapping/versions/{version.id}/tree?mode=preview",
        json={"json": "{not valid"},
    )
    assert resp.status_code == 400


# ── append 模式 ──


@pytest.mark.asyncio
async def test_append_first_round_writes_db(client, version, db_session):
    """首次 append：round=1，写库成功。"""
    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={"3333333333333333333": True, "4444444444444444444": True})):
        resp = await client.post(
            f"/api/mapping/versions/{version.id}/tree/append",
            params={"note": "首次执行"},
            json={"json": SAMPLE_JSON_3LEVEL},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["round_number"] == 1
    assert data["note"] == "首次执行"
    assert data["total_nodes"] == 4
    assert data["leaf_count"] == 2


@pytest.mark.asyncio
async def test_append_second_round_auto_increment(client, version, db_session):
    """第二次 append：round=2。"""
    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={})):
        # 第一次
        r1 = await client.post(
            f"/api/mapping/versions/{version.id}/tree/append",
            params={"note": "r1"},
            json={"json": SAMPLE_JSON_3LEVEL},
        )
        assert r1.status_code == 200
        assert r1.json()["round_number"] == 1

        # 第二次（不同 Id，不冲突）
        with patch("app.api.mapping.probe_leaves_in_s3_batch",
                   new=AsyncMock(return_value={"5555555555555555555": True})):
            r2 = await client.post(
                f"/api/mapping/versions/{version.id}/tree/append",
                params={"note": "r2"},
                json={"json": json.dumps({
                    "Name": "TS_new", "Id": "8888888888888888888",
                    "child_tasks": [
                        {"Name": "TC_new", "Id": "5555555555555555555", "child_tasks": []}
                    ]
                })},
            )
        assert r2.status_code == 200
        assert r2.json()["round_number"] == 2


@pytest.mark.asyncio
async def test_append_cross_round_conflict_rejected(client, version, db_session):
    """跨 round 冲突：第二次 append 包含已有 Id → 400 + 不写库。"""
    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={"3333333333333333333": True, "4444444444444444444": True})):
        r1 = await client.post(
            f"/api/mapping/versions/{version.id}/tree/append",
            params={"note": "r1"},
            json={"json": SAMPLE_JSON_3LEVEL},
        )
        assert r1.status_code == 200

    # 第二次：SAMPLE_JSON_OVERLAP 含已有 Id=4444444444444444444
    r2 = await client.post(
        f"/api/mapping/versions/{version.id}/tree/append",
        params={"note": "r2"},
        json={"json": SAMPLE_JSON_OVERLAP},
    )
    assert r2.status_code == 400
    data = r2.json()
    assert "冲突" in str(data) or "conflict" in str(data).lower()
    # DB 还是只有 1 棵
    from app.models.task_tree import TestTaskTree
    from sqlalchemy import select, func
    count = (await db_session.execute(
        select(func.count(TestTaskTree.id)).where(TestTaskTree.version_id == version.id))
    ).scalar()
    assert count == 1


# ── list / get / delete ──


@pytest.mark.asyncio
async def test_list_trees(client, version, db_session):
    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={})):
        await client.post(
            f"/api/mapping/versions/{version.id}/tree/append",
            params={"note": "r1"}, json={"json": SAMPLE_JSON_3LEVEL},
        )
    resp = await client.get(f"/api/mapping/versions/{version.id}/trees")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["round_number"] == 1


@pytest.mark.asyncio
async def test_get_tree(client, version, db_session):
    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={})):
        await client.post(
            f"/api/mapping/versions/{version.id}/tree/append",
            params={"note": "r1"}, json={"json": SAMPLE_JSON_3LEVEL},
        )
    resp = await client.get(f"/api/mapping/versions/{version.id}/trees/1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["round_number"] == 1
    assert data["total_nodes"] == 4


@pytest.mark.asyncio
async def test_get_tree_with_s3_probe(client, version, db_session):
    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={})):
        await client.post(
            f"/api/mapping/versions/{version.id}/tree/append",
            params={"note": "r1"}, json={"json": SAMPLE_JSON_3LEVEL},
        )
    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={"3333333333333333333": True, "4444444444444444444": False})):
        resp = await client.get(
            f"/api/mapping/versions/{version.id}/trees/1",
            params={"include_s3_probe": "true"},
        )
    assert resp.status_code == 200
    # 叶子节点带 s3_matched 字段
    leaf_nodes = [n for n in resp.json()["nodes"] if n["is_leaf"]]
    assert any(n["s3_matched"] is True for n in leaf_nodes)
    assert any(n["s3_matched"] is False for n in leaf_nodes)


@pytest.mark.asyncio
async def test_delete_tree_clears_task_links(client, version, db_session):
    """删除 round：相关 task 的 tree_node_id 被置 NULL，Task 实体保留。"""
    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={})):
        await client.post(
            f"/api/mapping/versions/{version.id}/tree/append",
            params={"note": "r1"}, json={"json": SAMPLE_JSON_3LEVEL},
        )
    # 模拟已有 task 关联到该 round 的 node
    from app.models.task import Task
    from app.models.task_tree import TestTaskTree, TestTaskNode
    tree = (await db_session.execute(
        __import__("sqlalchemy").select(TestTaskTree).where(TestTaskTree.version_id == version.id))
    ).scalar_one()
    leaf_node = (await db_session.execute(
        __import__("sqlalchemy").select(TestTaskNode).where(
            TestTaskNode.tree_id == tree.id, TestTaskNode.is_leaf == True)
    )).scalars().first()
    t = Task(
        name="x", source_type="s3", parser_type="html",
        package_version=version.version_name,
        automation_task_id=leaf_node.node_id,
        node_id="*", task_block_id="*",
        tree_node_id=leaf_node.id,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    assert t.tree_node_id is not None

    # 删除 round
    resp = await client.delete(f"/api/mapping/versions/{version.id}/trees/1")
    assert resp.status_code == 200

    # task.tree_node_id 应被置 NULL
    await db_session.refresh(t)
    assert t.tree_node_id is None
    # task 实体仍存在
    assert t.id is not None


@pytest.mark.asyncio
async def test_delete_nonexistent_round_404(client, version):
    resp = await client.delete(f"/api/mapping/versions/{version.id}/trees/999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_current_reports_use_completed_tasks_and_reviewable_files(
    client, version, db_session, admin_user, monkeypatch, tmp_path,
):
    """Version and purpose reports use current completed-task data only."""
    category = Category(name="Network")
    purpose = TestPurpose(version_id=version.id, name="Smoke")
    rule = AnalysisRule(
        rule_id="network_rule", name="Network rule", category_id=category.id,
        enabled=True, script_module="rules.network_rule",
    )
    db_session.add_all([category, purpose])
    await db_session.flush()
    rule.category_id = category.id
    db_session.add(rule)
    await db_session.flush()
    draft_rule = AnalysisRule(
        rule_id="draft_metadata_rule", name="Original Name", category_id=category.id,
        enabled=True, script_module="rules.user.draft_metadata_rule",
    )
    db_session.add(draft_rule)
    await db_session.flush()
    db_session.add(Rule(
        rule_id=draft_rule.rule_id,
        status=RuleStatus.draft.value,
        created_by=admin_user.id,
        analysis_rule_id=draft_rule.id,
    ))
    db_session.add(TaskReference(purpose_id=purpose.id, task_id="automation-1"))

    completed = Task(
        name="completed", status="completed", source_type="s3",
        package_version=version.version_name, automation_task_id="automation-1",
    )
    ignored = Task(
        name="still-running", status="parsing", source_type="s3",
        package_version=version.version_name, automation_task_id="automation-1",
    )
    db_session.add_all([completed, ignored])
    await db_session.flush()

    logfile = LogFile(
        task_id=completed.id, name="case.html", file_path="case.html",
        file_type="testcase", failure_count=1, review_status="confirmed",
    )
    db_session.add(logfile)
    await db_session.flush()
    failure = FailureEvent(task_id=completed.id, log_file_id=logfile.id)
    db_session.add(failure)
    await db_session.flush()
    db_session.add(AnalysisResult(
        failure_event_id=failure.id, log_file_id=logfile.id, rank=1,
        category_id=category.id, rule_id=rule.id, confidence=0.9,
    ))
    await db_session.commit()

    import app.core.audit_logger as audit_module
    from app.core.audit_logger import AuditLogger, REPORT_AUDIT_SCHEMA
    audit_logger = AuditLogger(str(tmp_path / "audit"))
    await audit_logger.pipeline_start(completed.id, report_audit_schema=REPORT_AUDIT_SCHEMA)
    await audit_logger.rule_evaluate(completed.id, rule_id="network_rule", matched=True)
    await audit_logger.rule_evaluate(completed.id, rule_id="network_rule", matched=False)
    monkeypatch.setattr(audit_module, "audit_logger", audit_logger)

    version_response = await client.get(f"/api/reports/versions/{version.id}")
    assert version_response.status_code == 200
    data = version_response.json()
    assert data["tasks"]["total"] == 1
    assert data["analysis"]["subjects"] == 1
    assert data["analysis"]["completed"] == 1
    assert data["analysis"]["rule_result"] == 1
    assert data["review"] == {"eligible": 1, "pending": 0, "confirmed": 1, "overridden": 0}
    assert data["tool_effectiveness"] == {
        "total_files": 1, "analyzed_files": 1, "analysis_rate": 100.0,
        "reviewed_files": 1, "adopted_files": 1, "adoption_rate": 100.0,
    }
    assert data["categories"] == [{"name": "Network", "count": 1}]
    assert data["rule_audit_status"]["available"] is True
    assert data["rule_statistics"] == [{
        "rule_id": "network_rule", "name": "Network rule", "category": "Network",
        "selected_count": 1, "selected_rate": 100.0,
        "evaluation_count": 2, "matched_count": 1, "match_rate": 50.0,
        "error_count": 0,
    }]
    assert data["purposes"][0]["name"] == "Smoke"
    assert data["purposes"][0]["task_count"] == 1

    purpose_response = await client.get(f"/api/reports/purposes/{purpose.id}")
    assert purpose_response.status_code == 200
    assert purpose_response.json()["scope"]["type"] == "purpose"
    assert purpose_response.json()["analysis"]["completed"] == 1


# ── create_tasks ──


@pytest.mark.asyncio
async def test_create_tasks_with_s3_probe(client, version, db_session):
    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={})):
        await client.post(
            f"/api/mapping/versions/{version.id}/tree/append",
            params={"note": "r1"}, json={"json": SAMPLE_JSON_3LEVEL},
        )
    # 现在调用 create_tasks：mock S3 探测只让一个 leaf 命中
    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={"3333333333333333333": True, "4444444444444444444": False})):
        resp = await client.post(
            f"/api/mapping/versions/{version.id}/trees/1/create_tasks"
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["round_number"] == 1
    assert len(data["created"]) == 1
    assert data["created"][0]["leaf_id"] == "3333333333333333333"
    assert len(data["skipped"]) == 1
    assert data["skipped"][0]["reason"] == "S3 路径不存在或无数据"


@pytest.mark.asyncio
async def test_create_tasks_links_existing_task(client, version, db_session):
    """已有同 automation_task_id 的 Task → 关联到当前 round，不重复创建。"""
    from app.models.task import Task
    from app.models.task_tree import TestTaskTree

    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={})):
        await client.post(
            f"/api/mapping/versions/{version.id}/tree/append",
            params={"note": "r1"}, json={"json": SAMPLE_JSON_3LEVEL},
        )
    # 预创建 Task（不带 tree_node_id）
    existing = Task(
        name="pre", source_type="s3", parser_type="html",
        package_version=version.version_name,
        automation_task_id="3333333333333333333",
        node_id="*", task_block_id="*",
    )
    db_session.add(existing)
    await db_session.commit()
    await db_session.refresh(existing)

    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={"3333333333333333333": True, "4444444444444444444": True})):
        resp = await client.post(
            f"/api/mapping/versions/{version.id}/trees/1/create_tasks"
        )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["created"]) == 1  # 4444... 新建
    assert len(data["linked"]) == 1   # 3333... 关联
    assert data["linked"][0]["task_id"] == existing.id

    # existing.task.tree_node_id 应被设上
    await db_session.refresh(existing)
    assert existing.tree_node_id is not None


# ── auto-fetch ──


@pytest.mark.asyncio
async def test_auto_fetch_returns_503(client, version):
    resp = await client.post(
        f"/api/mapping/versions/{version.id}/tree/auto-fetch",
        params={"execution_id": "exec_123"},
    )
    assert resp.status_code == 503
    data = resp.json()
    # FastAPI 把 HTTPException 的 detail 包装在 "detail" 键下
    detail = data["detail"]
    assert detail["status"] == "not_implemented"
    assert "auto-fetch" in detail["message"] or "即将推出" in detail["message"]


# ── update_note ──


@pytest.mark.asyncio
async def test_update_note(client, version, db_session):
    with patch("app.api.mapping.probe_leaves_in_s3_batch",
               new=AsyncMock(return_value={})):
        await client.post(
            f"/api/mapping/versions/{version.id}/tree/append",
            params={"note": "original"}, json={"json": SAMPLE_JSON_3LEVEL},
        )
    resp = await client.put(
        f"/api/mapping/versions/{version.id}/trees/1/note",
        json={"note": "updated note 改备注"},
    )
    assert resp.status_code == 200
    assert resp.json()["note"] == "updated note 改备注"
