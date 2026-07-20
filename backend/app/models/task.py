import uuid
from datetime import datetime
from typing import Optional, List

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


def gen_uuid() -> str:
    return uuid.uuid4().hex[:12]


class Category(Base):
    """预定义的分析结论类别。

    两级结构：parent_id 为空 = 大类；非空 = 子类。
    分析结果/人工覆盖引用的是子类节点（无子类的大类可直接引用）。
    """
    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_id: Mapped[Optional[str]] = mapped_column(
        String(12), ForeignKey("categories.id"), default=None
    )
    description: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # relations
    parent: Mapped[Optional["Category"]] = relationship(
        remote_side="Category.id", lazy="selectin"
    )
    rules: Mapped[List["AnalysisRule"]] = relationship(back_populates="category")
    results: Mapped[List["AnalysisResult"]] = relationship(
        back_populates="category", foreign_keys="AnalysisResult.category_id"
    )


class Task(Base):
    """分析任务。

    对应 S3 路径中的一个 task_block_id，或一个本地文件上传。
    路径规范（来自 rustfs-folder-design.md）：
      s3://<bucket>/<prefix>/<package_version>/<task_id>/<node_id>/<task_block_id>/
        upload/    ← 只读，不可变证据
        analyzer/  ← 分析产物
    """
    __tablename__ = "tasks"

    # ── 系统内部标识 ──
    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False
    )  # pending | parsing | analyzing | completed | completed_with_warnings | failed

    # ── 数据来源 ──
    source_type: Mapped[str] = mapped_column(
        String(16), default="upload", nullable=False
    )  # "upload" | "s3"

    # ── S3 路径定位（source_type=s3 时使用）──
    bucket: Mapped[Optional[str]] = mapped_column(String(256), default=None)
    prefix: Mapped[Optional[str]] = mapped_column(String(512), default=None)
    package_version: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    automation_task_id: Mapped[Optional[str]] = mapped_column(String(256), default=None)
    node_id: Mapped[Optional[str]] = mapped_column(String(128), default=None)
    task_block_id: Mapped[Optional[str]] = mapped_column(String(256), default=None)

    # ── 本地文件（source_type=upload 时使用）──
    log_file_path: Mapped[Optional[str]] = mapped_column(String(1024), default=None)
    parser_type: Mapped[str] = mapped_column(String(32), default="text")  # text | html
    log_format_pattern: Mapped[Optional[str]] = mapped_column(Text, default=None)

    # ── 统计 ──
    total_entries: Mapped[int] = mapped_column(Integer, default=0)
    total_testcases: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    classified_count: Mapped[int] = mapped_column(Integer, default=0)
    unrecognized_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, default=None)

    # ── 任务树关联（v5）──
    # 指向 TestTaskNode.id（叶子节点）；NULL = 未关联或老任务
    tree_node_id: Mapped[Optional[str]] = mapped_column(
        String(12), ForeignKey("test_task_nodes.id"), default=None, index=True
    )
    # New multi-source tasks point at a PurposeExecution. Legacy tasks keep NULL.
    purpose_execution_id: Mapped[Optional[str]] = mapped_column(
        String(12), ForeignKey("purpose_executions.id"), default=None, index=True
    )

    # ── 时间 ──
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)

    # ── 关系 ──
    log_entries: Mapped[List["LogEntry"]] = relationship(back_populates="task", lazy="select")
    failure_events: Mapped[List["FailureEvent"]] = relationship(back_populates="task", lazy="select")
    testcases: Mapped[List["TestCase"]] = relationship(back_populates="task", lazy="select")
    log_files: Mapped[List["LogFile"]] = relationship(back_populates="task", lazy="select")

    @property
    def s3_path(self) -> Optional[str]:
        """构建 S3 对象前缀路径。"""
        if self.source_type != "s3" or not self.bucket:
            return None
        parts = [p for p in [
            self.prefix,
            self.package_version,
            self.automation_task_id,
            self.node_id,
            self.task_block_id,
        ] if p]
        prefix = "/".join(parts)
        return f"s3://{self.bucket}/{prefix}"

    @property
    def s3_upload_path(self) -> Optional[str]:
        """S3 upload/ 目录的完整路径。"""
        base = self.s3_path
        return f"{base}/upload" if base else None

    @property
    def s3_analyzer_path(self) -> Optional[str]:
        """S3 analyzer/ 目录的完整路径。"""
        base = self.s3_path
        return f"{base}/analyzer" if base else None


class LogFile(Base):
    """被分析的单个日志文件（本阶段仅 .html），分析与人工审核的基本单位。

    每个文件最多有 2 条带 rank 的主要错误结论：
    rank=1 为根因（最终结论），rank=2 为次要原因，其余结果 rank=NULL 仅供参考。
    """
    __tablename__ = "log_files"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=gen_uuid)
    task_id: Mapped[str] = mapped_column(String(12), ForeignKey("tasks.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_dir: Mapped[Optional[str]] = mapped_column(String(1024), default=None)
    file_type: Mapped[str] = mapped_column(
        String(16), default="testcase"
    )  # testsuite | testcase | task_log
    testcase_name: Mapped[Optional[str]] = mapped_column(String(256), default=None)
    total_lines: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)

    # ── 人工审核 ──
    review_status: Mapped[str] = mapped_column(
        String(16), default="pending"
    )  # pending | confirmed | overridden
    reviewer_note: Mapped[Optional[str]] = mapped_column(Text, default=None)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)

    # ── 人工覆盖（review_status=overridden 时有效）──
    override_category_id: Mapped[Optional[str]] = mapped_column(
        String(12), ForeignKey("categories.id"), default=None
    )
    override_evidence: Mapped[Optional[str]] = mapped_column(Text, default=None)
    override_line_start: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    override_line_end: Mapped[Optional[int]] = mapped_column(Integer, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # relations
    task: Mapped["Task"] = relationship(back_populates="log_files")
    override_category: Mapped[Optional["Category"]] = relationship(
        foreign_keys=[override_category_id], lazy="selectin"
    )
    analysis_results: Mapped[List["AnalysisResult"]] = relationship(
        back_populates="log_file", lazy="selectin"
    )


class TestCase(Base):
    """单个测试用例——从 HTML 测试报告中提取。

    对应 S3 路径中 artifacts/testcases/<name>/ 下的单个用例。
    """
    __tablename__ = "testcases"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=gen_uuid)
    task_id: Mapped[str] = mapped_column(String(12), ForeignKey("tasks.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    suite_name: Mapped[Optional[str]] = mapped_column(String(256), default=None)
    status: Mapped[str] = mapped_column(
        String(16), default="unknown"
    )  # pass | fail | error | skip | unknown
    duration_sec: Mapped[Optional[float]] = mapped_column(Float, default=None)

    # ── 文件引用 ──
    html_report_path: Mapped[Optional[str]] = mapped_column(String(1024), default=None)
    log_file_path: Mapped[Optional[str]] = mapped_column(String(1024), default=None)
    raw_artifact_path: Mapped[Optional[str]] = mapped_column(String(1024), default=None)

    # ── 提取内容 ──
    extracted_log: Mapped[Optional[str]] = mapped_column(Text, default=None)
    error_summary: Mapped[Optional[str]] = mapped_column(Text, default=None)

    # ── 关联失败事件 ──
    failure_event_id: Mapped[Optional[str]] = mapped_column(
        String(12), ForeignKey("failure_events.id"), default=None
    )

    # ── 关系 ──
    task: Mapped["Task"] = relationship(back_populates="testcases")
    failure_event: Mapped[Optional["FailureEvent"]] = relationship(foreign_keys=[failure_event_id])


class LogEntry(Base):
    """解析后的日志条目。"""
    __tablename__ = "log_entries"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=gen_uuid)
    task_id: Mapped[str] = mapped_column(String(12), ForeignKey("tasks.id"), nullable=False)
    log_file_id: Mapped[Optional[str]] = mapped_column(
        String(12), ForeignKey("log_files.id"), default=None
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    file_line_number: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    level: Mapped[Optional[str]] = mapped_column(String(32), default=None)
    script_name: Mapped[Optional[str]] = mapped_column(String(256), default=None)
    message: Mapped[Optional[str]] = mapped_column(Text, default=None)
    raw_line: Mapped[str] = mapped_column(Text, nullable=False)
    is_error: Mapped[bool] = mapped_column(Boolean, default=False)
    extra: Mapped[Optional[str]] = mapped_column(Text, default=None)

    # relations
    task: Mapped["Task"] = relationship(back_populates="log_entries")


class FailureEvent(Base):
    """检测到的失败事件（脚本执行失败）。"""
    __tablename__ = "failure_events"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=gen_uuid)
    task_id: Mapped[str] = mapped_column(String(12), ForeignKey("tasks.id"), nullable=False)
    log_file_id: Mapped[Optional[str]] = mapped_column(
        String(12), ForeignKey("log_files.id"), default=None
    )
    start_entry_id: Mapped[Optional[str]] = mapped_column(String(12), ForeignKey("log_entries.id"), default=None)
    line_start: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    line_end: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    script_name: Mapped[Optional[str]] = mapped_column(String(256), default=None)
    exception_type: Mapped[Optional[str]] = mapped_column(String(128), default=None)
    exception_message: Mapped[Optional[str]] = mapped_column(Text, default=None)
    traceback: Mapped[Optional[str]] = mapped_column(Text, default=None)
    relevant_log: Mapped[Optional[str]] = mapped_column(Text, default=None)
    detected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # relations
    task: Mapped["Task"] = relationship(back_populates="failure_events")
    analysis_results: Mapped[List["AnalysisResult"]] = relationship(
        back_populates="failure_event", lazy="selectin"
    )


class AnalysisRule(Base):
    """规则脚本的元数据。"""
    __tablename__ = "analysis_rules"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=gen_uuid)
    rule_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    category_id: Mapped[str] = mapped_column(String(12), ForeignKey("categories.id"), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    script_module: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, default=None)
    version: Mapped[str] = mapped_column(String(32), default="1.0")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # relations
    category: Mapped["Category"] = relationship(back_populates="rules")
    results: Mapped[List["AnalysisResult"]] = relationship(back_populates="rule")


class AnalysisResult(Base):
    """分析结果：每个失败事件对应一条分类结果。"""
    __tablename__ = "analysis_results"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=gen_uuid)
    failure_event_id: Mapped[str] = mapped_column(
        String(12), ForeignKey("failure_events.id"), nullable=False
    )
    log_file_id: Mapped[Optional[str]] = mapped_column(
        String(12), ForeignKey("log_files.id"), default=None
    )
    rank: Mapped[Optional[int]] = mapped_column(Integer, default=None)  # 1=根因/最终 2=次要 NULL=其他
    rule_id: Mapped[Optional[str]] = mapped_column(String(12), ForeignKey("analysis_rules.id"), default=None)
    category_id: Mapped[Optional[str]] = mapped_column(String(12), ForeignKey("categories.id"), default=None)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[Optional[str]] = mapped_column(Text, default=None)
    extractions: Mapped[Optional[str]] = mapped_column(Text, default=None)
    is_auto: Mapped[bool] = mapped_column(Boolean, default=True)
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # relations
    failure_event: Mapped["FailureEvent"] = relationship(back_populates="analysis_results")
    log_file: Mapped[Optional["LogFile"]] = relationship(back_populates="analysis_results")
    rule: Mapped[Optional["AnalysisRule"]] = relationship(
        back_populates="results", lazy="selectin"
    )
    category: Mapped[Optional["Category"]] = relationship(
        back_populates="results", foreign_keys=[category_id], lazy="selectin"
    )
    feedback: Mapped[Optional["Feedback"]] = relationship(back_populates="analysis_result", uselist=False)


class Feedback(Base):
    """用户对分析结果的质量反馈。"""
    __tablename__ = "feedbacks"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=gen_uuid)
    analysis_result_id: Mapped[str] = mapped_column(
        String(12), ForeignKey("analysis_results.id"), unique=True, nullable=False
    )
    is_correct: Mapped[Optional[bool]] = mapped_column(Boolean, default=None)
    suggested_category_id: Mapped[Optional[str]] = mapped_column(
        String(12), ForeignKey("categories.id"), default=None
    )
    comment: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # relations
    analysis_result: Mapped["AnalysisResult"] = relationship(back_populates="feedback")


class ArchivedReview(Base):
    """已归档的审核记录（不再在待处理页面展示）。"""
    __tablename__ = "archived_reviews"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=gen_uuid)
    log_file_id: Mapped[str] = mapped_column(
        String(12), ForeignKey("log_files.id"), unique=True, nullable=False
    )
    archived_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class HighValueRecord(Base):
    """高价值审核信息——人工核实过的可靠结论，可作为 LLM 补充材料。"""
    __tablename__ = "high_value_records"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=gen_uuid)
    log_file_id: Mapped[str] = mapped_column(
        String(12), ForeignKey("log_files.id"), unique=True, nullable=False
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
