"""规则编辑器相关 Pydantic 模式。

所有 schema 仅承担序列化/校验，DB 模型转换由 API 层完成。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, ConfigDict


# ── 来源字段枚举（与 RuleMatchSource 对齐） ──
MATCH_SOURCES = ("relevant_log", "traceback")
RULE_STATUSES = ("draft", "published")


# ── 通用基类 ──
class _ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── 创建 ──
class RuleCreate(BaseModel):
    """用户/管理员创建规则时提交的载荷。

    校验在前端 + 后端都做：
    - rule_id 必须是 snake_case（同时也是 Python 模块名）
    - pattern 必须是可编译的正则（API 层额外用 re.compile 一次）
    - category 支持 "大类/子类" 路径
    """
    rule_id: str = Field(min_length=2, max_length=128, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=256)
    category: str = Field(min_length=1, max_length=128, description="支持 '大类/子类' 路径")
    description: Optional[str] = Field(default=None, max_length=2000)
    priority: int = Field(default=100, ge=0, le=1000)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    match_source: str = Field(default="relevant_log")
    pattern: str = Field(min_length=1, max_length=4000)
    version: str = Field(default="1.0", max_length=32)


# ── 更新 ──
class RuleUpdate(BaseModel):
    """整体更新（不含 rule_id、created_by、status、analysis_rule_id）。"""
    name: str = Field(min_length=1, max_length=256)
    category: str = Field(min_length=1, max_length=128)
    description: Optional[str] = Field(default=None, max_length=2000)
    priority: int = Field(ge=0, le=1000)
    confidence: float = Field(ge=0.0, le=1.0)
    match_source: str
    pattern: str = Field(min_length=1, max_length=4000)
    version: str = Field(max_length=32)


# ── 启用切换 ──
class RuleEnabledPatch(BaseModel):
    enabled: bool


# ── 名称/备注局部更新 ──
class RuleMetaPatch(BaseModel):
    """只更新 name / description；不触发重渲染 / 状态变更。

    权限策略：
    - builtin（系统）规则：仅 admin
    - user 规则：创建者本人 + admin
    """
    name: Optional[str] = Field(default=None, min_length=1, max_length=256)
    description: Optional[str] = Field(default=None, max_length=2000)


# ── 列表项 ──
class RuleListItem(_ORMBase):
    id: str
    rule_id: str
    name: str
    category: str          # 已拼成 "大类/子类"
    category_id: str
    priority: int
    enabled: bool
    match_source: Optional[str] = None
    pattern: Optional[str] = None
    status: Optional[str] = None        # builtin 为 None，user 为 "draft"/"published"
    source: str                          # "builtin" | "user"
    version: str
    description: Optional[str] = None
    created_by: Optional[str] = None
    created_by_username: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    hit_count: int = 0


# ── 详情（含 .py 全文 + 操作历史） ──
class RuleAuditEntry(_ORMBase):
    id: str
    action: str
    actor_user_id: str
    actor_username: str
    before: Optional[str] = None
    after: Optional[str] = None
    ip: Optional[str] = None
    created_at: datetime


class RuleDetail(RuleListItem):
    source_code: Optional[str] = None   # user 规则：生成的 .py 全文；builtin 规则：null
    audits: list[RuleAuditEntry] = []


# ── 通用响应 ──
class OperationResult(BaseModel):
    rule_id: str
    status: str
    detail: Optional[str] = None
