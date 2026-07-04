from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
import enum

from app.database import Base
from app.models.task import gen_uuid


class UserRole(str, enum.Enum):
    visitor = "visitor"       # 游客：只能浏览/查看
    analyst = "analyst"       # 分析人员：可审核/覆盖分析结果
    reviewer = "reviewer"     # 审核人员：可操作审核结果 + 启动任务
    admin = "admin"           # 管理员：以上全部 + 用户管理


class User(Base):
    """系统用户。"""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=gen_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role", create_constraint=True),
        default=UserRole.visitor,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
