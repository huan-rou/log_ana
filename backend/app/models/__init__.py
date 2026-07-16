"""SQLAlchemy ORM 模型集中导出。

本包内每个模块通过 `import` 副作用被 `app.database.Base` 自动发现（用于
`create_all` 建表）。本文件显式 re-export 便于外部 `from app.models import ...`。
"""
from app.models.task import (
    AnalysisResult,
    AnalysisRule,
    Category,
    FailureEvent,
    Feedback,
    LogEntry,
    LogFile,
    Task,
    gen_uuid,
)
from app.models.user import User, UserRole
from app.models.mapping import TestPurpose, TestVersion, TaskReference
from app.models.rule import Rule, RuleAuditLog, RuleStatus, RuleMatchSource
from app.models.task_tree import TestTaskTree, TestTaskNode

__all__ = [
    # task
    "AnalysisResult",
    "AnalysisRule",
    "Category",
    "FailureEvent",
    "Feedback",
    "LogEntry",
    "LogFile",
    "Task",
    "gen_uuid",
    # user
    "User",
    "UserRole",
    # mapping
    "TestPurpose",
    "TestVersion",
    "TaskReference",
    # rule (rule editor)
    "Rule",
    "RuleAuditLog",
    "RuleStatus",
    "RuleMatchSource",
    # task tree (v5)
    "TestTaskTree",
    "TestTaskNode",
]
