from __future__ import annotations

from rules.base import BaseRule, RuleContext, RuleResult

MARKER_PRIMARY = "【环境加载】加载环境时发生异常"
MARKER_PORT = "ValueError: can not find free port to allocate in env"


class EnvLoadPortErrorRule(BaseRule):
    """规则：环境加载时端口分配失败。

    失败块中先出现 "【环境加载】加载环境时发生异常"，
    且同一块中包含 "ValueError: can not find free port to allocate in env" 时匹配。
    优先级（5）最高，确保该特定环境错误优先于所有泛化规则。
    """

    @property
    def rule_id(self) -> str:
        return "env_load_port_error"

    @property
    def name(self) -> str:
        return "环境加载端口分配失败检测"

    @property
    def category(self) -> str:
        return "环境问题/env.json异常"

    @property
    def priority(self) -> int:
        return 5

    @property
    def description(self) -> str:
        return (
            "失败块含 '【环境加载】加载环境时发生异常' 且 "
            "含 'ValueError: can not find free port to allocate in env' 时归类为环境问题/env.json异常"
        )

    async def evaluate(self, ctx: RuleContext) -> RuleResult:
        block = ctx.failure_event.get("relevant_log") or ctx.traceback or ""

        if MARKER_PRIMARY not in block:
            return RuleResult.no_match()
        if MARKER_PORT not in block:
            return RuleResult.no_match()

        # 以 ValueError 行作为核心证据；若无则回退到主标记行
        hit_line = next(
            (line.strip() for line in block.split("\n") if MARKER_PORT in line),
            None,
        )
        if hit_line is None:
            hit_line = next(
                (line.strip() for line in block.split("\n") if MARKER_PRIMARY in line),
                MARKER_PRIMARY,
            )

        return RuleResult.match(
            category=self.category,
            confidence=0.99,
            evidence=hit_line,
            line_start=ctx.failure_event.get("line_start"),
            line_end=ctx.failure_event.get("line_end"),
        )
