"""用户规则的 Python 源码模板渲染。

为什么用 str.replace 而不是 str.format？
  正则字符串里可能含 `{}`（如 `(?:a|b){2,3}`），用 .format() 会触发 KeyError
  或 IndexError。用 .replace 一一占位符替换最稳。

为什么用 ast.parse 二次校验？
  用户提交的任何内容都应在写盘前做一次语法检查；通过后再覆盖文件，
  失败则回滚，避免污染磁盘。
"""
from __future__ import annotations

import ast
import re
from typing import Any, Mapping


_USER_RULE_TEMPLATE = '''\
"""用户自定义规则 - 由规则编辑器自动生成，请勿手工修改元数据。

- rule_id:     {RULE_ID}
- name:        {NAME}
- category:    {CATEGORY}
- author:      {AUTHOR}
- created_at:  {CREATED_AT}
"""
from __future__ import annotations

import re

from rules.base import BaseRule, RuleContext, RuleResult

# 由编辑器注入；评估器按此字段取源文本
MATCH_SOURCE = "{MATCH_SOURCE}"  # relevant_log | traceback
PATTERN = re.compile(r"{PATTERN_ESCAPED}", re.IGNORECASE)
PATTERN_RAW = r"{PATTERN_ESCAPED}"


class {CLASS_NAME}(BaseRule):
    """{NAME}"""

    @property
    def rule_id(self) -> str:
        return "{RULE_ID}"

    @property
    def name(self) -> str:
        return "{NAME}"

    @property
    def category(self) -> str:
        return "{CATEGORY}"

    @property
    def priority(self) -> int:
        return {PRIORITY}

    @property
    def version(self) -> str:
        return "{VERSION}"

    @property
    def description(self) -> str:
        return "正则匹配：{PATTERN_DISPLAY}"

    async def evaluate(self, ctx: RuleContext) -> RuleResult:
        fe = ctx.failure_event or {}
        if MATCH_SOURCE == "traceback":
            block = ctx.traceback or ""
        else:
            block = fe.get("relevant_log") or ctx.traceback or ""
        if not block:
            return RuleResult.no_match()

        hit_line = next(
            (ln.strip() for ln in block.split("\\n") if PATTERN.search(ln)),
            None,
        )
        if hit_line is None:
            # fallback: 任意位置命中
            m = PATTERN.search(block)
            if m is None:
                return RuleResult.no_match()
            hit_line = m.group(0)

        return RuleResult.match(
            category=self.category,
            confidence={CONFIDENCE},
            evidence=hit_line[:512],
            line_start=fe.get("line_start"),
            line_end=fe.get("line_end"),
        )
'''


# 转义顺序：先把 `\` 替成 `\\`，再把 `"` 替成 `\"`
def _escape_for_double_quoted(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _to_pascal_class_name(snake: str) -> str:
    parts = [p for p in snake.split("_") if p]
    if not parts:
        raise ValueError("rule_id 不能为空")
    return "".join(p[:1].upper() + p[1:] for p in parts) + "UserRule"


def render_user_rule(meta: Mapping[str, Any]) -> str:
    """根据元数据渲染一段合法 Python 源码。

    Required keys in meta:
        rule_id, name, category, priority, confidence,
        match_source, pattern, version, author, created_at
    """
    required = (
        "rule_id", "name", "category", "priority", "confidence",
        "match_source", "pattern", "version", "author", "created_at",
    )
    missing = [k for k in required if k not in meta]
    if missing:
        raise ValueError(f"渲染规则缺少字段：{missing}")

    # 强制类型/取值
    rule_id = str(meta["rule_id"])
    name = str(meta["name"])
    category = str(meta["category"])
    priority = int(meta["priority"])
    confidence = float(meta["confidence"])
    match_source = str(meta["match_source"])
    pattern_raw = str(meta["pattern"])
    version = str(meta["version"])
    author = str(meta["author"])
    created_at = str(meta["created_at"])

    if not re.fullmatch(r"[a-z][a-z0-9_]*", rule_id):
        raise ValueError("rule_id 必须为 snake_case")
    if match_source not in ("relevant_log", "traceback"):
        raise ValueError("match_source 必须为 relevant_log 或 traceback")
    # 同步做一次 re.compile 校验
    try:
        re.compile(pattern_raw)
    except re.error as e:
        raise ValueError(f"正则非法：{e}") from e

    class_name = _to_pascal_class_name(rule_id)
    pattern_escaped = _escape_for_double_quoted(pattern_raw)
    pattern_display = pattern_escaped[:200]  # docstring 截断展示

    src = _USER_RULE_TEMPLATE
    src = src.replace("{RULE_ID}", rule_id)
    src = src.replace("{NAME}", _escape_for_double_quoted(name))
    src = src.replace("{CATEGORY}", _escape_for_double_quoted(category))
    src = src.replace("{AUTHOR}", _escape_for_double_quoted(author))
    src = src.replace("{CREATED_AT}", _escape_for_double_quoted(created_at))
    src = src.replace("{MATCH_SOURCE}", match_source)
    src = src.replace("{PATTERN_ESCAPED}", pattern_escaped)
    src = src.replace("{PATTERN_DISPLAY}", pattern_display)
    src = src.replace("{CLASS_NAME}", class_name)
    src = src.replace("{PRIORITY}", str(priority))
    src = src.replace("{CONFIDENCE}", repr(confidence))
    src = src.replace("{VERSION}", _escape_for_double_quoted(version))

    # 语法校验
    try:
        ast.parse(src)
    except SyntaxError as e:
        raise ValueError(f"渲染结果语法错误：{e}") from e

    return src


def safe_rule_id(rule_id: str) -> str:
    """把 rule_id 限制成模块名合法形式（防 path injection）。"""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", rule_id):
        raise ValueError("rule_id 必须为 snake_case")
    return rule_id
