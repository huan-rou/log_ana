"""应用通用 logging 配置（v5 新增）。

按 `enabled` 切换 root logger 级别：
- enabled=True : root=INFO, app.*=DEBUG → 输出到 stdout + 可选 log_file
- enabled=False: root=WARNING, app.*=WARNING → 关键错误才输出

设计目标：
- 统一格式：`%(asctime)s [%(levelname)s] %(name)s: %(message)s`
- 输出目标：stdout（dev）+ 可选文件（prod / 排查）
- 与 audit_logger 共存：audit_logger 走 JSONL 独立通道，不复用此处
- 幂等：可重复调用，handler 不重复添加
- 测试安全：测试期间 LA_APP_DEBUG_LOGGING=false，新加 logger.info/debug 不会污染测试输出

入口：
    from app.core.logging_setup import setup_logging
    setup_logging(enabled=settings.app_debug_logging, log_file=settings.log_file)
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

# ── 内部常量 ──

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_APP_LOGGER_PREFIX = "app"

# 给 app.* 子 logger 一个标志，区分 setup_logging 加的 handler vs 业务自己加的
_SETUP_FLAG_ATTR = "_app_logging_setup_done"


def _is_managed_handler(h: logging.Handler) -> bool:
    """只移除 setup_logging 自己加的 handler（带标记），避免误删业务代码注册的。"""
    return getattr(h, _SETUP_FLAG_ATTR, False) is True


def _mark_handler(h: logging.Handler) -> None:
    setattr(h, _SETUP_FLAG_ATTR, True)


def _remove_existing_managed_handlers(logger: logging.Logger) -> None:
    """清理之前 setup_logging 装上的 handler，保证幂等。"""
    for h in list(logger.handlers):
        if _is_managed_handler(h):
            logger.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass


def _build_formatter() -> logging.Formatter:
    return logging.Formatter(_FORMAT)


def _build_stream_handler() -> logging.Handler:
    sh = logging.StreamHandler(stream=sys.stdout)
    sh.setFormatter(_build_formatter())
    _mark_handler(sh)
    return sh


def _build_file_handler(log_file: Path) -> logging.Handler:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(_build_formatter())
    _mark_handler(fh)
    return fh


# ── 公共入口 ──


def setup_logging(
    enabled: bool,
    log_file: Optional[Path] = None,
    *,
    force: bool = False,
) -> None:
    """初始化应用 logging 设施。

    Args:
        enabled:
            True  - 打开应用级调试日志（root=INFO, app.*=DEBUG）
            False - 仅 WARNING 及以上
        log_file:
            可选；同时输出到这个文件（默认 None = 只 stdout）
        force:
            True 时即使已 setup 过也重置（用于测试场景）。

    Behavior:
        - 幂等：重复调用会先清掉自己装的 handler 再装新的
        - 不影响 audit_logger（它用独立文件通道 + 自己的 logger 名）
        - 不影响 uvicorn / sqlalchemy / 其他第三方 logger 的级别
          （uvicorn 自己有 access log，跟我们无关）
    """
    root = logging.getLogger()

    # 幂等保护：未传 force 且 root 已经 setup 过，直接返回
    if not force and getattr(root, _SETUP_FLAG_ATTR, False):
        return

    # 清掉旧 managed handler（force 模式下也清）
    _remove_existing_managed_handlers(root)

    if enabled:
        root.setLevel(logging.INFO)
        logging.getLogger(_APP_LOGGER_PREFIX).setLevel(logging.DEBUG)
    else:
        root.setLevel(logging.WARNING)
        logging.getLogger(_APP_LOGGER_PREFIX).setLevel(logging.WARNING)

    # stdout handler
    root.addHandler(_build_stream_handler())

    # 可选 file handler
    if log_file is not None:
        root.addHandler(_build_file_handler(Path(log_file)))

    setattr(root, _SETUP_FLAG_ATTR, True)


def teardown_logging() -> None:
    """测试场景用：清掉 setup_logging 装的 handler，释放 log_file。

    不动 level；不动业务代码自己加的 handler。
    """
    root = logging.getLogger()
    _remove_existing_managed_handlers(root)
    if hasattr(root, _SETUP_FLAG_ATTR):
        delattr(root, _SETUP_FLAG_ATTR)


def is_logging_enabled() -> bool:
    """用于测试或健康检查：当前 root logger 是否已被 setup_logging 接管。"""
    return getattr(logging.getLogger(), _SETUP_FLAG_ATTR, False) is True
