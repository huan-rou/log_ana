from __future__ import annotations

from rules.base import BaseRule, RuleContext, RuleResult

MARKER = "RuntimeError:"


class RuntimeErrorRule(BaseRule):
    """规则 2：运行时错误。

    失败块中包含 "RuntimeError: xxx" 即匹配；含该字符串的第一个块
    （在没有更高优先级规则匹配时）成为根因。
    """

    @property
    def rule_id(self) -> str:
        return "runtime_error"

    @property
    def name(self) -> str:
        return "运行时错误检测"

    @property
    def category(self) -> str:
        return "产品问题/未知问题"

    @property
    def priority(self) -> int:
        return 20

    @property
    def description(self) -> str:
        return "日志失败块中出现 'RuntimeError: xxx' 时归类为产品问题/未知问题"

    async def evaluate(self, ctx: RuleContext) -> RuleResult:
        block = ctx.failure_event.get("relevant_log") or ctx.traceback or ""
        if MARKER not in block:
            return RuleResult.no_match()

        hit_line = next(
            (line.strip() for line in block.split("\n") if MARKER in line),
            MARKER,
        )
        return RuleResult.match(
            category=self.category,
            confidence=0.8,
            evidence=hit_line,
            line_start=ctx.failure_event.get("line_start"),
            line_end=ctx.failure_event.get("line_end"),
        )
