"""规则编辑器相关的数据模型。

本模块新增两张表，均在 `app.database.init_db()` 时由 SQLAlchemy `create_all`
自动创建（不破坏现有 `analysis_rules` 等已存在表，零迁移）：

- `rules`：每条规则的"用户/管理员"维度元数据，与 `analysis_rules` 一对一关联
  （builtin 规则无 `rules` 记录；user 规则有）。
- `rule_audit_logs`：规则操作审计日志，每条记录一次动作。
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.task import gen_uuid

if TYPE_CHECKING:
    from app.models.task import AnalysisRule


class RuleStatus(str, enum.Enum):
    """规则状态机。

    - draft：草稿，不参与匹配
    - published：已发布，参与匹配（前提 `AnalysisRule.enabled=True`）
    """
    draft = "draft"
    published = "published"


class RuleMatchSource(str, enum.Enum):
    """正则匹配的源字段。"""
    relevant_log = "relevant_log"   # 从 failure_event.relevant_log 匹配
    traceback = "traceback"         # 从 traceback 匹配


class Rule(Base):
    """用户/管理员创建的规则元数据。

    builtin 规则不写入本表（通过 `analysis_rules.script_module` 前缀区分：
    `rules.<rid>` 视为 builtin，`rules.user.<rid>` 视为 user 规则）。
    """
    __tablename__ = "rules"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=gen_uuid)
    rule_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)

    # —— 用户规则特有字段（与 builtin 规则不同部分）——
    match_source: Mapped[str] = mapped_column(
        String(32), default=RuleMatchSource.relevant_log.value, nullable=False,
    )
    pattern: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # —— 状态机 ——
    status: Mapped[str] = mapped_column(
        String(16), default=RuleStatus.draft.value, nullable=False, index=True,
    )

    # —— 审计字段 ——
    created_by: Mapped[str] = mapped_column(
        String(12), ForeignKey("users.id"), nullable=False, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False,
    )
    updated_by: Mapped[Optional[str]] = mapped_column(
        String(12), ForeignKey("users.id"), default=None,
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    published_by: Mapped[Optional[str]] = mapped_column(
        String(12), ForeignKey("users.id"), default=None,
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)

    # —— 与 AnalysisRule 的 1:1 关联 ——
    analysis_rule_id: Mapped[Optional[str]] = mapped_column(
        String(12), ForeignKey("analysis_rules.id"), unique=True, default=None,
    )
    analysis_rule: Mapped[Optional["AnalysisRule"]] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Rule {self.rule_id} status={self.status}>"


class RuleAuditLog(Base):
    """规则操作审计日志。

    `before` / `after` 用 JSON 字符串存关键字段（rule_id、name、category、
    priority、pattern、enabled、status 等），节省空间并避免宽表。
    """
    __tablename__ = "rule_audit_logs"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=gen_uuid)

    # 业务主键：AnalysisRule.rule_id（字符串，便于跨表查阅）
    rule_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    actor_user_id: Mapped[str] = mapped_column(
        String(12), ForeignKey("users.id"), nullable=False,
    )
    actor_username: Mapped[str] = mapped_column(String(64), nullable=False)

    # create / update / publish / unpublish / enable / disable / delete
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    before: Mapped[Optional[str]] = mapped_column(Text, default=None)
    after: Mapped[Optional[str]] = mapped_column(Text, default=None)
    ip: Mapped[Optional[str]] = mapped_column(String(64), default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, index=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RuleAuditLog {self.action} rule_id={self.rule_id} by {self.actor_username}>"
