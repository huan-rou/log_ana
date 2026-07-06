"""任务树模型：按"轮次"组织的 JSON 任务树。

数据关系：
  test_versions
    └─ test_task_trees (round=N)        —— 一棵轮次树
        └─ test_task_nodes (parent-child)  —— 树形节点
            └─ Task (tree_node_id 指向叶子)
                └─ LogFile
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.task import gen_uuid


class TestTaskTree(Base):
    """一棵轮次任务树，对应一次 JSON 导入。

    同一 TestVersion 下 round_number 自动递增（1, 2, 3, ...），由 (version_id, round_number) 唯一。
    """
    __tablename__ = "test_task_trees"
    __table_args__ = (
        UniqueConstraint("version_id", "round_number", name="uq_tree_version_round"),
    )

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=gen_uuid)
    version_id: Mapped[str] = mapped_column(
        String(12), ForeignKey("test_versions.id"), nullable=False, index=True
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    root_name: Mapped[str] = mapped_column(String(256), nullable=False)
    root_id: Mapped[str] = mapped_column(String(256), nullable=False)
    raw_json: Mapped[Optional[str]] = mapped_column(Text, default=None)
    note: Mapped[str] = mapped_column(Text, nullable=False)  # 轮次备注，追加时必填
    parsed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # relations
    nodes: Mapped[List["TestTaskNode"]] = relationship(
        back_populates="tree",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="TestTaskNode.sort_order",
    )

    def to_summary(self) -> dict:
        return {
            "id": self.id,
            "version_id": self.version_id,
            "round_number": self.round_number,
            "root_name": self.root_name,
            "root_id": self.root_id,
            "note": self.note,
            "total_nodes": len(self.nodes) if self.nodes else 0,
            "leaf_count": sum(1 for n in (self.nodes or []) if n.is_leaf),
            "created_at": self.created_at,
            "parsed_at": self.parsed_at,
        }


class TestTaskNode(Base):
    """任务树的一个节点。

    聚合键 name_key = name.rsplit('_', 1)[0]（用于跨 round 聚合同名节点）。
    叶子节点的 node_id 对应 S3 任务编号（Task.automation_task_id）。
    """
    __tablename__ = "test_task_nodes"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=gen_uuid)
    tree_id: Mapped[str] = mapped_column(
        String(12), ForeignKey("test_task_trees.id"), nullable=False, index=True
    )
    parent_id: Mapped[Optional[str]] = mapped_column(
        String(12), ForeignKey("test_task_nodes.id"), default=None
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    name_key: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    is_leaf: Mapped[bool] = mapped_column(Boolean, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    extra: Mapped[Optional[str]] = mapped_column(Text, default=None)

    # relations
    tree: Mapped["TestTaskTree"] = relationship(back_populates="nodes")
    children: Mapped[List["TestTaskNode"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        single_parent=True,
    )
    parent: Mapped[Optional["TestTaskNode"]] = relationship(
        back_populates="children", remote_side="TestTaskNode.id"
    )
