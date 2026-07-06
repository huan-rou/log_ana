"""pytest 全局配置。

- 加载 backend/.env（如果存在）
- 把 backend/ 加到 sys.path 便于 import app.*
"""
import os
import sys
from pathlib import Path

# 把 backend 根目录加到 sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# 加载 .env（如果存在）
env_file = BACKEND_DIR / ".env"
if env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
    except ImportError:
        # dotenv 不是必装依赖；config.py 用 pydantic-settings 会自己读
        pass

# 测试环境用内存 SQLite
os.environ.setdefault("LA_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("LA_AUDIT_ENABLED", "false")
os.environ.setdefault("LA_APP_DEBUG_LOGGING", "false")
