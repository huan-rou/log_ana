from __future__ import annotations

import logging
import re
from pathlib import Path
from datetime import datetime
from typing import List, Optional

from bs4 import BeautifulSoup

from app.config import settings

logger = logging.getLogger("app.log_parser")


# ── Default text log format regex ──
# Captures: timestamp, level, script_name, message
DEFAULT_LOG_PATTERN = re.compile(
    r'^\[(?P<timestamp>[^\]]+)\]\s*\[(?P<level>[A-Z]+)\]\s*\[(?P<script>[^\]]+)\]\s*(?P<message>.*)$'
)

# Valid log levels (uppercase)
LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "FATAL"})

# Sentinels that indicate a Python failure
ERROR_SENTINELS = {
    "Traceback (most recent call last):",
    "AssertionError",
    "assert ",
}


def parse_text_log_line(
    line: str,
    pattern: re.Pattern | None = None,
) -> dict:
    """解析单行文本日志。

    Args:
        line: 原始日志行
        pattern: 自定义正则模式（需包含 timestamp/level/script/message 命名组）

    Returns:
        解析后的字典，始终包含 raw_line 字段。
    """
    pat = pattern or DEFAULT_LOG_PATTERN
    m = pat.match(line.strip())
    if m:
        groups = m.groupdict()
        level = groups.get("level", "").upper()
        if level not in LOG_LEVELS:
            level = _infer_level_from_text(groups.get("message", "") + line)

        return {
            "timestamp": groups.get("timestamp"),
            "level": level,
            "script_name": groups.get("script"),
            "message": groups.get("message"),
            "is_error": level in ("ERROR", "CRITICAL", "FATAL"),
            "raw_line": line,
        }

    # Fallback: treat as unstructured
    return {
        "timestamp": None,
        "level": _infer_level_from_text(line),
        "script_name": None,
        "message": line.strip(),
        "is_error": _is_error_line(line),
        "raw_line": line,
    }


# 公共页头/导航区块：仅用于快速跳转和过滤，不属于实际日志内容，解析前剔除
HTML_EXCLUDED_SELECTORS = [
    'div.filters.if_js',
    'div#hellobaby',
    'div#mainAnchorDivId',
]

# 视为"红色文本"的颜色名（失败/错误内容只看红字）
RED_COLOR_NAMES = {"red", "darkred", "crimson", "firebrick", "indianred", "tomato"}

# inline style 中的文本颜色声明（排除 background-color 等带前缀的属性）
_STYLE_COLOR_RE = re.compile(r'(?:^|;)\s*color\s*:\s*([^;]+)')


def _is_red_color_value(value: str) -> bool:
    """判断一个 CSS 颜色值是否偏红。

    支持颜色名、#rgb/#rrggbb（如报告中的 Font Color='#E64046'）和 rgb(r,g,b)。
    十六进制/rgb 按分量启发式判断：红分量高且明显大于绿蓝分量。
    """
    v = value.strip().lower()
    if v in RED_COLOR_NAMES:
        return True

    r = g = b = None
    if v.startswith("#"):
        hexpart = v[1:]
        if len(hexpart) == 3:
            hexpart = "".join(c * 2 for c in hexpart)
        if len(hexpart) == 6:
            try:
                r, g, b = (int(hexpart[i:i + 2], 16) for i in (0, 2, 4))
            except ValueError:
                return False
    else:
        m = re.match(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)', v)
        if m:
            r, g, b = (int(x) for x in m.groups())

    if r is None:
        return False
    return r >= 160 and g <= 130 and b <= 130 and r > max(g, b) + 50


_SKIP_TAGS = {"script", "style", "head", "title", "meta", "link"}


def _is_red_element(el) -> bool:
    """判断元素自身是否为红色文本。

    检查三处：inline style 的 color、color 属性（<font color=...> / <a color=...>）、
    class 名中的 error/fail/red 关键字。
    """
    style = (el.get("style") or "").lower()
    m = _STYLE_COLOR_RE.search(style)
    if m and _is_red_color_value(m.group(1)):
        return True

    color_attr = el.get("color")
    if color_attr and _is_red_color_value(str(color_attr)):
        return True

    classes = el.get("class", [])
    classes_str = " ".join(classes).lower() if isinstance(classes, list) else str(classes).lower()
    return any(kw in classes_str for kw in ("error", "fail", "red"))


def parse_html_log(content: str) -> List[dict]:
    """解析 HTML 格式的日志文件。

    处理策略：
    1. 剔除公共页头/导航区块（HTML_EXCLUDED_SELECTORS）。
    2. 按文档顺序遍历文本节点，根据自身及祖先元素的颜色判定是否为红色文本。
    3. 所有行均入库（保留上下文）；红色行标记 is_error=True，仅红色行参与失败分析。
    """
    from bs4 import NavigableString, Tag
    from bs4.element import PreformattedString

    soup = BeautifulSoup(content, "lxml")

    for selector in HTML_EXCLUDED_SELECTORS:
        for el in soup.select(selector):
            el.decompose()

    entries: List[dict] = []
    root = soup.body or soup

    for node in root.descendants:
        if not isinstance(node, NavigableString) or isinstance(node, PreformattedString):
            continue  # PreformattedString 涵盖注释/CDATA/Doctype 等非正文节点
        parent = node.parent
        if parent and parent.name in _SKIP_TAGS:
            continue
        text = str(node)
        if not text.strip():
            continue

        # 向上查找祖先链判断红色
        is_red = False
        el = parent
        while isinstance(el, Tag):
            if _is_red_element(el):
                is_red = True
                break
            el = el.parent

        for line in text.split("\n"):
            line = line.rstrip()
            if not line.strip():
                continue
            level = "ERROR" if is_red else _infer_level_from_text(line)
            entries.append({
                "timestamp": _extract_html_timestamp(parent, line),
                "level": level,
                "script_name": _extract_html_script(parent, line),
                "message": line.strip(),
                "is_error": is_red,
                "raw_line": line,
            })

    # Fallback: 纯文本剥离（遍历无结果时）
    if not entries:
        plain_text = soup.get_text("\n", strip=True)
        for line in plain_text.split("\n"):
            if not line.strip():
                continue
            entries.append({
                "timestamp": None,
                "level": _infer_level_from_text(line),
                "script_name": None,
                "message": line.strip(),
                "is_error": _is_error_line(line),
                "raw_line": line,
            })

    for i, entry in enumerate(entries):
        entry["line_number"] = i + 1

    return entries


def _extract_html_level(el) -> str:
    """从 HTML 元素的 class/style 中提取日志级别。"""
    classes = el.get("class", [])
    classes_str = " ".join(classes).lower() if isinstance(classes, list) else str(classes).lower()
    style = (el.get("style") or "").lower()

    # Check CSS classes
    for level in ("critical", "fatal", "error", "warning", "warn", "info", "debug"):
        if level in classes_str:
            if level == "warn":
                return "WARNING"
            return level.upper()

    # Check inline color styles
    color_map = {
        "red": "ERROR",
        "#ff0000": "ERROR",
        "#f00": "ERROR",
        "#dc3545": "ERROR",
        "#e74c3c": "ERROR",
        "darkred": "ERROR",
        "crimson": "ERROR",
        "orange": "WARNING",
        "#ffa500": "WARNING",
        "#ffc107": "WARNING",
        "#f39c12": "WARNING",
        "yellow": "WARNING",
        "#ffff00": "WARNING",
        "green": "INFO",
        "#00ff00": "INFO",
        "#28a745": "INFO",
        "blue": "INFO",
        "#0000ff": "INFO",
        "cyan": "DEBUG",
        "gray": "DEBUG",
        "grey": "DEBUG",
    }
    for color, level in color_map.items():
        if color in style:
            return level

    return "INFO"


def _extract_html_timestamp(el, text: str) -> Optional[str]:
    """尝试从文本中提取时间戳。"""
    ts_patterns = [
        r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}',
        r'\d{2}:\d{2}:\d{2}\.\d+',
        r'\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}',
    ]
    for pat in ts_patterns:
        m = re.search(pat, text)
        if m:
            return m.group()
    return None


def _extract_html_script(el, text: str) -> Optional[str]:
    """尝试从文本中提取脚本文件名。"""
    m = re.search(r'(\w+\.py)', text)
    return m.group(1) if m else None


def _infer_level_from_text(text: str) -> str:
    """从纯文本中推断日志级别。"""
    upper = text.upper()
    for level in ("CRITICAL", "FATAL", "ERROR", "WARNING", "DEBUG"):
        if level in upper:
            return level
    # Check for colored ANSI escape codes
    if "\033[31m" in text or "\033[91m" in text:  # red
        return "ERROR"
    if "\033[33m" in text or "\033[93m" in text:  # yellow
        return "WARNING"
    return "INFO"


def _is_error_line(line: str) -> bool:
    """判断一行是否属于错误行。"""
    upper = line.upper()
    if any(sentinel.upper() in upper for sentinel in ERROR_SENTINELS):
        return True
    if "Traceback" in line:
        return True
    if "Error" in line and "Error" not in ("ZeroDivisionError",):  # crude
        return any(err in line for err in ("Error:", "Error ", "Error\n"))
    return False


async def parse_log_file(task, db) -> list:
    """解析完整日志文件并存入数据库。

    支持两种数据来源：
    - source_type=upload: 读取本地 log_file_path
    - source_type=s3:       通过 S3 Provider 读取日志文件

    Args:
        task: Task 模型实例
        db: 异步数据库会话

    Returns:
        解析后的 LogEntry 列表
    """
    from app.models.task import LogEntry

    if task.source_type == "s3":
        return await _parse_s3_logs(task, db)
    else:
        return await _parse_local_logs(task, db)


async def _parse_local_logs(task, db) -> list:
    """解析本地上传的日志文件。"""
    file_path = Path(task.log_file_path)
    if not file_path or not file_path.exists():
        raise FileNotFoundError(f"Log file not found: {file_path}")

    log_file = await _create_log_file(
        task, db,
        name=file_path.name,
        path=str(file_path),
        source_dir=str(file_path.parent),
        file_type="testcase" if task.parser_type == "html" else "task_log",
    )

    content = file_path.read_text(encoding="utf-8", errors="replace")
    entries = _parse_content(task, content, log_file=log_file)
    return await _insert_entries(task, db, entries)


BLOCKED_CATEGORY = "无法识别/测试套失败"


async def _mark_blocked(task, log_file, case_rec: dict, db):
    """为 blocked 用例直接写入最终结论（rank=1），日志不做解析。"""
    from app.models.task import FailureEvent, AnalysisResult
    from app.services.rule_executor import _get_category_id
    from app.services.summary_report import last_fail_line

    fail_detail = str(case_rec.get("fail_detail") or "")
    failure = FailureEvent(
        task_id=task.id,
        log_file_id=log_file.id,
        exception_type="BlockedTestcase",
        exception_message=last_fail_line(fail_detail) or None,
        traceback=fail_detail or None,
        relevant_log=fail_detail or None,
    )
    db.add(failure)
    await db.flush()

    db.add(AnalysisResult(
        failure_event_id=failure.id,
        log_file_id=log_file.id,
        rank=1,
        category_id=await _get_category_id(db, BLOCKED_CATEGORY),
        confidence=1.0,
        evidence="summary_report.yaml: result=blocked，跳过日志分析",
        is_auto=True,
        is_fallback=False,
    ))
    log_file.failure_count = 1
    await db.flush()


async def _create_log_file(task, db, *, name: str, path: str, source_dir: str | None,
                           file_type: str, testcase_name: str | None = None):
    """创建 LogFile 行并 flush 取得 id。"""
    from app.models.task import LogFile

    log_file = LogFile(
        task_id=task.id,
        name=name,
        file_path=path,
        source_dir=source_dir,
        file_type=file_type,
        testcase_name=testcase_name,
    )
    db.add(log_file)
    await db.flush()
    return log_file


async def _parse_s3_logs(task, db) -> list:
    """从 S3 读取并解析日志文件。

    策略：
    1. 支持 node_id / task_block_id 为 "*" 的通配符展开
    2. 列出 s3_upload_path 下的 artifacts/task/*.log
    3. 列出 artifacts/testsuite/*.html
    4. 逐个读取并解析
    """
    from app.services.storage.provider_manager import provider_manager

    # Build path segments, stopping at the first wildcard to form a concrete base
    segments = [
        task.package_version,
        task.automation_task_id,
        task.node_id,
        task.task_block_id,
    ]
    concrete = []
    wildcard_from = None
    for idx, seg in enumerate(segments):
        if seg == "*":
            wildcard_from = idx
            break
        if seg:
            concrete.append(seg)
    else:
        # No wildcards — direct path
        concrete.append("upload")

    if not concrete:
        raise ValueError("S3 任务缺少路径信息")

    concrete_base = "/".join(concrete)

    # Discover all upload/ directories (expanding wildcards)
    upload_dirs = await _discover_upload_dirs(
        provider_manager, concrete_base, wildcard_from, segments
    )

    all_entries = []
    skipped_dirs: list[str] = []
    skipped_files: list[str] = []

    from app.core.audit_logger import audit_logger
    import time as _time

    async def _list_dir(dir_path: str) -> list:
        t1 = _time.monotonic()
        try:
            s3_entries = await provider_manager.list_dir("s3", dir_path)
        except Exception as e:
            skipped_dirs.append(f"{dir_path} ({e})")
            await audit_logger.s3_list_dir(
                task.id, path=dir_path, count=0,
                duration_ms=int((_time.monotonic() - t1) * 1000),
                error=str(e),
            )
            return []
        await audit_logger.s3_list_dir(
            task.id, path=dir_path, count=len(s3_entries),
            duration_ms=int((_time.monotonic() - t1) * 1000),
        )
        return s3_entries

    def _is_html(name: str) -> bool:
        return name.lower().endswith((".html", ".htm"))

    # 本阶段仅分析 .html 文件：
    #   artifacts/testsuite/*.html           → file_type=testsuite
    #   artifacts/testcases/<name>/main/*.html → file_type=testcase
    # 其余文件不解析，由 related-files API 按需列出。
    # summary_report.yaml 中 result=blocked 的用例直接给出结论并跳过日志处理。
    from app.services import summary_report as sr
    report_cache: dict = {}

    for upload_dir in upload_dirs:
        summary_lookup = await sr.load_summary_lookup(
            "s3", f"{upload_dir}/metadata/summary_report.yaml", report_cache
        )
        targets: list[dict] = []

        suite_dir = f"{upload_dir}/artifacts/testsuite"
        for s3_entry in await _list_dir(suite_dir):
            if s3_entry.is_file and _is_html(s3_entry.name):
                targets.append({
                    "entry": s3_entry, "file_type": "testsuite",
                    "testcase_name": None, "source_dir": suite_dir,
                })

        tc_root = f"{upload_dir}/artifacts/testcases"
        for tc_dir in await _list_dir(tc_root):
            if tc_dir.is_file:
                continue
            main_dir = f"{tc_dir.path.rstrip('/')}/main"
            for s3_entry in await _list_dir(main_dir):
                if s3_entry.is_file and _is_html(s3_entry.name):
                    targets.append({
                        "entry": s3_entry, "file_type": "testcase",
                        "testcase_name": tc_dir.name, "source_dir": main_dir,
                    })

        for target in targets:
            s3_entry = target["entry"]

            # blocked 用例：记录结论（无法识别/测试套失败），不读取/解析日志
            if target["file_type"] == "testcase":
                case_rec = sr.find_case(
                    summary_lookup, target["testcase_name"], sr.stem(s3_entry.name)
                )
                if sr.is_blocked(case_rec):
                    log_file = await _create_log_file(
                        task, db,
                        name=s3_entry.name,
                        path=s3_entry.path,
                        source_dir=target["source_dir"],
                        file_type=target["file_type"],
                        testcase_name=target["testcase_name"],
                    )
                    await _mark_blocked(task, log_file, case_rec, db)
                    await audit_logger.log(
                        task.id, "testcase.blocked_skip",
                        path=s3_entry.path,
                        testcase=target["testcase_name"] or s3_entry.name,
                    )
                    continue

            t2 = _time.monotonic()
            try:
                fc = await provider_manager.read_file("s3", s3_entry.path, max_bytes=10 * 1024 * 1024)
                if fc.content:
                    log_file = await _create_log_file(
                        task, db,
                        name=s3_entry.name,
                        path=s3_entry.path,
                        source_dir=target["source_dir"],
                        file_type=target["file_type"],
                        testcase_name=target["testcase_name"],
                    )
                    content_entries = _parse_content(
                        task, fc.content,
                        start_line=len(all_entries),
                        log_file=log_file,
                        force_html=True,
                    )
                    all_entries.extend(content_entries)
                await audit_logger.s3_read_file(
                    task.id, path=s3_entry.path, size=fc.size,
                    duration_ms=int((_time.monotonic() - t2) * 1000),
                )
            except Exception as e:
                skipped_files.append(f"{s3_entry.path} ({e})")
                await audit_logger.s3_read_file(
                    task.id, path=s3_entry.path, size=0,
                    duration_ms=int((_time.monotonic() - t2) * 1000),
                    error=str(e),
                )
                continue

    # Surface warnings even when some entries were found
    if skipped_dirs or skipped_files:
        warnings = []
        if skipped_dirs:
            warnings.append(f"跳过 {len(skipped_dirs)} 个目录")
        if skipped_files:
            warnings.append(f"跳过 {len(skipped_files)} 个文件")
        task.error_message = "; ".join(warnings)
        await db.flush()
        await audit_logger.warning(task.id, message=task.error_message)

    if not all_entries:
        detail = f"S3 path: {'/'.join(s for s in segments if s)}"
        if skipped_dirs:
            detail += f"; 目录列表失败: {'; '.join(skipped_dirs[:3])}"
        if skipped_files:
            detail += f"; 文件读取失败: {'; '.join(skipped_files[:3])}"
        raise FileNotFoundError(detail)

    return await _insert_entries(task, db, all_entries)


async def _discover_upload_dirs(provider_manager, concrete_base: str, wildcard_from: int | None, segments: list) -> list[str]:
    """递归展开通配符，返回所有 upload/ 目录路径。"""
    if wildcard_from is None:
        return [concrete_base]

    discovered = [concrete_base]

    for idx in range(wildcard_from, len(segments)):
        seg = segments[idx]
        next_frontier = []
        for parent in discovered:
            try:
                entries = await provider_manager.list_dir("s3", parent)
            except Exception:
                continue
            if seg == "*":
                for entry in entries:
                    if entry.is_dir:
                        next_frontier.append(entry.path)
            else:
                for entry in entries:
                    if entry.is_dir and entry.name == seg:
                        next_frontier.append(entry.path)
                        break
        discovered = next_frontier
        if not discovered:
            return []  # wildcard expansion hit a dead end — no upload dirs (not an error)

    return [f"{d.rstrip('/')}/upload" for d in discovered] if discovered else []


def _parse_content(task, content: str, start_line: int = 0,
                   log_file=None, force_html: bool = False) -> list:
    """解析日志内容为统一的条目字典列表。

    log_file 提供时，条目带上 log_file_id 与文件内行号 file_line_number。
    """
    if force_html or task.parser_type == "html":
        entries = parse_html_log(content)
        for entry in entries:
            entry["file_line_number"] = entry["line_number"]
            entry["line_number"] = entry["line_number"] + start_line
    else:
        custom_pat = None
        if task.log_format_pattern:
            try:
                custom_pat = re.compile(task.log_format_pattern)
            except re.error:
                pass
        entries = []
        for line_no, line in enumerate(content.split("\n"), 1):
            if not line.strip():
                continue
            parsed = parse_text_log_line(line, custom_pat)
            parsed["line_number"] = line_no + start_line
            parsed["file_line_number"] = line_no
            entries.append(parsed)

    if log_file is not None:
        for entry in entries:
            entry["log_file_id"] = log_file.id
        log_file.total_lines = len(entries)
    return entries


async def _insert_entries(task, db, entries: list) -> list:
    """将解析后的条目批量写入数据库。"""
    from app.models.task import LogEntry
    from app.database import log_database_probe

    total_raw_chars = sum(len(entry.get("raw_line") or "") for entry in entries)
    max_raw_chars = max((len(entry.get("raw_line") or "") for entry in entries), default=0)
    total_message_chars = sum(len(entry.get("message") or "") for entry in entries)
    logger.warning(
        "[log_parser] task=%s inserting log_entries count=%s total_raw_chars=%s max_raw_chars=%s total_message_chars=%s",
        task.id,
        len(entries),
        total_raw_chars,
        max_raw_chars,
        total_message_chars,
    )
    log_database_probe(f"log-entries-before-insert task={task.id}")

    chunk_size = 500
    db_entries = []
    for i in range(0, len(entries), chunk_size):
        chunk = entries[i:i + chunk_size]
        chunk_entries = []
        chunk_raw_chars = sum(len(entry.get("raw_line") or "") for entry in chunk)
        chunk_max_raw_chars = max((len(entry.get("raw_line") or "") for entry in chunk), default=0)
        logger.warning(
            "[log_parser] task=%s add chunk start=%s size=%s raw_chars=%s max_raw_chars=%s first_line=%s last_line=%s",
            task.id,
            i,
            len(chunk),
            chunk_raw_chars,
            chunk_max_raw_chars,
            chunk[0].get("line_number") if chunk else None,
            chunk[-1].get("line_number") if chunk else None,
        )

        for entry in chunk:
            ts = None
            if entry.get("timestamp"):
                try:
                    ts = _parse_timestamp(entry["timestamp"])
                except (ValueError, TypeError):
                    pass

            db_entry = LogEntry(
                task_id=task.id,
                log_file_id=entry.get("log_file_id"),
                file_line_number=entry.get("file_line_number"),
                line_number=entry["line_number"],
                timestamp=ts,
                level=entry["level"],
                script_name=entry["script_name"],
                message=entry["message"],
                raw_line=entry["raw_line"],
                is_error=entry["is_error"],
            )
            db.add(db_entry)
            chunk_entries.append(db_entry)
            db_entries.append(db_entry)

        task.total_entries = len(db_entries)
        try:
            await db.flush()
            logger.warning(
                "[log_parser] task=%s flushed chunk start=%s inserted_so_far=%s",
                task.id,
                i,
                len(db_entries),
            )
        except Exception as exc:
            first = chunk[0] if chunk else {}
            logger.exception(
                "[log_parser] task=%s flush failed chunk_start=%s chunk_size=%s first_line=%s first_raw_len=%s first_message_len=%s error=%s",
                task.id,
                i,
                len(chunk),
                first.get("line_number"),
                len(first.get("raw_line") or ""),
                len(first.get("message") or ""),
                exc,
            )
            log_database_probe(f"log-entries-flush-failed task={task.id} chunk={i}")
            raise

    # flush 后数据对同 session 后续查询可见；commit 由上层 _run_pipeline 统一执行
    return db_entries


def _parse_timestamp(ts_str: str) -> Optional[datetime]:
    """尝试多种格式解析时间戳。"""
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%d/%b/%Y:%H:%M:%S",
        "%b %d %H:%M:%S",
        "%H:%M:%S",
        "%H:%M:%S.%f",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(ts_str.strip(), fmt)
        except ValueError:
            continue
    return None
