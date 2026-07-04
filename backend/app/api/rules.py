from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.task import AnalysisRule, Category
from app.auth import require_admin

router = APIRouter()


@router.get("/")
async def list_rules(db: AsyncSession = Depends(get_db)):
    """获取所有规则。"""
    result = await db.execute(
        select(AnalysisRule).order_by(AnalysisRule.priority)
    )
    return result.scalars().all()


@router.get("/{rule_id}")
async def get_rule(rule_id: str, db: AsyncSession = Depends(get_db)):
    """获取单条规则。"""
    result = await db.execute(
        select(AnalysisRule).where(AnalysisRule.rule_id == rule_id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(404, "Rule not found")
    return rule


@router.post("/reload")
async def reload_rules(_admin=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """重新扫描 rules/ 目录，同步数据库中的规则元数据。"""
    from app.services.rule_registry import rule_registry

    await rule_registry.discover()
    rules = await rule_registry.sync_to_db(db)
    return {"rules": len(rules), "status": "reloaded"}
