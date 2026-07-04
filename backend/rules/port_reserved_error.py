from __future__ import annotations

import re

from rules.base import BaseRule, RuleContext, RuleResult

# 形如 "RuntimeError: xxxxx Port xxxx reserved error."
PATTERN = re.compile(r'RuntimeError:.*\bPort\b.*\breserved error\b', re.IGNORECASE)


class PortReservedErrorRule(BaseRule):
    """规则 3：端口占用失败。

    失败块中出现 "RuntimeError: ... Port ... reserved error." 即匹配。
    优先级高于通用的 runtime_error 规则，使该类 RuntimeError 优先归入
    端口占用失败而不是未知问题。
    """

    @property
    def rule_id(self) -> str:
        return "port_reserved_error"

    @property
    def name(self) -> str:
        return "端口占用检测"

    @property
    def category(self) -> str:
        return "产品问题/端口占用失败"

    @property
    def priority(self) -> int:
        return 15

    @property
    def description(self) -> str:
        return "失败块中出现 'RuntimeError: ... Port ... reserved error.' 时归类为产品问题/端口占用失败"

    async def evaluate(self, ctx: RuleContext) -> RuleResult:
        block = ctx.failure_event.get("relevant_log") or ctx.traceback or ""
        hit_line = next(
            (line.strip() for line in block.split("\n") if PATTERN.search(line)),
            None,
        )
        if hit_line is None:
            return RuleResult.no_match()

        return RuleResult.match(
            category=self.category,
            confidence=0.9,
            evidence=hit_line,
            line_start=ctx.failure_event.get("line_start"),
            line_end=ctx.failure_event.get("line_end"),
        )
