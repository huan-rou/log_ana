from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import init_db, seed_default_categories, seed_default_users
from app.models.user import User  # noqa: F401 — ensure table is created
from app.models import mapping  # noqa: F401 — ensure mapping tables are created
from app.models import rule  # noqa: F401 — ensure rule editor tables are created
from app.api import tasks, logs, analysis, feedback, rules as rules_api, browse, audit, review
from app.api import auth, mapping
from app.services.storage.provider_manager import init_providers, shutdown_providers
from app.core.audit_logger import init_audit_logger
from app.services.rule_registry import rule_registry
from app.database import async_session

logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.warning("[startup] init_db starting")
    try:
        await init_db()
        await seed_default_categories()
        await seed_default_users()
        logger.warning("[startup] init_db completed")
    except Exception as exc:
        logger.exception("[startup] init_db failed: %s", exc)
        raise

    # 启动时同步一次规则：保证 builtin 规则已建 AnalysisRule，user 规则已 discover
    try:
        await rule_registry.discover()
        async with async_session() as s:
            await rule_registry.sync_to_db(s)
        logger.warning("[startup] rules discovered & synced: %d", len(rule_registry.get_all()))
    except Exception as exc:
        logger.exception("[startup] rule discover/sync failed: %s", exc)
        # 不阻塞启动：若 sync 失败可在首个任务时再重试

    init_providers()
    init_audit_logger(str(settings.audit_dir), settings.audit_enabled)
    yield
    await shutdown_providers()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

# CORS — allow Vue dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routers
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(logs.router, prefix="/api/logs", tags=["logs"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["analysis"])
app.include_router(feedback.router, prefix="/api/feedback", tags=["feedback"])
app.include_router(rules_api.router, prefix="/api/rules", tags=["rules"])
app.include_router(browse.router, prefix="/api/browse", tags=["browse"])
app.include_router(audit.router, prefix="/api/audit", tags=["audit"])
app.include_router(review.router, prefix="/api/review", tags=["review"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(mapping.router, prefix="/api/mapping", tags=["mapping"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": settings.app_version}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
