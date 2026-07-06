"""S3 探测单测：mock provider_manager.list_dir 覆盖各分支。"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services.storage.base import DirEntry
from app.services.task_tree_s3 import (
    _build_probe_path,
    probe_leaf_in_s3,
    probe_leaves_in_s3_batch,
)


def _entry(name: str, is_dir: bool = True) -> DirEntry:
    return DirEntry(name=name, type="directory" if is_dir else "file", path=name)


# ── _build_probe_path 路径构造 ──


class TestBuildProbePath:
    def test_basic(self):
        assert _build_probe_path("1.2.3", "abc") == "1.2.3/abc/"

    def test_strip_slashes(self):
        assert _build_probe_path("/1.2.3/", "/abc/") == "1.2.3/abc/"

    def test_chinese(self):
        assert _build_probe_path("v1", "统计分析__2") == "v1/统计分析__2/"

    def test_empty_version_raises(self):
        with pytest.raises(ValueError, match="不能为空"):
            _build_probe_path("", "abc")

    def test_empty_leaf_raises(self):
        with pytest.raises(ValueError, match="不能为空"):
            _build_probe_path("1.2.3", "")


# ── probe_leaf_in_s3 单个探测 ──


class TestProbeLeafInS3:
    @patch("app.services.task_tree_s3.provider_manager")
    async def test_has_data_when_entries_nonempty(self, mock_pm):
        mock_pm.list_dir = AsyncMock(return_value=[_entry("upload"), _entry("raw")])
        result = await probe_leaf_in_s3("1.2.3", "abc")
        assert result is True
        mock_pm.list_dir.assert_awaited_once_with("s3", "1.2.3/abc/")

    @patch("app.services.task_tree_s3.provider_manager")
    async def test_no_data_when_empty(self, mock_pm):
        mock_pm.list_dir = AsyncMock(return_value=[])
        result = await probe_leaf_in_s3("1.2.3", "abc")
        assert result is False

    @patch("app.services.task_tree_s3.provider_manager")
    async def test_no_data_on_timeout(self, mock_pm):
        async def slow(*_args, **_kw):
            await asyncio.sleep(10)
        mock_pm.list_dir = slow
        result = await probe_leaf_in_s3("1.2.3", "abc", timeout=0.1)
        assert result is False

    @patch("app.services.task_tree_s3.provider_manager")
    async def test_no_data_on_exception(self, mock_pm):
        mock_pm.list_dir = AsyncMock(side_effect=RuntimeError("S3 not configured"))
        result = await probe_leaf_in_s3("1.2.3", "abc")
        assert result is False

    @patch("app.services.task_tree_s3.provider_manager")
    async def test_only_files_count(self, mock_pm):
        # 只列文件（无子目录）也算有数据
        mock_pm.list_dir = AsyncMock(return_value=[_entry("a.html", is_dir=False)])
        result = await probe_leaf_in_s3("1.2.3", "abc")
        assert result is True


# ── probe_leaves_in_s3_batch 并发探测 ──


class TestProbeLeavesInS3Batch:
    @patch("app.services.task_tree_s3.provider_manager")
    async def test_mixed_results(self, mock_pm):
        async def fake_list_dir(provider, path):
            await asyncio.sleep(0)
            # 按 path 决定返回：有 "1.2.3/hasdata/" 才有数据
            if "hasdata" in path:
                return [_entry("upload")]
            return []

        mock_pm.list_dir = fake_list_dir
        result = await probe_leaves_in_s3_batch("1.2.3", ["hasdata", "nodata", "alsogood"])
        assert result == {"hasdata": True, "nodata": False, "alsogood": False}

    @patch("app.services.task_tree_s3.provider_manager")
    async def test_empty_input(self, mock_pm):
        result = await probe_leaves_in_s3_batch("1.2.3", [])
        assert result == {}
        mock_pm.list_dir.assert_not_called()

    @patch("app.services.task_tree_s3.provider_manager")
    async def test_all_timeout_become_false(self, mock_pm):
        async def slow(*_args, **_kw):
            await asyncio.sleep(10)
        mock_pm.list_dir = slow
        result = await probe_leaves_in_s3_batch("1.2.3", ["a", "b", "c"], timeout=0.1)
        assert result == {"a": False, "b": False, "c": False}

    @patch("app.services.task_tree_s3.provider_manager")
    async def test_partial_exception(self, mock_pm):
        async def fake(provider, path):
            if "bad" in path:
                raise RuntimeError("boom")
            return [_entry("upload")]
        mock_pm.list_dir = fake
        result = await probe_leaves_in_s3_batch("1.2.3", ["good", "bad", "alsogood"])
        assert result == {"good": True, "bad": False, "alsogood": True}
