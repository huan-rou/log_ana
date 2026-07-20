"""Purpose execution models for multi-source analysis runs."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.task import gen_uuid


class PurposeExecution(Base):
    __tablename__ = "purpose_executions"
    __table_args__ = (
        UniqueConstraint("purpose_id", "round_number", name="uq_purpose_execution_round"),
    )

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=gen_uuid)
    purpose_id: Mapped[str] = mapped_column(
        String(12), ForeignKey("test_purposes.id"), nullable=False, index=True
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    external_task_id: Mapped[str] = mapped_column(String(256), nullable=False)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    sources: Mapped[List["TaskSource"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan", lazy="selectin",
        order_by="TaskSource.discovery_order",
    )


class TaskSource(Base):
    """A JSON leaf. ``name`` is the feature and ``source_task_id`` locates S3."""

    __tablename__ = "task_sources"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=gen_uuid)
    execution_id: Mapped[str] = mapped_column(
        String(12), ForeignKey("purpose_executions.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    source_task_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    discovery_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text, default=None)

    execution: Mapped["PurposeExecution"] = relationship(back_populates="sources")
    blocks: Mapped[List["TaskBlock"]] = relationship(
        back_populates="source", cascade="all, delete-orphan", lazy="selectin",
        order_by="TaskBlock.discovery_order",
    )


class TaskBlock(Base):
    __tablename__ = "task_blocks"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=gen_uuid)
    source_id: Mapped[str] = mapped_column(
        String(12), ForeignKey("task_sources.id"), nullable=False, index=True
    )
    node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    task_block_id: Mapped[str] = mapped_column(String(256), nullable=False)
    upload_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    summary_path: Mapped[Optional[str]] = mapped_column(String(1024), default=None)
    discovery_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text, default=None)
    environment: Mapped[Optional[str]] = mapped_column(String(256), default=None)

    source: Mapped["TaskSource"] = relationship(back_populates="blocks")
    suite: Mapped[Optional["ExecutionSuite"]] = relationship(
        back_populates="block", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )
    occurrences: Mapped[List["CaseOccurrence"]] = relationship(
        back_populates="block", cascade="all, delete-orphan", lazy="selectin",
        order_by="CaseOccurrence.discovery_order",
    )


class ExecutionSuite(Base):
    __tablename__ = "execution_suites"
    __table_args__ = (UniqueConstraint("task_block_id", name="uq_execution_suite_block"),)

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=gen_uuid)
    task_block_id: Mapped[str] = mapped_column(
        String(12), ForeignKey("task_blocks.id"), nullable=False, index=True
    )
    suite_id: Mapped[Optional[str]] = mapped_column(String(256), default=None, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(512), default=None)
    raw_result: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    normalized_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    start_time: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    end_time: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    fail_detail: Mapped[Optional[str]] = mapped_column(Text, default=None)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    blocked_count: Mapped[int] = mapped_column(Integer, default=0)
    unknown_count: Mapped[int] = mapped_column(Integer, default=0)

    block: Mapped["TaskBlock"] = relationship(back_populates="suite")


class CaseOccurrence(Base):
    __tablename__ = "case_occurrences"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=gen_uuid)
    task_block_id: Mapped[str] = mapped_column(
        String(12), ForeignKey("task_blocks.id"), nullable=False, index=True
    )
    suite_id: Mapped[Optional[str]] = mapped_column(
        String(12), ForeignKey("execution_suites.id"), default=None, index=True
    )
    case_id: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    case_name: Mapped[Optional[str]] = mapped_column(String(512), default=None)
    raw_result: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    normalized_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    start_time: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    end_time: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    fail_detail: Mapped[Optional[str]] = mapped_column(Text, default=None)
    discovery_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    log_file_id: Mapped[Optional[str]] = mapped_column(
        String(12), ForeignKey("log_files.id"), default=None, index=True
    )

    block: Mapped["TaskBlock"] = relationship(back_populates="occurrences")
    suite: Mapped[Optional["ExecutionSuite"]] = relationship(lazy="selectin")
    log_file = relationship("LogFile", lazy="selectin")
