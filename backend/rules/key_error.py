from __future__ import annotations

from rules.base import BaseRule, RuleContext, RuleResult

MARKER = "KeyError:"


class KeyErrorRule(BaseRule):
    """规则：KeyError 异常。

    失败块中出现 "KeyError: xxx" 即匹配。
    优先级（18）介于 firmware_version_mismatch (16) 和 runtime_error (20) 之间，
    确保 KeyError 归入修改引入问题而非未知问题。
    """

    @property
    def rule_id(self) -> str:
        return "key_error"

    @property
    def name(self) -> str:
        return "KeyError 检测"

    @property
    def category(self) -> str:
        return "产品问题/修改引入问题"

    @property
    def priority(self) -> int:
        return 18

    @property
    def description(self) -> str:
        return "失败块中出现 'KeyError: xxx' 时归类为产品问题/修改引入问题"

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
            confidence=0.85,
            evidence=hit_line,
            line_start=ctx.failure_event.get("line_start"),
            line_end=ctx.failure_event.get("line_end"),
        )
