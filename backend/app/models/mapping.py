"""任务映射模型：测试版本 → 测试目的 → S3 任务引用。

层级关系：
  测试版本 (TestVersion): 对应 S3 中的 package_version
    └── 测试目的 (TestPurpose): 一个测试目标（什么环境执行什么脚本）
          └── 任务引用 (TaskReference): 关联的 S3 task_id + 执行轮次
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.task import gen_uuid


class TestVersion(Base):
    """测试版本（对应 S3 package_version）。"""
    __tablename__ = "test_versions"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=gen_uuid)
    version_name: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    bucket: Mapped[Optional[str]] = mapped_column(String(256), default=None)
    prefix: Mapped[Optional[str]] = mapped_column(String(512), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # relations
    purposes: Mapped[List["TestPurpose"]] = relationship(back_populates="version", lazy="selectin")


class TestPurpose(Base):
    """测试目的：在某版本下执行某脚本的测试目标。"""
    __tablename__ = "test_purposes"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=gen_uuid)
    version_id: Mapped[str] = mapped_column(String(12), ForeignKey("test_versions.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, default=None)
    environment: Mapped[Optional[str]] = mapped_column(String(256), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # relations
    version: Mapped["TestVersion"] = relationship(back_populates="purposes")
    task_refs: Mapped[List["TaskReference"]] = relationship(
        back_populates="purpose", lazy="selectin",
        order_by="TaskReference.round_number"
    )


class TaskReference(Base):
    """S3 任务引用：每个测试目的关联的实际 S3 task_id 及轮次。"""
    __tablename__ = "task_references"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=gen_uuid)
    purpose_id: Mapped[str] = mapped_column(String(12), ForeignKey("test_purposes.id"), nullable=False)
    task_id: Mapped[str] = mapped_column(String(256), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # relations
    purpose: Mapped["TestPurpose"] = relationship(back_populates="task_refs")
