from __future__ import annotations

import json
import os
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("LA_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("LA_AUDIT_ENABLED", "false")
os.environ.setdefault("LA_APP_DEBUG_LOGGING", "false")

from app.database import Base
from app.database import get_db as real_get_db
from app.auth import require_admin, require_start_task
from app.main import app
from app.models.mapping import TestPurpose, TestVersion
from app.models.purpose_execution import (
    CaseOccurrence,
    ExecutionSuite,
    PurposeExecution,
    TaskBlock,
    TaskSource,
)
from app.models.task import Category, LogFile, Task
from app.services.purpose_execution import (
    persist_execution_preview,
    preview_execution,
    run_execution_pipeline,
    suite_rows,
    testcase_history as load_testcase_history,
    testcase_rows as load_testcase_rows,
)
from app.services.summary_report import normalize_status
from app.services.overall_report import apply_latest_case_counts, build_latest_case_statuses
from app.services.storage.base import DirEntry, FileContent, StorageProvider
from app.services.storage.provider_manager import provider_manager


class MemoryS3(StorageProvider):
    def __init__(self, dirs=None, files=None):
        self.dirs = dirs or {}
        self.files = files or {}

    @property
    def provider_type(self):
        return "s3"

    @property
    def label(self):
        return "memory"

    async def list_dir(self, path):
        if path not in self.dirs:
            raise FileNotFoundError(path)
        return self.dirs[path]

    async def read_file(self, path, max_bytes=5 * 1024 * 1024):
        if path not in self.files:
            raise FileNotFoundError(path)
        content = self.files[path]
        return FileContent(path=path, content_type="yaml", content=content, size=len(content))

    async def file_meta(self, path):  # pragma: no cover - not used by these tests
        raise NotImplementedError


@pytest.fixture
def memory_s3():
    original = provider_manager.get("s3")
    provider = MemoryS3()
    provider_manager.register(provider)
    yield provider
    if original:
        provider_manager.register(original)
    else:
        provider_manager.unregister("s3")


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session):
    async def override_db():
        yield db_session

    app.dependency_overrides[real_get_db] = override_db
    app.dependency_overrides[require_start_task] = lambda: object()
    app.dependency_overrides[require_admin] = lambda: object()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _execution(db, purpose, round_number, feature, block_name, suite_name):
    execution = PurposeExecution(
        purpose_id=purpose.id,
        round_number=round_number,
        external_task_id=f"external-{round_number}",
        raw_json="{}",
    )
    db.add(execution)
    await db.flush()
    task = Task(
        name=f"round-{round_number}",
        source_type="s3",
        status="completed",
        purpose_execution_id=execution.id,
    )
    source = TaskSource(
        execution_id=execution.id,
        name=feature,
        source_task_id=f"source-{round_number}",
        discovery_order=0,
        status="completed",
    )
    db.add_all([task, source])
    await db.flush()
    block = TaskBlock(
        source_id=source.id,
        node_id=f"node-{round_number}",
        task_block_id=block_name,
        upload_path=f"v/source-{round_number}/node/{block_name}/upload",
        summary_path=f"v/source-{round_number}/node/{block_name}/upload/metadata/summary_report.yaml",
        discovery_order=0,
        status="ready",
    )
    db.add(block)
    await db.flush()
    suite = ExecutionSuite(
        task_block_id=block.id,
        suite_id=f"suite-{round_number}",
        name=suite_name,
        raw_result="failed",
        normalized_status="failed",
    )
    db.add(suite)
    await db.flush()
    return execution, task, source, block, suite


def test_unknown_summary_status_is_not_blocked():
    assert normalize_status("infra_error") == ("infra_error", "unknown")
    assert normalize_status("blocked") == ("blocked", "blocked")


@pytest.mark.asyncio
async def test_preview_expands_multiple_leaves_and_task_blocks(db_session, memory_s3):
    version = TestVersion(version_name="R-preview")
    db_session.add(version)
    await db_session.commit()
    memory_s3.dirs.update({
        "R-preview/task-a": [DirEntry(name="node-a", type="directory", path="R-preview/task-a/node-a")],
        "R-preview/task-a/node-a": [
            DirEntry(name="block-1", type="directory", path="R-preview/task-a/node-a/block-1"),
            DirEntry(name="block-2", type="directory", path="R-preview/task-a/node-a/block-2"),
        ],
    })
    tree = json.dumps({
        "Name": "root", "Id": "root-id", "child_tasks": [
            {"Name": "Feature A", "Id": "task-a", "child_tasks": []},
            {"Name": "Feature B", "Id": "task-b", "child_tasks": []},
        ],
    })
    preview = await preview_execution(version, "external-1", tree)
    assert preview["leaf_count"] == 2
    assert preview["block_count"] == 2
    assert preview["sources"][0]["name"] == "Feature A"
    assert preview["sources"][0]["task_id"] == "task-a"
    assert preview["sources"][1]["errors"]


@pytest.mark.asyncio
async def test_execution_preview_create_list_and_detail_api(client, db_session, memory_s3):
    version = TestVersion(version_name="R-api")
    db_session.add(version)
    await db_session.flush()
    purpose = TestPurpose(version_id=version.id, name="API 目的")
    db_session.add(purpose)
    await db_session.commit()
    memory_s3.dirs.update({
        "R-api/task-api": [DirEntry(name="node", type="directory", path="R-api/task-api/node")],
        "R-api/task-api/node": [DirEntry(name="block", type="directory", path="R-api/task-api/node/block")],
    })
    payload = {
        "purpose_id": purpose.id,
        "external_task_id": "external-api",
        "json": json.dumps({"Name": "Feature API", "Id": "task-api", "child_tasks": []}),
    }
    preview_response = await client.post("/api/purpose-executions/preview", json=payload)
    assert preview_response.status_code == 200
    assert preview_response.json()["block_count"] == 1

    create_response = await client.post("/api/purpose-executions", json=payload)
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["task_status"] == "pending"
    assert created["round_number"] == 1
    task_response = await client.get(f"/api/tasks/{created['task_id']}")
    assert task_response.status_code == 200
    assert task_response.json()["purpose_execution_id"] == created["id"]

    list_response = await client.get("/api/purpose-executions", params={"feature": "API"})
    assert list_response.status_code == 200
    assert [row["id"] for row in list_response.json()] == [created["id"]]
    detail_response = await client.get(f"/api/purpose-executions/{created['id']}")
    assert detail_response.status_code == 200
    delete_response = await client.delete(f"/api/mapping/purposes/{purpose.id}")
    assert delete_response.status_code == 409
    assert detail_response.json()["purpose_name"] == "API 目的"


@pytest.mark.asyncio
async def test_pipeline_keeps_blocked_without_logs_and_rejects_multi_suite(
    db_session, memory_s3
):
    version = TestVersion(version_name="R-pipeline")
    db_session.add(version)
    await db_session.flush()
    purpose = TestPurpose(version_id=version.id, name="多来源分析")
    db_session.add(purpose)
    await db_session.flush()
    base = "R-pipeline/task-a/node-a"
    valid_upload = f"{base}/block-valid/upload"
    invalid_upload = f"{base}/block-invalid/upload"
    preview = {
        "external_task_id": "external-pipeline",
        "raw_json": "{}",
        "leaf_count": 1,
        "block_count": 2,
        "warnings": [],
        "sources": [{
            "name": "Feature A",
            "task_id": "task-a",
            "discovery_order": 0,
            "errors": ["one node could not be listed"],
            "blocks": [
                {"node_id": "node-a", "task_block_id": "block-valid", "upload_path": valid_upload, "summary_path": f"{valid_upload}/metadata/summary_report.yaml", "discovery_order": 0},
                {"node_id": "node-a", "task_block_id": "block-invalid", "upload_path": invalid_upload, "summary_path": f"{invalid_upload}/metadata/summary_report.yaml", "discovery_order": 1},
            ],
        }],
    }
    execution, task = await persist_execution_preview(db_session, purpose, preview)
    memory_s3.files.update({
        f"{valid_upload}/metadata/summary_report.yaml": """
testsuites:
  - id: suite-valid
    desc: Valid suite
    result: failed
    testcases:
      - id: BLOCKED-1
        result: blocked
        fail_detail: no environment
      - id: UNKNOWN-1
        result: infra_error
""",
        f"{invalid_upload}/metadata/summary_report.yaml": """
testsuites:
  - id: suite-a
    testcases: []
  - id: suite-b
    testcases: []
""",
        f"{invalid_upload}/artifacts/testsuite/unmatched.html": "<html><body>plain log</body></html>",
    })
    memory_s3.dirs.update({
        f"{valid_upload}/artifacts/testsuite": [],
        f"{valid_upload}/artifacts/testcases": [],
        f"{invalid_upload}/artifacts/testsuite": [
            DirEntry(name="unmatched.html", type="file", path=f"{invalid_upload}/artifacts/testsuite/unmatched.html")
        ],
        f"{invalid_upload}/artifacts/testcases": [],
    })

    terminal = await run_execution_pipeline(task, db_session)
    await db_session.commit()
    assert terminal == "completed_with_warnings"
    assert execution.sources[0].status == "completed_with_warnings"
    assert "one node could not be listed" in task.error_message
    assert task.total_testcases == 2
    rows = {row["case_id"]: row for row in await load_testcase_rows(db_session, execution.id)}
    assert rows["BLOCKED-1"]["last_normalized_status"] == "blocked"
    assert rows["BLOCKED-1"]["log_file_id"] is None
    assert rows["UNKNOWN-1"]["last_normalized_status"] == "unknown"
    suites = await suite_rows(db_session, execution.id)
    invalid = next(row for row in suites if row["task_block_id"] == "block-invalid")
    assert invalid["block_status"] == "multiple_suites"
    assert invalid["suite_name"] is None
    assert len(invalid["logs"]) == 1


@pytest.mark.asyncio
async def test_pipeline_fails_when_every_summary_is_missing_or_corrupt(db_session, memory_s3):
    version = TestVersion(version_name="R-failed")
    db_session.add(version)
    await db_session.flush()
    purpose = TestPurpose(version_id=version.id, name="异常汇总")
    db_session.add(purpose)
    await db_session.flush()
    preview = {
        "external_task_id": "external-failed",
        "raw_json": "{}",
        "leaf_count": 1,
        "block_count": 2,
        "warnings": [],
        "sources": [{
            "name": "Feature failed",
            "task_id": "source-failed",
            "discovery_order": 0,
            "errors": [],
            "blocks": [
                {"node_id": "node", "task_block_id": "missing", "upload_path": "missing/upload", "summary_path": "missing/upload/metadata/summary_report.yaml", "discovery_order": 0},
                {"node_id": "node", "task_block_id": "corrupt", "upload_path": "corrupt/upload", "summary_path": "corrupt/upload/metadata/summary_report.yaml", "discovery_order": 1},
            ],
        }],
    }
    execution, task = await persist_execution_preview(db_session, purpose, preview)
    memory_s3.files["corrupt/upload/metadata/summary_report.yaml"] = "testsuites: [unterminated"
    for upload in ("missing/upload", "corrupt/upload"):
        memory_s3.dirs[f"{upload}/artifacts/testsuite"] = []
        memory_s3.dirs[f"{upload}/artifacts/testcases"] = []

    terminal = await run_execution_pipeline(task, db_session)
    await db_session.commit()
    assert terminal == "failed"
    assert task.error_message
    rows = await suite_rows(db_session, execution.id)
    assert {row["block_status"] for row in rows} == {"missing_summary", "invalid_summary"}


@pytest.mark.asyncio
async def test_case_aggregation_preserves_duplicates_and_selects_latest(db_session, client):
    version = TestVersion(version_name="R1")
    db_session.add(version)
    await db_session.flush()
    purpose = TestPurpose(version_id=version.id, name="回归")
    db_session.add(purpose)
    await db_session.flush()

    e1, _, _, b1, s1 = await _execution(db_session, purpose, 1, "首次特性", "block-a", "旧套件")
    db_session.add_all([
        CaseOccurrence(task_block_id=b1.id, suite_id=s1.id, case_id="CASE-1", case_name="case one", raw_result="failed", normalized_status="failed", end_time="2026-07-20 10:00:00", discovery_order=0),
        CaseOccurrence(task_block_id=b1.id, suite_id=s1.id, case_id="DUP", raw_result="success", normalized_status="success", end_time="2026-07-20 10:01:00", discovery_order=1),
        CaseOccurrence(task_block_id=b1.id, suite_id=s1.id, case_id="DUP", raw_result="failed", normalized_status="failed", end_time="2026-07-20 10:02:00", discovery_order=2),
    ])

    e2, task2, source2, b2, s2 = await _execution(db_session, purpose, 2, "后续特性", "block-b", "最终套件")
    b2.discovery_order = 1
    override_category = Category(name="人工根因")
    db_session.add(override_category)
    await db_session.flush()
    latest_log = LogFile(
        task_id=task2.id,
        name="case-1.html",
        file_path=f"{b2.upload_path}/artifacts/testcases/CASE-1/main/case-1.html",
        source_dir=f"{b2.upload_path}/artifacts/testcases/CASE-1/main",
        file_type="testcase",
        testcase_name="CASE-1",
        review_status="overridden",
        override_category_id=override_category.id,
    )
    db_session.add(latest_log)
    await db_session.flush()
    db_session.add_all([
        CaseOccurrence(task_block_id=b2.id, suite_id=s2.id, case_id="CASE-1", raw_result="success", normalized_status="success", end_time=None, discovery_order=0, log_file_id=latest_log.id),
        CaseOccurrence(task_block_id=b2.id, suite_id=s2.id, case_id="NEW", raw_result="mystery", normalized_status="unknown", end_time=None, discovery_order=1),
        CaseOccurrence(task_block_id=b2.id, suite_id=s2.id, case_id="PATH/CASE", raw_result="success", normalized_status="success", end_time=None, discovery_order=2),
    ])
    await db_session.commit()

    rows = {row["case_id"]: row for row in await load_testcase_rows(db_session, e2.id)}
    assert rows["CASE-1"]["execution_count"] == 2
    assert rows["CASE-1"]["first_feature"] == "首次特性"
    assert rows["CASE-1"]["last_suite"] == "最终套件"
    assert rows["CASE-1"]["last_normalized_status"] == "success"
    assert rows["CASE-1"]["final_root_cause"] == "人工根因"
    assert rows["CASE-1"]["review_status"] == "overridden"
    assert rows["CASE-1"]["log_file_id"] == latest_log.id
    assert rows["DUP"]["execution_count"] == 2
    assert rows["DUP"]["last_normalized_status"] == "failed"
    assert rows["NEW"]["last_normalized_status"] == "unknown"

    history = await load_testcase_history(db_session, e2.id, "CASE-1")
    assert [item["round_number"] for item in history] == [1, 2]
    assert history[-1]["task_block_id"] == "block-b"
    assert history[-1]["review_status"] == "overridden"
    assert history[-1]["log_file_id"] == latest_log.id

    response = await client.get(
        f"/api/purpose-executions/{e2.id}/testcase-history",
        params={"case_id": "PATH/CASE"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["normalized_status"] == "success"


@pytest.mark.asyncio
async def test_suite_blocked_requires_every_case_explicitly_blocked(db_session):
    version = TestVersion(version_name="R2")
    db_session.add(version)
    await db_session.flush()
    purpose = TestPurpose(version_id=version.id, name="阻塞验证")
    db_session.add(purpose)
    await db_session.flush()
    execution, _, _, block, suite = await _execution(
        db_session, purpose, 1, "Feature", "blocked-block", "Blocked suite"
    )
    suite.total_count = 2
    suite.blocked_count = 2
    suite.unknown_count = 0
    db_session.add_all([
        CaseOccurrence(task_block_id=block.id, suite_id=suite.id, case_id="B-1", raw_result="blocked", normalized_status="blocked", discovery_order=0),
        CaseOccurrence(task_block_id=block.id, suite_id=suite.id, case_id="B-2", raw_result="blocked", normalized_status="blocked", discovery_order=1),
    ])
    await db_session.commit()

    rows = await suite_rows(db_session, execution.id)
    assert rows[0]["suite_blocked"] is True
    assert rows[0]["unknown"] == 0
    assert rows[0]["environment"] is None

    suite.blocked_count = 1
    suite.unknown_count = 1
    await db_session.commit()
    rows = await suite_rows(db_session, execution.id)
    assert rows[0]["suite_blocked"] is False


@pytest.mark.asyncio
async def test_overview_keeps_legacy_cases_not_present_in_rerun(db_session, tmp_path):
    version = TestVersion(version_name="R-overview")
    db_session.add(version)
    await db_session.flush()
    purpose = TestPurpose(version_id=version.id, name="总览")
    db_session.add(purpose)
    await db_session.flush()
    legacy = Task(name="legacy", source_type="upload", status="completed")
    db_session.add(legacy)
    await db_session.flush()
    upload = tmp_path / "upload"
    summary_dir = upload / "metadata"
    summary_dir.mkdir(parents=True)
    (summary_dir / "summary_report.yaml").write_text("""
testsuites:
  - id: old-suite
    testcases:
      - id: CASE-1
        result: failed
      - id: CASE-OLD
        result: blocked
""", encoding="utf-8")
    db_session.add(LogFile(
        task_id=legacy.id,
        name="CASE-1.html",
        file_path=str(upload / "artifacts/testcases/CASE-1/main/CASE-1.html"),
        source_dir=str(upload / "artifacts/testcases/CASE-1/main"),
        file_type="testcase",
        testcase_name="CASE-1",
    ))
    execution, _, _, block, suite = await _execution(
        db_session, purpose, 1, "Feature", "rerun-block", "Rerun suite"
    )
    db_session.add(CaseOccurrence(
        task_block_id=block.id,
        suite_id=suite.id,
        case_id="CASE-1",
        raw_result="success",
        normalized_status="success",
        discovery_order=0,
    ))
    await db_session.commit()

    statuses = await build_latest_case_statuses(db_session, [legacy], [purpose.id])
    assert statuses == {"CASE-1": "success", "CASE-OLD": "blocked"}
    report = {"results": {}}
    apply_latest_case_counts(report, statuses)
    assert report["results"] == {
        "total": 2, "success": 1, "failed": 0, "blocked": 1, "unknown": 0,
    }
