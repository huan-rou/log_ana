from __future__ import annotations

import re
from typing import List

from app.models.task import FailureEvent, LogEntry


# Patterns for detecting Python failure boundaries
TRACEBACK_START = re.compile(r'^Traceback\s*\(most recent call last\):')
TRACEBACK_FILE_LINE = re.compile(r'^\s*File\s+"([^"]+)",\s*line\s+(\d+)')
TRACEBACK_EXCEPTION = re.compile(r'^(\w+(?:\.\w+)*(?:Error|Exception|Warning|Failure|Interrupt))\s*:?\s*(.*)')
ASSERTION_PATTERN = re.compile(r'(?:AssertionError|assert\s+)', re.IGNORECASE)
ERROR_SENTINELS = re.compile(
    r'(?:Error|Exception|FATAL|CRITICAL|failed|FAILED|FAIL)',
    re.IGNORECASE
)


async def detect_failures(task, db) -> List[FailureEvent]:
    """从日志条目中检测 Python 脚本失败事件。

    策略：
    1. 扫描所有 ERROR/CRITICAL 级别的日志行
    2. 查找 traceback 块（Traceback ... → 最后一行异常类型）
    3. 查找独立的断言失败或异常消息
    4. 将相邻的失败行归并为一个 FailureEvent

    Args:
        task: Task 模型实例
        db: 异步数据库会话

    Returns:
        FailureEvent 列表
    """
    from app.models.task import LogEntry, LogFile

    # Load all log entries ordered by line number
    from sqlalchemy import select
    result = await db.execute(
        select(LogEntry)
        .where(LogEntry.task_id == task.id)
        .order_by(LogEntry.line_number)
    )
    all_entries = list(result.scalars())

    # 按来源文件分组检测，避免 traceback 块跨文件拼接
    groups: dict = {}
    for entry in all_entries:
        groups.setdefault(entry.log_file_id, []).append(entry)

    # 文件名映射：html 文件采用红色块检测，文本文件保留原有检测
    lf_rows = (await db.execute(
        select(LogFile).where(LogFile.task_id == task.id)
    )).scalars()
    lf_names = {lf.id: lf.name for lf in lf_rows}

    failures = []
    for log_file_id, entries in groups.items():
        name = (lf_names.get(log_file_id) or "").lower()
        is_html = name.endswith((".html", ".htm")) or task.parser_type == "html"
        if is_html:
            file_failures = _detect_red_blocks(task, entries, db)
        else:
            file_failures = await _detect_in_entries(task, entries, db)
        for f in file_failures:
            f.log_file_id = log_file_id
        failures.extend(file_failures)

    # 更新各文件失败计数
    if failures:
        per_file: dict = {}
        for f in failures:
            if f.log_file_id:
                per_file[f.log_file_id] = per_file.get(f.log_file_id, 0) + 1
        if per_file:
            lf_result = await db.execute(
                select(LogFile).where(LogFile.id.in_(per_file.keys()))
            )
            for lf in lf_result.scalars():
                lf.failure_count = per_file.get(lf.id, 0)

    task.failure_count = len(failures)
    await db.flush()
    # commit 由上层 _run_pipeline 统一执行

    # Audit: log exception type distribution
    from app.core.audit_logger import audit_logger
    exc_types: dict[str, int] = {}
    for f in failures:
        t = f.exception_type or "UnknownError"
        exc_types[t] = exc_types.get(t, 0) + 1
    await audit_logger.log(task.id, "failures.detected",
                           total=len(failures),
                           exception_types=exc_types)

    return failures


# 红色块内的异常签名：如 "AssertionError: xxx" / "RuntimeError: xxx"
RED_BLOCK_EXCEPTION = re.compile(r'(\w+(?:\.\w+)*(?:Error|Exception))\s*:\s*(.*)')

MAX_BLOCK_CHARS = 8000


def _detect_red_blocks(task, entries: list, db) -> List[FailureEvent]:
    """html 文件的失败检测：连续红色行（is_error）构成一个失败块。

    每个块产生一个 FailureEvent，按文档顺序排列（"第一个块"即最早的失败）。
    """
    failures: List[FailureEvent] = []
    block: list = []

    def flush():
        if not block:
            return
        text = "\n".join(e.raw_line for e in block)
        if len(text) > MAX_BLOCK_CHARS:
            text = text[:MAX_BLOCK_CHARS] + "\n…(truncated)"
        exc_type, exc_msg = "UnknownError", None
        for e in block:
            m = RED_BLOCK_EXCEPTION.search(e.raw_line)
            if m:
                exc_type = m.group(1)
                exc_msg = m.group(2).strip() or None
                break
        script_name = next((e.script_name for e in block if e.script_name), None)
        failure = FailureEvent(
            task_id=task.id,
            exception_type=exc_type,
            exception_message=exc_msg,
            traceback=text,
            relevant_log=text,
            script_name=script_name,
            line_start=block[0].file_line_number,
            line_end=block[-1].file_line_number,
        )
        db.add(failure)
        failures.append(failure)
        block.clear()

    prev_no = None
    for entry in entries:
        if entry.is_error:
            # 连续行（按文件内行号相邻）归并为同一块
            if block and prev_no is not None and entry.file_line_number not in (prev_no, prev_no + 1):
                flush()
            block.append(entry)
            prev_no = entry.file_line_number
        else:
            flush()
            prev_no = None
    flush()

    return failures


async def _detect_in_entries(task, entries: list, db) -> List[FailureEvent]:
    """在单个文件的条目序列内检测失败事件。"""
    failures = []
    i = 0
    while i < len(entries):
        entry = entries[i]

        # Detection strategy 1: Traceback block
        if TRACEBACK_START.search(entry.raw_line):
            failure_data = await _extract_traceback_block(entries, i, task.id, db)
            if failure_data:
                failures.append(failure_data["failure"])
                i += failure_data["skip_lines"]
                continue

        # Detection strategy 2: Standalone exception on error line
        if entry.is_error or ERROR_SENTINELS.search(entry.raw_line):
            exc_match = TRACEBACK_EXCEPTION.search(entry.raw_line)
            if exc_match:
                failure = FailureEvent(
                    task_id=task.id,
                    exception_type=exc_match.group(1),
                    exception_message=exc_match.group(2).strip() or None,
                    traceback=entry.raw_line,
                    script_name=entry.script_name,
                    relevant_log=entry.raw_line,
                    line_start=entry.file_line_number,
                    line_end=entry.file_line_number,
                )
            else:
                # Generic error — capture surrounding context
                context_start = max(0, i - 3)
                context_end = min(len(entries), i + 4)
                relevant = "\n".join(
                    e.raw_line for e in entries[context_start:context_end]
                )
                failure = FailureEvent(
                    task_id=task.id,
                    exception_type=_guess_exception_type(entry.raw_line),
                    exception_message=entry.message,
                    traceback=entry.raw_line,
                    script_name=entry.script_name,
                    relevant_log=relevant,
                    line_start=entries[context_start].file_line_number,
                    line_end=entries[context_end - 1].file_line_number,
                )

            db.add(failure)
            failures.append(failure)

        i += 1

    # Also detect assertion failures on non-error lines
    i = 0
    while i < len(entries):
        entry = entries[i]
        if not entry.is_error and ASSERTION_PATTERN.search(entry.raw_line):
            context_start = max(0, i - 2)
            context_end = min(len(entries), i + 3)
            relevant = "\n".join(
                e.raw_line for e in entries[context_start:context_end]
            )
            failure = FailureEvent(
                task_id=task.id,
                exception_type="AssertionError",
                exception_message=entry.message,
                traceback=entry.raw_line,
                script_name=entry.script_name,
                relevant_log=relevant,
                line_start=entry.file_line_number,
                line_end=entry.file_line_number,
            )
            db.add(failure)
            failures.append(failure)
        i += 1

    return failures


async def _extract_traceback_block(
    entries: list, start_idx: int, task_id: str, db
) -> dict | None:
    """提取一个完整的 traceback 块。

    Returns:
        {"failure": FailureEvent, "skip_lines": int} 或 None
    """
    tb_lines = []
    exc_type = None
    exc_msg = None
    script_name = None
    end_idx = start_idx

    for i in range(start_idx, min(len(entries), start_idx + 200)):
        line = entries[i].raw_line.rstrip()
        tb_lines.append(line)

        # Check for exception line
        exc_match = TRACEBACK_EXCEPTION.match(line)
        if exc_match:
            exc_type = exc_match.group(1)
            exc_msg = exc_match.group(2).strip() or None
            end_idx = i
            # Include one more line if it looks like continuation
            if i + 1 < len(entries) and entries[i + 1].raw_line.startswith(("  ", "\t")):
                tb_lines.append(entries[i + 1].raw_line.rstrip())
                end_idx = i + 1
            break

        # Extract script name from File "..." line
        file_match = TRACEBACK_FILE_LINE.match(line)
        if file_match and not script_name:
            script_name = file_match.group(1).split("/")[-1].split("\\")[-1]

        # Safety break: empty line after tb block
        if not line.strip() and i > start_idx + 1:
            end_idx = i - 1
            break

    if not exc_type:
        return None

    failure = FailureEvent(
        task_id=task_id,
        exception_type=exc_type,
        exception_message=exc_msg,
        traceback="\n".join(tb_lines),
        script_name=script_name,
        relevant_log="\n".join(tb_lines),
        line_start=entries[start_idx].file_line_number,
        line_end=entries[min(end_idx, len(entries) - 1)].file_line_number,
    )
    db.add(failure)
    return {"failure": failure, "skip_lines": end_idx - start_idx + 1}


def _guess_exception_type(line: str) -> str:
    """从错误行猜测异常类型。"""
    exc_patterns = [
        (r'(\w+Error)', None),
        (r'(\w+Exception)', None),
        (r'(\w+Failure)', None),
        (r'(Timeout|timeout)', 'TimeoutError'),
        (r'(Connection\s*refused|ConnectionError)', 'ConnectionError'),
        (r'(Permission\s*denied|PermissionError)', 'PermissionError'),
        (r'(File\s*not\s*found|FileNotFoundError)', 'FileNotFoundError'),
        (r'(KeyError)', 'KeyError'),
        (r'(ValueError)', 'ValueError'),
        (r'(TypeError)', 'TypeError'),
        (r'(ImportError|ModuleNotFoundError)', 'ImportError'),
        (r'(OSError)', 'OSError'),
        (r'(AssertionError|assert)', 'AssertionError'),
        (r'(AttributeError)', 'AttributeError'),
    ]
    for pattern, force_type in exc_patterns:
        m = re.search(pattern, line, re.IGNORECASE)
        if m:
            return force_type or m.group(1)
    return "UnknownError"
