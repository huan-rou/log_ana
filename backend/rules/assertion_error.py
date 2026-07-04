from __future__ import annotations

from rules.base import BaseRule, RuleContext, RuleResult

MARKER = "AssertionError:"


class AssertionErrorRule(BaseRule):
    """规则 1：html 文件中的断言失败。

    仅适用于 html 文件；优先级最高（最先裁决）。
    失败块（连续红色文本）中包含 "AssertionError: xxx" 即匹配；
    含该字符串的第一个块由执行器的排序键自动成为根因（最终结论）。
    """

    @property
    def rule_id(self) -> str:
        return "assertion_error"

    @property
    def name(self) -> str:
        return "断言失败检测"

    @property
    def category(self) -> str:
        return "产品问题/断言失败"

    @property
    def priority(self) -> int:
        return 10

    @property
    def description(self) -> str:
        return "html 日志红色块中出现 'AssertionError: xxx' 时归类为产品问题/断言失败"

    async def evaluate(self, ctx: RuleContext) -> RuleResult:
        log_file = ctx.failure_event.get("log_file") or {}
        if not str(log_file.get("name", "")).lower().endswith((".html", ".htm")):
            return RuleResult.no_match()

        block = ctx.failure_event.get("relevant_log") or ctx.traceback or ""
        if MARKER not in block:
            return RuleResult.no_match()

        hit_line = next(
            (line.strip() for line in block.split("\n") if MARKER in line),
            MARKER,
        )
        return RuleResult.match(
            category=self.category,
            confidence=0.9,
            evidence=hit_line,
            line_start=ctx.failure_event.get("line_start"),
            line_end=ctx.failure_event.get("line_end"),
        )
