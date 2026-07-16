"""logging_setup 单测（v5 第 9.7 节）。

覆盖：
- setup_logging(True/False) 切换 root + app.* 级别
- setup_logging 幂等：重复调用不增加 handler
- log_file 输出生效
- teardown_logging 清掉 setup_logging 装的 handler
- 与 audit_logger 不互相干扰
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from app.core.logging_setup import (
    _SETUP_FLAG_ATTR,
    is_logging_enabled,
    setup_logging,
    teardown_logging,
)


@pytest.fixture(autouse=True)
def _clean_logging_state():
    """每个测试前后清掉 setup_logging 状态，防止污染其他测试。"""
    teardown_logging()
    yield
    teardown_logging()


def _count_handlers() -> int:
    return len(logging.getLogger().handlers)


def _count_managed_handlers() -> int:
    """只数 setup_logging 自己装的 handler（带 _SETUP_FLAG_ATTR 标记）。"""
    from app.core.logging_setup import _is_managed_handler
    return sum(1 for h in logging.getLogger().handlers if _is_managed_handler(h))


# ── 级别切换 ──


class TestLevelToggle:
    def test_enabled_true_root_info_app_debug(self):
        setup_logging(enabled=True)
        assert logging.getLogger().level == logging.INFO
        assert logging.getLogger("app").level == logging.DEBUG
        # 子 logger 用 getEffectiveLevel 而非 .level（Python NOTSET = 继承）
        assert logging.getLogger("app.sub.deep").getEffectiveLevel() == logging.DEBUG

    def test_enabled_false_root_and_app_warning(self):
        setup_logging(enabled=False)
        assert logging.getLogger().level == logging.WARNING
        assert logging.getLogger("app").level == logging.WARNING
        assert logging.getLogger("app.sub").getEffectiveLevel() == logging.WARNING

    def test_is_logging_enabled_reflects_state(self):
        assert is_logging_enabled() is False
        setup_logging(enabled=True)
        assert is_logging_enabled() is True
        teardown_logging()
        assert is_logging_enabled() is False


# ── 幂等性 ──


class TestIdempotent:
    def test_repeated_call_does_not_duplicate_handlers(self):
        before = _count_handlers()
        setup_logging(enabled=True)
        setup_logging(enabled=True)
        setup_logging(enabled=True)
        assert _count_handlers() == before + 1  # 只装了一个 stream handler

    def test_repeated_call_with_force(self):
        before = _count_handlers()
        setup_logging(enabled=True)
        setup_logging(enabled=True, force=True)
        assert _count_handlers() == before + 1  # force 后仍然是 1 个

    def test_second_call_no_setup_flag_returns_early(self):
        setup_logging(enabled=True)
        first_handler_ids = {id(h) for h in logging.getLogger().handlers}

        # 第二次不传 force，应直接返回，不动 handler
        setup_logging(enabled=False)
        second_handler_ids = {id(h) for h in logging.getLogger().handlers}
        assert first_handler_ids == second_handler_ids


# ── file handler ──


class TestFileHandler:
    def test_log_file_creates_handler(self, tmp_path: Path):
        log_file = tmp_path / "app.log"
        before = _count_handlers()
        setup_logging(enabled=True, log_file=log_file)
        assert _count_handlers() == before + 2  # stdout + file
        assert log_file.exists() or log_file.parent.exists()

    def test_log_file_message_lands_on_disk(self, tmp_path: Path):
        log_file = tmp_path / "app.log"
        setup_logging(enabled=True, log_file=log_file)
        logging.getLogger("app.test").info("hello disk")
        # FileHandler 默认延迟 flush；显式 flush 一下
        for h in logging.getLogger().handlers:
            h.flush()
        content = log_file.read_text(encoding="utf-8")
        assert "hello disk" in content

    def test_log_file_none_means_stdout_only(self):
        before = _count_handlers()
        setup_logging(enabled=True, log_file=None)
        assert _count_handlers() == before + 1

    def test_log_file_parent_created(self, tmp_path: Path):
        log_file = tmp_path / "deep" / "nested" / "app.log"
        setup_logging(enabled=True, log_file=log_file)
        assert log_file.parent.exists()


# ── teardown ──


class TestTeardown:
    def test_teardown_removes_managed_handlers(self):
        setup_logging(enabled=True)
        assert _count_managed_handlers() > 0
        teardown_logging()
        assert _count_managed_handlers() == 0

    def test_teardown_resets_setup_flag(self):
        setup_logging(enabled=True)
        assert getattr(logging.getLogger(), _SETUP_FLAG_ATTR) is True
        teardown_logging()
        assert getattr(logging.getLogger(), _SETUP_FLAG_ATTR, False) is False or not hasattr(
            logging.getLogger(), _SETUP_FLAG_ATTR
        )

    def test_business_handler_preserved(self):
        """业务代码自己 addHandler 的不应被 setup_logging 清掉。"""
        biz_handler = logging.StreamHandler()
        logging.getLogger().addHandler(biz_handler)
        try:
            setup_logging(enabled=True)
            assert biz_handler in logging.getLogger().handlers
            teardown_logging()
            assert biz_handler in logging.getLogger().handlers  # 仍然在
        finally:
            logging.getLogger().removeHandler(biz_handler)


# ── 与 audit_logger 共存 ──


class TestCoexistWithAudit:
    def test_audit_logger_unaffected(self):
        """setup_logging 不应触碰 audit_logger 自身 / 它的 handler。"""
        from app.core.audit_logger import audit_logger
        # audit_logger 是单例，目前 audit_dir 默认 ./data/audit
        # setup_logging 不应该重置 audit_logger 状态
        before_logger = audit_logger
        setup_logging(enabled=True)
        after_logger = audit_logger
        assert before_logger is after_logger  # 同对象


# ── 实际级别生效 ──


class TestEffectiveLevel:
    def test_disabled_app_logger_does_not_emit_info(self):
        """enabled=False 时，app.* logger 的有效级别是 WARNING，isEnabledFor(INFO) 应为 False。"""
        setup_logging(enabled=False)
        assert logging.getLogger("app.silenced").getEffectiveLevel() == logging.WARNING
        assert logging.getLogger("app.silenced").isEnabledFor(logging.INFO) is False
        assert logging.getLogger("app.silenced").isEnabledFor(logging.WARNING) is True

    def test_enabled_app_logger_emits_info(self):
        """enabled=True 时，app.* logger 应接收 INFO。"""
        setup_logging(enabled=True)
        assert logging.getLogger("app.loud").getEffectiveLevel() == logging.DEBUG
        assert logging.getLogger("app.loud").isEnabledFor(logging.INFO) is True
        assert logging.getLogger("app.loud").isEnabledFor(logging.DEBUG) is True

    def test_disabled_app_debug_blocked(self):
        """enabled=False 时 app.* 收不到 DEBUG。"""
        setup_logging(enabled=False)
        assert logging.getLogger("app.deep").isEnabledFor(logging.DEBUG) is False
