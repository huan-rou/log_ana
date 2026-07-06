"""Analysis API v5 集成测试：任务树视图 + suite 关联 + TestCase 聚合。"""
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


TREE_JSON = json.dumps({
    "Name": "TS_top",
    "Id": "1111111111111111111",
    "child_tasks": [
        {
            "Name": "TC_a",
            "Id": "2222222222222222222",
            "child_tasks": [
                {"Name": "TC_a_1", "Id": "3333333333333333333", "child_tasks": []},
                {"Name": "TC_a_2", "Id": "5555555555555555555", "child_tasks": []},
            ],
        },
    ],
})

TREE2_JSON = json.dumps({
    "Name": "TS_top",
    "Id": "1111111111111111111",
    "child_tasks": [
        {
            "Name": "TC_a",
            "Id": "4444444444444444444",  # 不同的 leaf id
            "child_tasks": [
                {"Name": "TC_a_1", "Id": "6666666666666666666", "child_tasks": []},
            ],
        },
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
async def version(db_session) -> TestVersion:
    v = TestVersion(version_name="1.2.3")
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)
    return v


@pytest_asyncio.fixture
async def two_rounds(version, db_session) -> tuple:
    """两个 round 的树：round=1 有 2 个叶子，round=2 有 1 个叶子。"""
    # round=1
    t1 = TestTaskTree(
        version_id=version.id, round_number=1,
        root_name="TS_top", root_id="1111111111111111111",
        note="r1", raw_json=TREE_JSON, parsed_at=__import__("datetime").datetime.utcnow(),
    )
    db_session.add(t1)
    await db_session.flush()

    # round=1 节点
    r1_root = TestTaskNode(
        tree_id=t1.id, parent_id=None,
        name="TS_top", name_key="TS_top", node_id="1111111111111111111",
        depth=0, path="/TS_top", is_leaf=False, sort_order=0, extra=None,
    )
    db_session.add(r1_root)
    await db_session.flush()
    r1_mid = TestTaskNode(
        tree_id=t1.id, parent_id=r1_root.id,
        name="TC_a", name_key="TC_a", node_id="2222222222222222222",
        depth=1, path="/TS_top/TC_a", is_leaf=False, sort_order=0, extra=None,
    )
    db_session.add(r1_mid)
    await db_session.flush()
    r1_l1 = TestTaskNode(
        tree_id=t1.id, parent_id=r1_mid.id,
        name="TC_a_1", name_key="TC_a_1", node_id="3333333333333333333",
        depth=2, path="/TS_top/TC_a/TC_a_1", is_leaf=True, sort_order=0, extra=None,
    )
    r1_l2 = TestTaskNode(
        tree_id=t1.id, parent_id=r1_mid.id,
        name="TC_a_2", name_key="TC_a_2", node_id="5555555555555555555",
        depth=2, path="/TS_top/TC_a/TC_a_2", is_leaf=True, sort_order=1, extra=None,
    )
    db_session.add_all([r1_l1, r1_l2])
    await db_session.flush()

    # round=2
    t2 = TestTaskTree(
        version_id=version.id, round_number=2,
        root_name="TS_top", root_id="1111111111111111111",
        note="r2", raw_json=TREE2_JSON, parsed_at=__import__("datetime").datetime.utcnow(),
    )
    db_session.add(t2)
    await db_session.flush()

    r2_root = TestTaskNode(
        tree_id=t2.id, parent_id=None,
        name="TS_top", name_key="TS_top", node_id="1111111111111111111",
        depth=0, path="/TS_top", is_leaf=False, sort_order=0, extra=None,
    )
    db_session.add(r2_root)
    await db_session.flush()
    r2_mid = TestTaskNode(
        tree_id=t2.id, parent_id=r2_root.id,
        name="TC_a", name_key="TC_a", node_id="4444444444444444444",
        depth=1, path="/TS_top/TC_a", is_leaf=False, sort_order=0, extra=None,
    )
    db_session.add(r2_mid)
    await db_session.flush()
    r2_l1 = TestTaskNode(
        tree_id=t2.id, parent_id=r2_mid.id,
        name="TC_a_1", name_key="TC_a_1", node_id="6666666666666666666",
        depth=2, path="/TS_top/TC_a/TC_a_1", is_leaf=True, sort_order=0, extra=None,
    )
    db_session.add(r2_l1)
    await db_session.commit()

    return t1, t2


@pytest_asyncio.fixture
async def tasks_and_logfiles(two_rounds, db_session) -> dict:
    """为 round=1 / round=2 各建一个 Task 和 LogFile。

    round=1 的 Task 有 2 个 LogFile (testcase 类型的)；
    round=2 的 Task 有 1 个 LogFile。
    """
    t1, t2 = two_rounds
    # round=1 的节点
    r1_l1 = (await db_session.execute(
        select(TestTaskNode).where(
            TestTaskNode.tree_id == t1.id,
            TestTaskNode.is_leaf == True,
            TestTaskNode.node_id == "3333333333333333333",
        )
    )).scalar_one()
    r1_l2 = (await db_session.execute(
        select(TestTaskNode).where(
            TestTaskNode.tree_id == t1.id,
            TestTaskNode.is_leaf == True,
            TestTaskNode.node_id == "5555555555555555555",
        )
    )).scalar_one()
    r2_l1 = (await db_session.execute(
        select(TestTaskNode).where(
            TestTaskNode.tree_id == t2.id,
            TestTaskNode.is_leaf == True,
            TestTaskNode.node_id == "6666666666666666666",
        )
    )).scalar_one()

    # round=1 task + logfiles
    task1 = Task(
        name="t1", status="completed", source_type="s3", parser_type="html",
        package_version="1.2.3", automation_task_id="3333333333333333333",
        node_id="*", task_block_id="*", tree_node_id=r1_l1.id,
    )
    db_session.add(task1)
    await db_session.flush()
    db_session.add_all([
        LogFile(task_id=task1.id, name="TC_a_1.html", file_path="artifacts/testcases/TC_a_1/main/TC_a_1.html",
                source_dir="artifacts/testcases/TC_a_1/main", file_type="testcase",
                testcase_name="TC_a_1", total_lines=100, failure_count=0),
        LogFile(task_id=task1.id, name="TC_a_2.html", file_path="artifacts/testcases/TC_a_2/main/TC_a_2.html",
                source_dir="artifacts/testcases/TC_a_2/main", file_type="testcase",
                testcase_name="TC_a_2", total_lines=200, failure_count=1),
    ])

    # round=2 task + logfile
    task2 = Task(
        name="t2", status="completed", source_type="s3", parser_type="html",
        package_version="1.2.3", automation_task_id="6666666666666666666",
        node_id="*", task_block_id="*", tree_node_id=r2_l1.id,
    )
    db_session.add(task2)
    await db_session.flush()
    db_session.add(
        LogFile(task_id=task2.id, name="TC_a_1_r2.html", file_path="artifacts/testcases/TC_a_1_r2/main/TC_a_1_r2.html",
                source_dir="artifacts/testcases/TC_a_1_r2/main", file_type="testcase",
                testcase_name="TC_a_1", total_lines=80, failure_count=0),
    )
    await db_session.commit()

    return {"task1": task1, "task2": task2, "r1_l1": r1_l1, "r2_l1": r2_l1}


@pytest_asyncio.fixture
async def client(db_session, admin_user, monkeypatch) -> AsyncGenerator[AsyncClient, None]:
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


# ── 测试 ──


@pytest.mark.asyncio
async def test_list_trees(client, tasks_and_logfiles):
    task1 = tasks_and_logfiles["task1"]
    resp = await client.get(f"/api/analysis/{task1.id}/trees")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["round_number"] == 1
    assert data[1]["round_number"] == 2


@pytest.mark.asyncio
async def test_get_tree_specific_round(client, tasks_and_logfiles):
    task1 = tasks_and_logfiles["task1"]
    resp = await client.get(f"/api/analysis/{task1.id}/tree?round=2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["round_number"] == 2
    # round=2 JSON: root + TC_a + TC_a_1 = 3 节点
    assert data["total_nodes"] == 3
    assert data["leaf_count"] == 1


@pytest.mark.asyncio
async def test_get_tree_via_task_tree_node_id(client, tasks_and_logfiles):
    """不传 round：根据 task.tree_node_id 自动定位 round。"""
    task1 = tasks_and_logfiles["task1"]
    resp = await client.get(f"/api/analysis/{task1.id}/tree")
    assert resp.status_code == 200
    data = resp.json()
    assert data["round_number"] == 1


@pytest.mark.asyncio
async def test_get_tree_404_for_missing_round(client, tasks_and_logfiles):
    task1 = tasks_and_logfiles["task1"]
    resp = await client.get(f"/api/analysis/{task1.id}/tree?round=99")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_aggregate_node(client, tasks_and_logfiles):
    """aggregate：跨 round 节点聚合。"""
    task1 = tasks_and_logfiles["task1"]
    r1_l1 = tasks_and_logfiles["r1_l1"]
    resp = await client.get(
        f"/api/analysis/{task1.id}/aggregate",
        params={"tree_node_id": r1_l1.id},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["node"]["name_key"] == "TC_a_1"
    agg = data["aggregate"]
    # 两个 round 都有 logfile → execution_count = 2
    assert agg["execution_count"] == 2
    assert agg["latest_round"] == 2
    assert agg["missing_rounds"] == []


@pytest.mark.asyncio
async def test_aggregate_node_missing_round(client, tasks_and_logfiles, db_session):
    """aggregate：某 round 节点存在但 task 无 logfile → 计入 missing_rounds。"""
    # 给 round=1 加一个 name_key="TC_a_3" 的叶子，但不带任何 logfile（模拟 missing）
    t1 = (await db_session.execute(
        select(TestTaskTree).where(TestTaskTree.round_number == 1)
    )).scalar_one()
    r1_mid = (await db_session.execute(
        select(TestTaskNode).where(
            TestTaskNode.tree_id == t1.id,
            TestTaskNode.node_id == "2222222222222222222",
        )
    )).scalar_one()
    new_leaf = TestTaskNode(
        tree_id=t1.id, parent_id=r1_mid.id,
        name="TC_a_3", name_key="TC_a_3", node_id="7777777777777777777",
        depth=2, path="/TS_top/TC_a/TC_a_3", is_leaf=True, sort_order=2, extra=None,
    )
    db_session.add(new_leaf)
    # 关联 task 但无 logfile
    task_no_data = Task(
        name="no_data", status="completed", source_type="s3", parser_type="html",
        package_version="1.2.3", automation_task_id="7777777777777777777",
        node_id="*", task_block_id="*", tree_node_id=new_leaf.id,
    )
    db_session.add(task_no_data)
    await db_session.commit()

    # 查询 aggregate
    task1 = tasks_and_logfiles["task1"]
    resp = await client.get(
        f"/api/analysis/{task1.id}/aggregate",
        params={"tree_node_id": new_leaf.id},
    )
    assert resp.status_code == 200
    agg = resp.json()["aggregate"]
    # round=1 没数据 → missing_rounds=[1]，execution_count=0
    assert 1 in agg["missing_rounds"]
    assert agg["execution_count"] == 0


@pytest.mark.asyncio
async def test_aggregate_testcases(client, tasks_and_logfiles):
    """aggregate/testcases：跨 round 按 testcase_name 聚合。"""
    task1 = tasks_and_logfiles["task1"]
    r1_l1 = tasks_and_logfiles["r1_l1"]
    resp = await client.get(
        f"/api/analysis/{task1.id}/aggregate/testcases",
        params={"tree_node_id": r1_l1.id},
    )
    assert resp.status_code == 200
    data = resp.json()
    # TC_a_1 在两个 round 都出现 → execution_count=2
    tc_a_1 = next(t for t in data["testcases"] if t["name"] == "TC_a_1")
    assert tc_a_1["execution_count"] == 2
    assert tc_a_1["latest_round"] == 2
    assert tc_a_1["missing_rounds"] == []


@pytest.mark.asyncio
async def test_aggregate_testcases_missing(client, tasks_and_logfiles, db_session):
    """额外加一个 round=1 才有的叶子节点，round=2 缺失 → testcases 仅 1 条，execution_count=1。"""
    # 加一个 name_key 不被切（名字无下划线）的叶子节点
    t1 = (await db_session.execute(
        select(TestTaskTree).where(TestTaskTree.round_number == 1)
    )).scalar_one()
    r1_mid = (await db_session.execute(
        select(TestTaskNode).where(
            TestTaskNode.tree_id == t1.id,
            TestTaskNode.node_id == "2222222222222222222",
        )
    )).scalar_one()
    extra_leaf = TestTaskNode(
        tree_id=t1.id, parent_id=r1_mid.id,
        name="uniqueNode", name_key="uniqueNode", node_id="9999999999999999999",
        depth=2, path="/TS_top/TC_a/uniqueNode", is_leaf=True, sort_order=99, extra=None,
    )
    db_session.add(extra_leaf)
    # 先 commit extra_leaf 拿到 id
    await db_session.commit()
    await db_session.refresh(extra_leaf)
    # 给 extra_leaf 关联一个 Task（无 logfile，模拟节点存在但 S3 无数据）
    extra_task = Task(
        name="t_extra", status="completed", source_type="s3", parser_type="html",
        package_version="1.2.3", automation_task_id="9999999999999999999",
        node_id="*", task_block_id="*", tree_node_id=extra_leaf.id,
    )
    db_session.add(extra_task)
    # 加 1 个 LogFile 模拟"执行了但失败"
    await db_session.flush()
    db_session.add(LogFile(
        task_id=extra_task.id, name="uniqueNode.html",
        file_path="artifacts/testcases/uniqueNode/main/uniqueNode.html",
        source_dir="artifacts/testcases/uniqueNode/main",
        file_type="testcase", testcase_name="uniqueNode",
        total_lines=50, failure_count=1,
    ))
    await db_session.commit()

    task1 = tasks_and_logfiles["task1"]
    resp = await client.get(
        f"/api/analysis/{task1.id}/aggregate/testcases",
        params={"tree_node_id": extra_leaf.id},
    )
    assert resp.status_code == 200
    data = resp.json()
    # 调试用
    print("\n\nRESPONSE:", data, "\n\n")
    # round=2 JSON 里没有 uniqueNode 节点 → 跨 round 聚合只看到 round=1
    assert len(data["testcases"]) == 1
    tc = data["testcases"][0]
    assert tc["name"] == "uniqueNode"
    assert tc["execution_count"] == 1
    # round=2 没声明这节点，missing_rounds=[]（按 v5 设计：missing 只算节点存在但无数据）
    assert tc["missing_rounds"] == []


@pytest.mark.asyncio
async def test_list_testcases_in_round(client, tasks_and_logfiles):
    """单 round 的 TestCase 行：按 testcase_name 分组的 LogFile。"""
    task1 = tasks_and_logfiles["task1"]
    resp = await client.get(
        f"/api/analysis/{task1.id}/testcases",
        params={"tree_node_id": tasks_and_logfiles["r1_l1"].id},
    )
    assert resp.status_code == 200
    data = resp.json()
    # round=1 task 下 2 个 testcase LogFile
    names = {t["testcase_name"] for t in data["testcases"]}
    assert names == {"TC_a_1", "TC_a_2"}
    assert data["summary"]["total_testcases"] == 2
    assert data["summary"]["with_failure"] == 1  # TC_a_2 有 failure


# ── find_suite_logfile 直接单测（已在 summary_report 里测过的简略版） ──


def test_find_suite_logfile_exact_match(db_session, tasks_and_logfiles):
    """精确匹配：suite.id stem == LogFile.name stem。"""
    from app.services.summary_report import find_suite_logfile
    # 准备一个 testsuite LogFile
    suite_lf = LogFile(
        task_id=tasks_and_logfiles["task1"].id,
        name="TS_id_1.html",
        file_path="artifacts/testsuite/TS_id_1.html",
        source_dir="artifacts/testsuite",
        file_type="testsuite",
    )
    db_session.add(suite_lf)
    db_session.commit()
    db_session.refresh(suite_lf)

    suite_info = {"id": "TS_id_1", "name": "TS_id_1", "desc": "TS_id_1"}
    result = find_suite_logfile(suite_info, [suite_lf])
    assert result is not None
    assert result.id == suite_lf.id


def test_find_suite_logfile_no_match(db_session, tasks_and_logfiles):
    from app.services.summary_report import find_suite_logfile
    suite_lf = LogFile(
        task_id=tasks_and_logfiles["task1"].id,
        name="somefile.html",
        file_path="artifacts/testsuite/somefile.html",
        source_dir="artifacts/testsuite",
        file_type="testsuite",
    )
    db_session.add(suite_lf)
    db_session.commit()
    db_session.refresh(suite_lf)

    suite_info = {"id": "totally_unrelated_id", "name": "x", "desc": "y"}
    result = find_suite_logfile(suite_info, [suite_lf])
    assert result is None
