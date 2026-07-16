import pytest

from app.core.audit_logger import AuditLogger, REPORT_AUDIT_SCHEMA


@pytest.mark.asyncio
async def test_rule_statistics_requires_current_run_marker(tmp_path):
    logger = AuditLogger(str(tmp_path / "audit"))

    await logger.rule_evaluate("legacy", rule_id="old_rule", matched=True)
    legacy = logger.collect_rule_statistics(["legacy"])
    assert legacy["available"] is False
    assert legacy["rules"] == {}

    await logger.reset_task("current")
    await logger.pipeline_start("current", report_audit_schema=REPORT_AUDIT_SCHEMA)
    await logger.rule_evaluate("current", rule_id="current_rule", matched=True)
    await logger.rule_evaluate("current", rule_id="current_rule", matched=False, error="timeout")

    current = logger.collect_rule_statistics(["current"])
    assert current["available"] is True
    assert current["rules"] == {
        "current_rule": {"evaluations": 2, "matches": 1, "errors": 1}
    }
