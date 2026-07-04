from __future__ import annotations

import re

from rules.base import BaseRule, RuleContext, RuleResult

# 匹配 "The test module firmware version is xxxxxxxx   Please use the xxxxxxxx GUI to reserve the ports."
PATTERN = re.compile(
    r"The test module firmware version is\s+.+?Please use the\s+.+?GUI to reserve the ports",
    re.IGNORECASE,
)


class FirmwareVersionMismatchRule(BaseRule):
    """规则：固件版本不匹配。

    失败块中出现 "The test module firmware version is ... Please use the ... GUI to reserve the ports."
    即匹配。优先级介于 port_reserved_error (15) 和 runtime_error (20) 之间，
    确保该 RuntimeError 归入版本不匹配而不是端口占用失败或未知问题。
    """

    @property
    def rule_id(self) -> str:
        return "firmware_version_mismatch"

    @property
    def name(self) -> str:
        return "固件版本不匹配检测"

    @property
    def category(self) -> str:
        return "环境问题/版本不匹配"

    @property
    def priority(self) -> int:
        return 16

    @property
    def description(self) -> str:
        return (
            "失败块中出现 'The test module firmware version is ... "
            "Please use the ... GUI to reserve the ports.' 时归类为环境问题/版本不匹配"
        )

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
