"""metadata/summary_report.yaml 的读取、解析与匹配。

上传方在 <upload>/metadata/summary_report.yaml 记录原始测试结果
（testsuites[] → testcases[]，含 id/desc/result/start_time/end_time/fail_detail）。
本模块供 API（展示原始结果列）与解析流水线（blocked 用例跳过分析）共用。
任何读取/解析失败都返回 None，调用方不需要做异常处理。
"""

from __future__ import annotations

from typing import Optional


def stem(name: str) -> str:
    base = (name or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return base.rsplit(".", 1)[0].lower()


def normalize_status(result) -> tuple[str, str]:
    """返回 (display_result, normalized_status)。

    已知状态（不区分大小写）：Success/failed/blocked；其余保留原文但归为 blocked。
    """
    raw = str(result or "").strip()
    low = raw.lower()
    if low in ("success", "failed", "blocked"):
        return raw, low
    return raw, "blocked"


def last_fail_line(detail) -> str:
    """fail_detail 通常是多行 trace；展示只取最后一个非空行。"""
    lines = [l.strip() for l in str(detail or "").splitlines() if l.strip()]
    return lines[-1] if lines else ""


def short_fail_reason(detail, limit: int = 120) -> str:
    text = last_fail_line(detail)
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def summary_report_path(log_file, task) -> Optional[tuple[str, str]]:
    """根据 LogFile.source_dir 推导 metadata/summary_report.yaml 的位置。

    Returns:
        (provider, path) 或 None（无法定位时）。
    """
    source_dir = (log_file.source_dir or "").replace("\\", "/")
    if not source_dir:
        return None
    provider = "s3" if task and task.source_type == "s3" else "local"
    if "/artifacts/" in source_dir:
        base = source_dir.split("/artifacts/")[0]
        return provider, f"{base}/metadata/summary_report.yaml"
    if provider == "local":
        from pathlib import Path
        candidate = Path(source_dir) / "metadata" / "summary_report.yaml"
        if candidate.exists():
            return provider, str(candidate)
    return None


async def load_summary_lookup(provider: str, path: str, cache: dict) -> Optional[dict]:
    """读取并解析 summary_report.yaml，按 (provider, path) 在调用方提供的 cache 内缓存。

    任何错误（缺文件、YAML 损坏、结构不符）都返回 None，不向上抛出。
    """
    key = (provider, path)
    if key in cache:
        return cache[key]

    lookup = None
    try:
        import yaml
        if provider == "s3":
            from app.services.storage.provider_manager import provider_manager
            fc = await provider_manager.read_file("s3", path, max_bytes=2 * 1024 * 1024)
            content = fc.content
        else:
            from pathlib import Path
            content = Path(path).read_text(encoding="utf-8", errors="replace")
        data = yaml.safe_load(content) if content else None
        if isinstance(data, dict) and isinstance(data.get("testsuites"), list):
            lookup = build_summary_lookup(data)
    except Exception:
        lookup = None

    cache[key] = lookup
    return lookup


def build_summary_lookup(report: dict) -> dict:
    """把 YAML 规整为查找表：suites/cases 按小写 id、desc 键入。"""
    suites_by_key: dict = {}
    cases_by_key: dict = {}
    suite_list = []

    for suite in report.get("testsuites") or []:
        if not isinstance(suite, dict):
            continue
        suite_rec = {
            "id": suite.get("id"),
            "desc": suite.get("desc"),
            "result": suite.get("result"),
            "start_time": suite.get("start_time"),
            "end_time": suite.get("end_time"),
            "fail_detail": suite.get("fail_detail"),
        }
        suite_list.append(suite_rec)
        for key in (suite.get("id"), suite.get("desc")):
            if key:
                suites_by_key.setdefault(str(key).lower(), suite_rec)
                suites_by_key.setdefault(stem(str(key)), suite_rec)

        for case in suite.get("testcases") or []:
            if not isinstance(case, dict):
                continue
            case_rec = {
                "id": case.get("id"),
                "desc": case.get("desc"),
                "result": case.get("result"),
                "start_time": case.get("start_time"),
                "end_time": case.get("end_time"),
                "fail_detail": case.get("fail_detail"),
                "suite": suite_rec,
            }
            for key in (case.get("id"), case.get("desc")):
                if key:
                    cases_by_key.setdefault(str(key).lower(), case_rec)
                    cases_by_key.setdefault(stem(str(key)), case_rec)

    return {"suites": suites_by_key, "cases": cases_by_key, "suite_list": suite_list}


def find_case(lookup: Optional[dict], *candidates) -> Optional[dict]:
    """按候选名（testcase_name、文件名 stem 等）查找测试用例记录。"""
    if not lookup:
        return None
    for cand in candidates:
        if cand and str(cand).lower() in lookup["cases"]:
            return lookup["cases"][str(cand).lower()]
    return None


def is_blocked(record: Optional[dict]) -> bool:
    """仅显式 result=blocked（不含未知状态的兜底归类）。"""
    if not record:
        return False
    return str(record.get("result") or "").strip().lower() == "blocked"


def summary_for_file(log_file, lookup: Optional[dict], source_path: str) -> Optional[dict]:
    """为单个 LogFile 匹配 summary report 记录并组装 API 响应字段。"""
    if not lookup:
        return None

    case_rec = None
    suite_rec = None

    if log_file.file_type == "testcase":
        case_rec = find_case(lookup, log_file.testcase_name, stem(log_file.name))
        if not case_rec:
            return None
        suite_rec = case_rec.get("suite")
    elif log_file.file_type == "testsuite":
        cand = stem(log_file.name)
        suite_rec = lookup["suites"].get(cand)
        if not suite_rec and len(lookup["suite_list"]) == 1:
            suite_rec = lookup["suite_list"][0]  # 单套件兜底
        if not suite_rec:
            return None
    else:
        return None  # task_log 等不关联原始结果

    primary = case_rec or suite_rec
    display_result, normalized = normalize_status(primary.get("result"))
    fail_detail = str(primary.get("fail_detail") or "")

    return {
        "suite_id": suite_rec.get("id") if suite_rec else None,
        "suite_desc": suite_rec.get("desc") if suite_rec else None,
        "suite_result": suite_rec.get("result") if suite_rec else None,
        "case_id": case_rec.get("id") if case_rec else None,
        "case_desc": case_rec.get("desc") if case_rec else None,
        "case_result": case_rec.get("result") if case_rec else None,
        "display_result": display_result,
        "normalized_status": normalized,
        "start_time": primary.get("start_time"),
        "end_time": primary.get("end_time"),
        "fail_detail": fail_detail,
        "fail_reason_line": last_fail_line(fail_detail),
        "fail_reason_short": short_fail_reason(fail_detail),
        "source_path": source_path,
    }
