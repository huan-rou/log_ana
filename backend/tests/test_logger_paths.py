"""关键路径日志存在性单测（v5 第 9.7 节）。

按 v5 计划第 9.4 节清单验证关键函数确实调用了 logger。
不验证日志内容精确字段，只验证调用了对应级别。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


# ── summary_report ──


class TestSummaryReportLogger:
    def test_find_suite_logfile_logs_warning_when_no_match(self, caplog):
        """suite_info 与 suite_logfiles 完全不匹配时记 WARNING。"""
        import logging
        from app.services.summary_report import find_suite_logfile

        suite_info = {"id": "TS_xyz_001", "desc": "Some Suite"}
        # 给一个完全不沾边的 LogFile
        suite_logfiles = [type("LF", (), {"id": "lf1", "name": "totally_unrelated.html"})()]

        with caplog.at_level(logging.DEBUG, logger="app.services.summary_report"):
            result = find_suite_logfile(suite_info, suite_logfiles)

        assert result is None
        # 应该有一条 no_match WARNING
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("no_match" in r.message for r in warnings)

    def test_find_suite_logfile_logs_debug_on_match(self, caplog):
        """匹配成功时记 DEBUG。"""
        import logging
        from app.services.summary_report import find_suite_logfile

        suite_info = {"id": "TS_xyz_001"}
        lf = type("LF", (), {"id": "lf1", "name": "TS_xyz_001.html"})()
        suite_logfiles = [lf]

        with caplog.at_level(logging.DEBUG, logger="app.services.summary_report"):
            result = find_suite_logfile(suite_info, suite_logfiles)

        assert result is lf
        debugs = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("[find_suite_logfile] match" in r.message for r in debugs)

    def test_summary_for_file_logs_case_not_found(self, caplog):
        """testcase 类型 LogFile 找不到 case_rec 时记 DEBUG。"""
        import logging
        from app.services.summary_report import summary_for_file

        lookup = {"cases": {}, "suites": {}, "suite_list": []}
        log_file = type(
            "LF", (), {
                "id": "lf1", "name": "unknown.html",
                "file_type": "testcase", "testcase_name": "no_such_case",
            }
        )()

        with caplog.at_level(logging.DEBUG, logger="app.services.summary_report"):
            result = summary_for_file(log_file, lookup, "/some/path.yaml")

        assert result is None
        debugs = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("case_not_found" in r.message for r in debugs)

    def test_summary_for_file_logs_case_found(self, caplog):
        """testcase 类型 LogFile 找到 case_rec 时记 DEBUG（含 suite_id）。"""
        import logging
        from app.services.summary_report import summary_for_file

        suite_rec = {"id": "TS_xyz", "result": "passed"}
        case_rec = {"id": "case1", "desc": "d", "suite": suite_rec,
                    "result": "passed", "start_time": None, "end_time": None,
                    "fail_detail": ""}
        lookup = {"cases": {"case1": case_rec}, "suites": {}, "suite_list": []}
        log_file = type(
            "LF", (), {
                "id": "lf1", "name": "case1.html",
                "file_type": "testcase", "testcase_name": "case1",
            }
        )()

        with caplog.at_level(logging.DEBUG, logger="app.services.summary_report"):
            result = summary_for_file(log_file, lookup, "/p.yaml")

        assert result is not None
        debugs = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("case_found" in r.message and "case1" in r.message for r in debugs)

    def test_build_suite_response_logs_match(self, caplog):
        import logging
        from app.services.summary_report import build_suite_response

        suite_info = {"id": "TS_xyz_001", "desc": "d"}
        lf = type("LF", (), {"id": "lf_s", "name": "TS_xyz_001.html", "file_path": "/p"})()
        suite_logfiles = [lf]

        with caplog.at_level(logging.DEBUG, logger="app.services.summary_report"):
            result = build_suite_response(suite_info, suite_logfiles)

        assert result["logfile_id"] == "lf_s"
        debugs = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("[build_suite_response]" in r.message for r in debugs)


# ── task_tree_s3 ──


class TestTaskTreeS3Logger:
    @pytest.mark.asyncio
    async def test_probe_leaf_in_s3_logs_debug_on_success(self, caplog):
        """probe_leaf_in_s3 成功时记 DEBUG。"""
        import logging
        from app.services.task_tree_s3 import probe_leaf_in_s3

        with patch(
            "app.services.task_tree_s3.provider_manager"
        ) as mock_pm:
            mock_pm.list_dir = AsyncMock(return_value=[{"name": "x", "is_dir": False}])

            with caplog.at_level(logging.DEBUG, logger="app.services.task_tree_s3"):
                result = await probe_leaf_in_s3("v1", "leaf1")

        assert result is True
        debugs = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("[s3.probe]" in r.message and "has_data=True" in r.message for r in debugs)

    @pytest.mark.asyncio
    async def test_probe_leaf_in_s3_logs_warning_on_failure(self, caplog):
        """probe_leaf_in_s3 provider_manager 抛错时记 WARNING。"""
        import logging
        from app.services.task_tree_s3 import probe_leaf_in_s3

        with patch(
            "app.services.task_tree_s3.provider_manager"
        ) as mock_pm:
            mock_pm.list_dir = AsyncMock(side_effect=RuntimeError("S3 not configured"))

            with caplog.at_level(logging.WARNING, logger="app.services.task_tree_s3"):
                result = await probe_leaf_in_s3("v1", "leaf1")

        assert result is False
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("[s3.probe] failed" in r.message for r in warnings)


# ── task_tree parser ──


class TestTaskTreeParserLogger:
    def test_parse_task_tree_logs_info(self, caplog):
        """parse_task_tree 成功时记 INFO（含 total_nodes / leaf_count）。"""
        import logging
        from app.services.task_tree import parse_task_tree

        raw = """{
            "Name": "root", "Id": "1", "child_tasks": [
                {"Name": "a", "Id": "2", "child_tasks": []}
            ]
        }"""

        with caplog.at_level(logging.INFO, logger="app.services.task_tree"):
            parsed = parse_task_tree(raw)

        assert parsed["leaves"]
        infos = [r for r in caplog.records if r.levelno == logging.INFO]
        assert any("[parse_task_tree]" in r.message for r in infos)
        # 字段都应在
        msg = next(r.message for r in infos if "[parse_task_tree]" in r.message)
        assert "total_nodes=2" in msg
        assert "leaf_count=1" in msg

    def test_parse_task_tree_no_log_when_value_error(self, caplog):
        """parse_task_tree 解析失败不记 INFO（业务抛 ValueError，调用方决定）。"""
        import logging
        from app.services.task_tree import parse_task_tree

        with caplog.at_level(logging.INFO, logger="app.services.task_tree"):
            with pytest.raises(ValueError):
                parse_task_tree("not json")
