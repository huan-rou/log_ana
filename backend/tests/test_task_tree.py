"""任务树解析器单测。

覆盖 v5 计划中以下场景：
- 3 层/1 层 JSON 解析
- 字段大小写不敏感
- 叶子识别（child_tasks = [] / 缺失 / null）
- 节点 extra 字段保存
- name_key 提取规则（4 种边界）
- 解析错误（顶层不是对象 / 缺 Id / child_tasks 非数组 / 同树 Id 重复）
"""
from __future__ import annotations

import pytest

from app.services.task_tree import (
    compute_name_key,
    parse_task_tree,
)


# ── name_key 提取（rsplit 规则：切最后一段）──


class TestNameKey:
    def test_no_underscore_keeps_full(self):
        # 无下划线时整段保留
        assert compute_name_key("TC") == "TC"

    def test_simple_one_underscore(self):
        # 一个下划线切最后一段
        assert compute_name_key("TC_id") == "TC"

    def test_two_underscores_chop_last(self):
        # 多个下划线也只切最后一段
        assert compute_name_key("TC_id_1") == "TC_id"

    def test_three_underscores_chop_last(self):
        assert compute_name_key("TC_id_1_a8b3c") == "TC_id_1"

    def test_chinese_double_underscore(self):
        # "统计分析__2" → "统计分析_"
        assert compute_name_key("统计分析__2") == "统计分析_"

    def test_chinese_with_hex_suffix(self):
        assert compute_name_key("统计分析__2_x9y2z") == "统计分析__2"

    def test_known_misbehavior_bgp0(self):
        # 已知误伤：BGP0_reRun6458 被切成 BGP0（基础名被切）
        # v5 接受这个误伤；后续可加"测试系统后缀白名单"改进
        assert compute_name_key("BGP0_reRun6458") == "BGP0"

    def test_empty_string(self):
        assert compute_name_key("") == ""


# ── 3 层 JSON 解析（example_task_result.json 风格）──


class TestParseThreeLayer:
    def test_basic(self):
        raw = """{
            "Name": "S1-10G-8S28/R45_B2B_part1",
            "Id": "3806765545196879872",
            "child_tasks": [
                {
                    "Name": "parallel test root node 0",
                    "Id": "3806765545196879873",
                    "child_tasks": [
                        {"Name": "802.1X__0", "Id": "3806765545196879874", "child_tasks": []}
                    ]
                },
                {
                    "Name": "parallel test root node 2",
                    "Id": "3806765545196879895",
                    "child_tasks": [
                        {"Name": "统计分析__2", "Id": "3806765545196879896", "child_tasks": []}
                    ]
                }
            ]
        }"""
        result = parse_task_tree(raw)
        # 总节点 5（1 root + 2 中间 + 2 叶子）
        assert len(result["nodes"]) == 5
        # 2 个叶子
        assert len(result["leaves"]) == 2
        # 叶子 Id
        leaf_ids = {lf["node_id"] for lf in result["leaves"]}
        assert leaf_ids == {"3806765545196879874", "3806765545196879896"}
        # 根 name_key = "S1-10G-8S28/R45_B2B_part1"（无 _ 保留完整）
        root = result["tree"]
        assert root["name"] == "S1-10G-8S28/R45_B2B_part1"
        assert root["depth"] == 0
        # 中间节点
        assert len(root["children"]) == 2

    def test_name_key_for_chinese_leaf(self):
        raw = """{
            "Name": "统计分析__2",
            "Id": "3806765545196879896",
            "child_tasks": []
        }"""
        result = parse_task_tree(raw)
        node = result["nodes"][0]
        # rsplit 切最后一段 → "统计分析_"
        assert node["name_key"] == "统计分析_"
        assert node["is_leaf"] is True


# ── 1 层 JSON 解析（example_task_result2.json 风格）──


class TestParseOneLayer:
    def test_top_is_leaf(self):
        raw = """{
            "Name": "BGP0_reRun6458",
            "Id": "369434831527713776",
            "child_tasks": []
        }"""
        result = parse_task_tree(raw)
        assert len(result["nodes"]) == 1
        assert len(result["leaves"]) == 1
        node = result["nodes"][0]
        assert node["is_leaf"] is True
        assert node["depth"] == 0
        # rsplit 切最后一段 → "BGP0"（已知误伤）
        assert node["name_key"] == "BGP0"

    def test_missing_child_tasks_treated_as_leaf(self):
        raw = """{"Name": "X", "Id": "123"}"""
        result = parse_task_tree(raw)
        assert result["nodes"][0]["is_leaf"] is True

    def test_null_child_tasks_treated_as_leaf(self):
        raw = """{"Name": "X", "Id": "123", "child_tasks": null}"""
        result = parse_task_tree(raw)
        assert result["nodes"][0]["is_leaf"] is True


# ── 字段大小写不敏感 ──


class TestCaseInsensitive:
    def test_lowercase_keys(self):
        raw = """{"name": "X", "id": "123", "child_tasks": []}"""
        result = parse_task_tree(raw)
        assert result["nodes"][0]["name"] == "X"
        assert result["nodes"][0]["node_id"] == "123"

    def test_mixed_case_keys(self):
        raw = """{"Name": "X", "ID": "123", "ChildTasks": []}"""
        result = parse_task_tree(raw)
        assert result["nodes"][0]["name"] == "X"
        assert result["nodes"][0]["node_id"] == "123"
        assert result["nodes"][0]["is_leaf"] is True

    def test_camelcase_childtasks(self):
        raw = """{"Name": "P", "Id": "1", "childTasks": [{"Name": "C", "Id": "2"}]}"""
        result = parse_task_tree(raw)
        assert len(result["nodes"]) == 2
        assert result["nodes"][1]["name"] == "C"


# ── extra 字段保存 ──


class TestExtraFields:
    def test_extra_preserved(self):
        raw = """{
            "Name": "X",
            "Id": "123",
            "child_tasks": [],
            "desc": "测试用例描述",
            "start_time": "2026-06-10 00:25:26",
            "fail_detail": "some error"
        }"""
        result = parse_task_tree(raw)
        node = result["nodes"][0]
        assert node["extra"] is not None
        import json
        extra = json.loads(node["extra"])
        assert extra["desc"] == "测试用例描述"
        assert extra["start_time"] == "2026-06-10 00:25:26"
        assert extra["fail_detail"] == "some error"
        # 解析过程记录所有非 Name/Id/child_tasks 字段
        assert "desc" in result["extra_fields_seen"]
        assert "start_time" in result["extra_fields_seen"]

    def test_no_extra_when_only_required_fields(self):
        raw = """{"Name": "X", "Id": "1", "child_tasks": []}"""
        result = parse_task_tree(raw)
        assert result["nodes"][0]["extra"] is None
        assert result["extra_fields_seen"] == []


# ── 解析错误 ──


class TestParseErrors:
    def test_empty_string(self):
        with pytest.raises(ValueError, match="为空"):
            parse_task_tree("")

    def test_invalid_json(self):
        with pytest.raises(ValueError, match="JSON 格式错误"):
            parse_task_tree("{not valid json")

    def test_top_level_not_object(self):
        with pytest.raises(ValueError, match="顶层必须是对象"):
            parse_task_tree("[]")

    def test_top_level_string(self):
        with pytest.raises(ValueError, match="顶层必须是对象"):
            parse_task_tree('"just a string"')

    def test_missing_id(self):
        with pytest.raises(ValueError, match="缺少字段"):
            parse_task_tree('{"Name": "X", "child_tasks": []}')

    def test_child_tasks_not_array(self):
        raw = """{"Name": "X", "Id": "1", "child_tasks": "not array"}"""
        with pytest.raises(ValueError, match="child_tasks 必须是数组"):
            parse_task_tree(raw)

    def test_duplicate_id_same_tree(self):
        raw = """{
            "Name": "P",
            "Id": "1",
            "child_tasks": [
                {"Name": "C1", "Id": "1"}
            ]
        }"""
        with pytest.raises(ValueError, match="Id 重复"):
            parse_task_tree(raw)

    def test_deep_duplicate_id_path_included(self):
        raw = """{
            "Name": "P1",
            "Id": "1",
            "child_tasks": [
                {"Name": "P2", "Id": "2", "child_tasks": [
                    {"Name": "P3", "Id": "1"}
                ]}
            ]
        }"""
        with pytest.raises(ValueError, match="/P1/P2/P3"):
            parse_task_tree(raw)


# ── sort_order 顺序 ──


class TestSortOrder:
    def test_children_get_correct_sort_order(self):
        raw = """{
            "Name": "P",
            "Id": "1",
            "child_tasks": [
                {"Name": "A", "Id": "2", "child_tasks": []},
                {"Name": "B", "Id": "3", "child_tasks": []},
                {"Name": "C", "Id": "4", "child_tasks": []}
            ]
        }"""
        result = parse_task_tree(raw)
        # 跳过根（P，sort_order 默认 0）
        children = sorted(
            [n for n in result["nodes"] if n["parent_id"]],
            key=lambda n: n["name"],
        )
        assert children[0]["name"] == "A"
        assert children[0]["sort_order"] == 0
        assert children[1]["name"] == "B"
        assert children[1]["sort_order"] == 1
        assert children[2]["name"] == "C"
        assert children[2]["sort_order"] == 2


# ── path 构建 ──


class TestPath:
    def test_root_path_starts_with_slash(self):
        raw = """{"Name": "Root", "Id": "1", "child_tasks": []}"""
        result = parse_task_tree(raw)
        assert result["nodes"][0]["path"] == "/Root"

    def test_nested_path(self):
        raw = """{
            "Name": "A",
            "Id": "1",
            "child_tasks": [
                {"Name": "B", "Id": "2", "child_tasks": [
                    {"Name": "C", "Id": "3", "child_tasks": []}
                ]}
            ]
        }"""
        result = parse_task_tree(raw)
        paths = [n["path"] for n in result["nodes"]]
        assert "/A" in paths
        assert "/A/B" in paths
        assert "/A/B/C" in paths
