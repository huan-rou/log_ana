from __future__ import annotations

from pydantic_settings import BaseSettings
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _resolve_backend_path(path: Path | str) -> Path:
    path = Path(path)
    if path.is_absolute():
        return path
    return (BACKEND_DIR / path).resolve()


class Settings(BaseSettings):
    # Application
    app_name: str = "Log Analyzer"
    app_version: str = "0.1.0"
    debug: bool = True

    # Database — 相对路径会在首次访问 database_url_absolute 时解析为绝对路径
    database_url: str = "sqlite+aiosqlite:///./data/log_analyzer.db"
    sqlite_journal_mode: str = "WAL"
    sqlite_busy_timeout_ms: int = 30000
    sqlite_temp_store: str = "MEMORY"
    db_diagnostics_enabled: bool = True
    db_direct_probe_enabled: bool = False
    db_diagnostics_log_file: Path = Path("./data/db_diagnostics.log")

    @property
    def database_url_absolute(self) -> str:
        """返回绝对路径的数据库 URL，防止工作目录变化导致 SQLite 找不到文件。"""
        if "///" in self.database_url:
            prefix, rel = self.database_url.split("///", 1)
            if rel == ":memory:":
                return self.database_url
            abs_path = _resolve_backend_path(rel)
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            return f"{prefix}///{abs_path.as_posix()}"
        return self.database_url

    # Storage
    upload_dir: Path = Path("./data/uploads")
    workspace_dir: Path = Path("./data/workspaces")

    # S3 / RustFS
    s3_enabled: bool = False
    s3_endpoint_url: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = ""
    s3_prefix: str = ""
    s3_region: str = "us-east-1"

    # Rule Engine
    rules_dir: Path = Path("./rules")
    rule_execution_mode: str = "parallel"  # "serial" | "parallel"
    rule_first_match_wins: bool = True

    # Audit log
    audit_enabled: bool = True
    audit_dir: Path = Path("./data/audit")

    # App debug logging (v5 新增)
    # 默认开启：发布时设 LA_APP_DEBUG_LOGGING=false 关闭所有 INFO/DEBUG
    app_debug_logging: bool = True
    log_file: Path = Path("./data/app.log")

    # Auth
    jwt_secret: str = "log-analyzer-secret-change-in-production"

    # Server
    host: str = "127.0.0.1"
    port: int = 8000

    model_config = {"env_prefix": "LA_", "env_file": BACKEND_DIR / ".env"}

    def model_post_init(self, __context) -> None:
        self.upload_dir = _resolve_backend_path(self.upload_dir)
        self.workspace_dir = _resolve_backend_path(self.workspace_dir)
        self.rules_dir = _resolve_backend_path(self.rules_dir)
        self.audit_dir = _resolve_backend_path(self.audit_dir)
        self.log_file = _resolve_backend_path(self.log_file)
        self.db_diagnostics_log_file = _resolve_backend_path(self.db_diagnostics_log_file)


settings = Settings()

# Ensure directories exist
settings.upload_dir.mkdir(parents=True, exist_ok=True)
settings.workspace_dir.mkdir(parents=True, exist_ok=True)
(BACKEND_DIR / "data").mkdir(parents=True, exist_ok=True)
settings.db_diagnostics_log_file.parent.mkdir(parents=True, exist_ok=True)
