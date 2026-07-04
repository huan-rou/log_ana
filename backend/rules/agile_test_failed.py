from __future__ import annotations

from rules.base import BaseRule, RuleContext, RuleResult

MARKER = "AssertionError: False is not true : Agile test run failed"


class AgileTestFailedRule(BaseRule):
    """规则：AgileTest 运行失败。

    失败块中出现 "AssertionError: False is not true : Agile test run failed" 即匹配。
    优先级（9）高于通用的 assertion_error（10），确保该特定断言优先归入
    AgileTest 失败而不是泛化的断言失败。
    """

    @property
    def rule_id(self) -> str:
        return "agile_test_failed"

    @property
    def name(self) -> str:
        return "AgileTest 失败检测"

    @property
    def category(self) -> str:
        return "产品问题/AgileTest失败"

    @property
    def priority(self) -> int:
        return 9

    @property
    def description(self) -> str:
        return "失败块中出现 'AssertionError: False is not true : Agile test run failed' 时归类为产品问题/AgileTest失败"

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
            confidence=0.95,
            evidence=hit_line,
            line_start=ctx.failure_event.get("line_start"),
            line_end=ctx.failure_event.get("line_end"),
        )
