from __future__ import annotations

from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from typing import Any, Optional


@dataclass
class RuleContext:
    """传递给每条规则脚本的上下文。

    包含一个失败事件的所有可用信息，规则可以根据需要从中提取。

    failure_event 额外包含：
      line_start / line_end — 失败块在源文件内的行号范围
      log_file — {"name", "file_type"(testsuite|testcase|task_log), "testcase_name"}
    """
    failure_event: dict  # FailureEvent 的字典表示
    log_entries: list[dict]  # 失败事件相关的日志条目
    traceback: str  # Python traceback 纯文本
    workspace_path: str  # 任务工作区路径（用于按需读取附加文件）
    extra_files: dict[str, str] = field(default_factory=dict)  # 已获取的附加文件内容 {filename: content}

    def get_log_field(self, field: str) -> Optional[str]:
        """从日志条目中提取字段值。"""
        for entry in self.log_entries:
            if field in entry and entry[field]:
                return str(entry[field])
        return None

    def get_extra_file(self, pattern: str) -> Optional[str]:
        """查找已获取的附加文件内容（模糊匹配文件名）。"""
        import re
        for filename, content in self.extra_files.items():
            if re.search(pattern, filename):
                return content
        return None


@dataclass
class RuleResult:
    """规则脚本返回的分析结果。

    category 支持 "大类/子类" 路径格式（如 "脚本缺陷/断言失败"）；
    仅写大类名时归入大类本身。详见 rules/RULE_GUIDE.md。
    """
    matched: bool
    category: Optional[str] = None  # 分类类别名称或 "大类/子类" 路径
    confidence: float = 0.0  # 0.0 ~ 1.0
    evidence: str = ""  # 匹配依据（应引用决定性的日志内容）
    line_start: Optional[int] = None  # 证据在源文件中的起始行号（缺省用失败事件的范围）
    line_end: Optional[int] = None  # 证据在源文件中的结束行号
    extractions: dict[str, Any] = field(default_factory=dict)  # 提取的结构化数据

    @staticmethod
    def no_match() -> "RuleResult":
        return RuleResult(matched=False)

    @staticmethod
    def match(category: str, confidence: float, evidence: str,
              line_start: Optional[int] = None, line_end: Optional[int] = None,
              **extractions) -> "RuleResult":
        return RuleResult(
            matched=True,
            category=category,
            confidence=confidence,
            evidence=evidence,
            line_start=line_start,
            line_end=line_end,
            extractions=extractions,
        )


class BaseRule(ABC):
    """规则脚本基类。

    每条规则都是继承此类的独立模块，存放在 rules/ 目录下。
    规则可以实现任意复杂的逻辑：正则匹配、AST 分析、外部 API 调用、文件探测等。
    """

    @property
    @abstractmethod
    def rule_id(self) -> str:
        """唯一标识符，如 'assertion_error'。"""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """规则名称，如 '断言失败检测'。"""
        ...

    @property
    @abstractmethod
    def category(self) -> str:
        """匹配成功时归属的类别名称，如 '断言失败'。"""
        ...

    @property
    @abstractmethod
    def priority(self) -> int:
        """优先级（数值越小优先级越高）。"""
        ...

    @property
    def version(self) -> str:
        return "1.0"

    @property
    def description(self) -> str:
        return ""

    def required_files(self) -> list[str]:
        """声明本规则可能需要读取的附加文件 glob 模式列表。

        例如：["config/*.yaml", "*.env"]。Orchestrator 会在 evaluate 前按需获取。
        """
        return []

    @abstractmethod
    async def evaluate(self, ctx: RuleContext) -> RuleResult:
        """评估当前上下文是否匹配本规则。

        Args:
            ctx: 包含失败事件所有可用信息的上下文对象。

        Returns:
            RuleResult: 匹配结果（成功/失败 + 类别 + 证据）。
        """
        ...
