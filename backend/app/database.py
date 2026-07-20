from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
from pathlib import Path
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event
from sqlalchemy.engine import make_url

from app.config import BACKEND_DIR, settings

logger = logging.getLogger("app.database")
SQLITE_DB_PATH: Path | None = None


def _configure_diagnostics_logging() -> None:
    app_logger = logging.getLogger("app")
    if not settings.db_diagnostics_enabled:
        app_logger.disabled = True
        return

    app_logger.disabled = False
    app_logger.setLevel(logging.WARNING)

    log_file = settings.db_diagnostics_log_file
    log_file.parent.mkdir(parents=True, exist_ok=True)
    existing_files = {
        getattr(handler, "baseFilename", None)
        for handler in app_logger.handlers
    }
    if str(log_file) not in existing_files:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.WARNING)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        ))
        app_logger.addHandler(file_handler)

    if not app_logger.handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.WARNING)
        stream_handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        ))
        app_logger.addHandler(stream_handler)


_configure_diagnostics_logging()


def _sqlite_database_path(database_url: str) -> Path | None:
    try:
        url = make_url(database_url)
    except Exception as exc:
        logger.warning("[db] failed to parse database URL %r: %s", database_url, exc)
        return None

    if not url.drivername.startswith("sqlite"):
        return None
    if not url.database or url.database == ":memory:":
        return None
    return Path(url.database)


def _log_database_diagnostics(database_url: str) -> None:
    global SQLITE_DB_PATH
    db_path = _sqlite_database_path(database_url)
    SQLITE_DB_PATH = db_path

    logger.warning("[db] cwd=%s", Path.cwd())
    logger.warning("[db] backend_dir=%s", BACKEND_DIR)
    logger.warning("[db] env_file=%s exists=%s", BACKEND_DIR / ".env", (BACKEND_DIR / ".env").exists())
    logger.warning("[db] LA_DATABASE_URL env=%r", os.environ.get("LA_DATABASE_URL"))
    logger.warning("[db] configured database_url=%r", settings.database_url)
    logger.warning("[db] resolved database_url=%r", database_url)
    logger.warning("[db] temp env TEMP=%r TMP=%r SQLITE_TMPDIR=%r",
                   os.environ.get("TEMP"), os.environ.get("TMP"), os.environ.get("SQLITE_TMPDIR"))
    logger.warning("[db] tempfile.gettempdir=%s", tempfile.gettempdir())

    if db_path is None:
        logger.warning("[db] sqlite file path: <not a file-backed sqlite database>")
        return

    parent = db_path.parent
    logger.warning("[db] sqlite path=%s", db_path)
    logger.warning("[db] sqlite path absolute=%s", db_path.resolve())
    logger.warning("[db] sqlite parent=%s", parent)
    logger.warning("[db] sqlite parent exists=%s is_dir=%s", parent.exists(), parent.is_dir())
    logger.warning("[db] sqlite file exists=%s", db_path.exists())
    logger.warning("[db] sqlite parent os.access R/W/X=%s/%s/%s",
                   os.access(parent, os.R_OK), os.access(parent, os.W_OK), os.access(parent, os.X_OK))

    try:
        parent.mkdir(parents=True, exist_ok=True)
        logger.warning("[db] sqlite parent mkdir=ok")
    except Exception as exc:
        logger.exception("[db] sqlite parent mkdir=failed: %s", exc)
        return

    try:
        with tempfile.NamedTemporaryFile(prefix=".db-write-test-", dir=parent, delete=True) as tmp:
            tmp.write(b"ok")
            tmp.flush()
        logger.warning("[db] sqlite parent write_test=ok")
    except Exception as exc:
        logger.exception("[db] sqlite parent write_test=failed: %s", exc)

    try:
        with tempfile.NamedTemporaryFile(prefix=".sqlite-temp-test-", delete=True) as tmp:
            tmp.write(b"ok")
            tmp.flush()
        logger.warning("[db] system temp write_test=ok")
    except Exception as exc:
        logger.exception("[db] system temp write_test=failed: %s", exc)


def _log_sqlite_file_state(label: str) -> None:
    if SQLITE_DB_PATH is None:
        return

    paths = [
        SQLITE_DB_PATH,
        SQLITE_DB_PATH.with_name(f"{SQLITE_DB_PATH.name}-wal"),
        SQLITE_DB_PATH.with_name(f"{SQLITE_DB_PATH.name}-shm"),
    ]
    for path in paths:
        try:
            if path.exists():
                stat = path.stat()
                logger.warning(
                    "[db:%s] file=%s exists=True size=%s readonly=%s mtime=%s",
                    label,
                    path,
                    stat.st_size,
                    not os.access(path, os.W_OK),
                    stat.st_mtime,
                )
            else:
                logger.warning("[db:%s] file=%s exists=False", label, path)
        except Exception as exc:
            logger.exception("[db:%s] failed to stat %s: %s", label, path, exc)


def log_database_probe(label: str) -> None:
    """Run a direct sqlite3 read-only probe outside SQLAlchemy."""
    _log_sqlite_file_state(label)
    if SQLITE_DB_PATH is None:
        return
    if not settings.db_direct_probe_enabled:
        logger.warning("[db:%s] direct probe skipped; enable LA_DB_DIRECT_PROBE_ENABLED=true to run it", label)
        return

    try:
        uri = f"file:{SQLITE_DB_PATH.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=settings.sqlite_busy_timeout_ms / 1000) as con:
            con.execute(f"PRAGMA busy_timeout={settings.sqlite_busy_timeout_ms}")
            for name, sql in [
                ("database_list", "PRAGMA database_list"),
                ("quick_check", "PRAGMA quick_check"),
                ("journal_mode", "PRAGMA journal_mode"),
                ("page_count", "PRAGMA page_count"),
                ("freelist_count", "PRAGMA freelist_count"),
            ]:
                try:
                    logger.warning("[db:%s] direct %s=%s", label, name, con.execute(sql).fetchall())
                except Exception as exc:
                    logger.exception("[db:%s] direct %s failed: %s", label, name, exc)

            if settings.sqlite_journal_mode.upper() == "WAL":
                try:
                    logger.warning(
                        "[db:%s] direct wal_checkpoint=%s",
                        label,
                        con.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchall(),
                    )
                except Exception as exc:
                    logger.exception("[db:%s] direct wal_checkpoint failed: %s", label, exc)
    except Exception as exc:
        logger.exception("[db:%s] direct sqlite connect failed: %s", label, exc)


def _statement_summary(statement: str | None) -> str:
    if not statement:
        return "<none>"
    collapsed = " ".join(statement.split())
    if len(collapsed) > 300:
        return f"{collapsed[:300]}..."
    return collapsed


def _value_summary(value) -> str:
    if value is None:
        return "None"
    if isinstance(value, str):
        sample = value[:80].replace("\n", "\\n").replace("\r", "\\r")
        return f"str(len={len(value)}, sample={sample!r})"
    if isinstance(value, bytes):
        return f"bytes(len={len(value)})"
    return f"{type(value).__name__}({value!r})"


def _parameters_summary(parameters) -> str:
    try:
        if isinstance(parameters, dict):
            return "{" + ", ".join(
                f"{key}: {_value_summary(value)}" for key, value in parameters.items()
            ) + "}"
        if isinstance(parameters, (list, tuple)):
            if parameters and isinstance(parameters[0], (list, tuple, dict)):
                rows = list(parameters)
                head = rows[:3]
                return f"batch(rows={len(rows)}, first={_parameters_summary(head[0]) if head else 'None'})"
            return "[" + ", ".join(_value_summary(value) for value in parameters) + "]"
        return _value_summary(parameters)
    except Exception as exc:
        return f"<failed to summarize parameters: {exc}>"


DATABASE_URL = settings.database_url_absolute
_log_database_diagnostics(DATABASE_URL)

engine = create_async_engine(
    DATABASE_URL,
    echo=settings.debug,
    connect_args={
        "check_same_thread": False,     # aiosqlite 需要
        "timeout": settings.sqlite_busy_timeout_ms / 1000,
    },
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ── SQLite pragma: WAL + busy_timeout ──
@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """每次新连接时执行，设置 pragma 以避免锁冲突。"""
    logger.warning("[db:connect] dbapi_connection=%s record=%s", id(dbapi_connection), id(connection_record))
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA database_list;")
        logger.warning("[db:connect] database_list=%s", cursor.fetchall())
        journal_mode = settings.sqlite_journal_mode.upper()
        cursor.execute(f"PRAGMA journal_mode={journal_mode};")
        logger.warning("[db:connect] journal_mode=%s", cursor.fetchone())
        cursor.execute(f"PRAGMA busy_timeout={settings.sqlite_busy_timeout_ms};")
        cursor.execute(f"PRAGMA temp_store={settings.sqlite_temp_store.upper()};")
        cursor.execute("PRAGMA temp_store;")
        logger.warning("[db:connect] temp_store=%s", cursor.fetchone())
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA locking_mode;")
        logger.warning("[db:connect] locking_mode=%s", cursor.fetchone())
        _log_sqlite_file_state("connect")
    except Exception as exc:
        logger.exception("[db:connect] failed while configuring sqlite pragmas: %s", exc)
        _log_sqlite_file_state("connect-error")
        raise
    finally:
        cursor.close()


@event.listens_for(engine.sync_engine, "checkout")
def _log_checkout(dbapi_connection, connection_record, connection_proxy):
    logger.warning("[db:checkout] dbapi_connection=%s record=%s", id(dbapi_connection), id(connection_record))


@event.listens_for(engine.sync_engine, "checkin")
def _log_checkin(dbapi_connection, connection_record):
    logger.warning("[db:checkin] dbapi_connection=%s record=%s", id(dbapi_connection), id(connection_record))


@event.listens_for(engine.sync_engine, "invalidate")
def _log_invalidate(dbapi_connection, connection_record, exception):
    logger.error(
        "[db:invalidate] dbapi_connection=%s record=%s exception=%s",
        id(dbapi_connection),
        id(connection_record),
        exception,
        exc_info=exception,
    )
    _log_sqlite_file_state("invalidate")


@event.listens_for(engine.sync_engine, "begin")
def _log_begin(conn):
    logger.warning("[db:tx] begin conn=%s", id(conn))


@event.listens_for(engine.sync_engine, "commit")
def _log_commit(conn):
    logger.warning("[db:tx] commit conn=%s", id(conn))
    _log_sqlite_file_state("commit")


@event.listens_for(engine.sync_engine, "rollback")
def _log_rollback(conn):
    logger.warning("[db:tx] rollback conn=%s", id(conn))
    _log_sqlite_file_state("rollback")


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _log_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    summary = _statement_summary(statement)
    op = summary.split(" ", 1)[0].upper() if summary else ""
    context._db_diag_start = perf_counter()
    if op in {"INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "PRAGMA"}:
        logger.warning(
            "[db:sql:start] conn=%s op=%s executemany=%s sql=%s",
            id(conn),
            op,
            executemany,
            summary,
        )


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _log_after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    summary = _statement_summary(statement)
    op = summary.split(" ", 1)[0].upper() if summary else ""
    if op in {"INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "PRAGMA"}:
        elapsed_ms = int((perf_counter() - getattr(context, "_db_diag_start", perf_counter())) * 1000)
        logger.warning(
            "[db:sql:ok] conn=%s op=%s elapsed_ms=%s rowcount=%s",
            id(conn),
            op,
            elapsed_ms,
            cursor.rowcount,
        )


@event.listens_for(engine.sync_engine, "handle_error")
def _log_handle_error(exception_context):
    original = exception_context.original_exception
    sqlite_code = getattr(original, "sqlite_errorcode", None)
    sqlite_name = getattr(original, "sqlite_errorname", None)
    logger.error(
        "[db:sql:error] original=%r sqlite_code=%r sqlite_name=%r is_disconnect=%s statement=%s parameters_summary=%s",
        original,
        sqlite_code,
        sqlite_name,
        exception_context.is_disconnect,
        _statement_summary(exception_context.statement),
        _parameters_summary(exception_context.parameters),
        exc_info=original,
    )
    log_database_probe("sql-error")


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """初始化数据库表。

    NOTE: 使用 create_all 仅创建不存在的表，不会修改已有表结构。
    如需 schema migration，请使用 Alembic:
      pip install alembic && alembic init migrations
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # 手动 ALTER TABLE 兜底老库的字段补齐
    await _apply_manual_migrations()


async def _apply_manual_migrations() -> None:
    """对 SQLite 老库做字段补齐（create_all 不会改已有表结构）。"""
    from sqlalchemy import text

    statements = [
        # v5: tasks.tree_node_id
        "ALTER TABLE tasks ADD COLUMN tree_node_id VARCHAR(12)",
        # v7: multi-source purpose executions
        "ALTER TABLE tasks ADD COLUMN purpose_execution_id VARCHAR(12)",
        "CREATE INDEX IF NOT EXISTS ix_tasks_purpose_execution_id ON tasks (purpose_execution_id)",
    ]
    async with engine.begin() as conn:
        for stmt in statements:
            try:
                await conn.execute(text(stmt))
                logger.warning("[migration] applied: %s", stmt)
            except Exception as exc:
                # 列已存在时会报错，吞掉
                msg = str(exc).lower()
                if "duplicate column" in msg or "already exists" in msg:
                    continue
                logger.warning("[migration] skipped %s (%s)", stmt, exc)


DEFAULT_CATEGORY_TREE = {
    "环境问题": ["工具问题", "端口被占用", "环境映射失败", "版本不匹配", "env.json异常"],
    "脚本问题": ["等待时间问题", "脚本逻辑问题", "前后脚本影响"],
    "产品问题": ["断言失败", "已知问题", "未知问题", "端口占用失败", "AgileTest失败", "修改引入问题"],
    "测试策略问题": [],
    "无法识别": ["测试套失败"],
}


async def seed_default_categories():
    """首次启动时写入默认的两级分类树（已存在的按名字跳过）。"""
    from sqlalchemy import select
    from app.models.task import Category

    async with async_session() as session:
        existing = {
            (c.name, c.parent_id)
            for c in (await session.execute(select(Category))).scalars()
        }
        name_to_id = {
            c.name: c.id
            for c in (await session.execute(
                select(Category).where(Category.parent_id.is_(None))
            )).scalars()
        }
        for parent_name, children in DEFAULT_CATEGORY_TREE.items():
            if parent_name not in name_to_id:
                parent = Category(name=parent_name)
                session.add(parent)
                await session.flush()
                name_to_id[parent_name] = parent.id
            for child_name in children:
                if (child_name, name_to_id[parent_name]) not in existing:
                    session.add(Category(name=child_name, parent_id=name_to_id[parent_name]))
        await session.commit()

async def seed_default_users():
    """首次启动时创建默认管理员账号（admin / admin123）。"""
    from sqlalchemy import select
    from app.models.user import User, UserRole
    from app.auth import hash_password

    async with async_session() as session:
        existing = (await session.execute(
            select(User).where(User.username == "admin")
        )).scalar_one_or_none()
        if not existing:
            session.add(User(
                username="admin",
                hashed_password=hash_password("admin123"),
                role=UserRole.admin,
            ))
            await session.commit()
