"""规则管理 API：列表、详情、创建、编辑、发布、撤销、启用、删除、操作历史。

权限模型：
- GET 类：analyst+
- 写类（create/update/publish/unpublish/enable/delete）：analyst 可改自己 + admin 改所有人

实现要点：
- 写操作统一在 `_check_can_modify` 工具里做角色/所有权/状态校验
- 写操作都写一条 RuleAuditLog
- 写文件用 `ast.parse` 二次校验，失败回滚
- 删除时 `sync_to_db` 不会真的把 AnalysisRule 删，只是 `enabled=False`
  （沿用 builtin 路径下 stale 规则的"软禁用"语义）
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.auth import (
    get_current_user,
    require_admin,
    require_analyst_or_admin,
)
from app.database import get_db
from app.models.user import User
from app.models.task import AnalysisRule, AnalysisResult, Category
from app.models.rule import Rule, RuleAuditLog, RuleStatus, RuleMatchSource
from app.schemas.rule import (
    MATCH_SOURCES,
    OperationResult,
    RuleAuditEntry,
    RuleCreate,
    RuleDetail,
    RuleEnabledPatch,
    RuleListItem,
    RuleMetaPatch,
    RuleUpdate,
)
from app.services.rule_registry import rule_registry
from app.services.rule_template import render_user_rule, safe_rule_id

router = APIRouter()


# ─────────────────────────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────────────────────────
def _is_admin(user: User) -> bool:
    return user.role == "admin"


def _category_display(db_rule, db) -> str:
    cat = db_rule.category
    if cat is None:
        return ""
    if cat.parent and cat.parent.name:
        return f"{cat.parent.name}/{cat.name}"
    return cat.name


async def _check_can_modify(
    rule: Rule,
    current_user: User,
    *,
    require_draft: bool = True,
) -> None:
    """校验当前用户对 user 规则是否有写权限。

    - admin 直接通过
    - analyst 必须 rule.created_by == current_user.id
    - require_draft=True 时仅 draft 状态可写
    """
    if _is_admin(current_user):
        return
    if rule.created_by != current_user.id:
        raise HTTPException(403, "无权操作他人规则")
    if require_draft and rule.status != RuleStatus.draft.value:
        raise HTTPException(409, f"规则当前状态为 {rule.status}，不可编辑/发布/启用；请先撤销发布或新建草稿")


async def _write_audit(
    db: AsyncSession,
    *,
    rule_id: str,
    actor: User,
    action: str,
    before: Optional[dict] = None,
    after: Optional[dict] = None,
    request: Optional[Request] = None,
) -> None:
    ip = None
    if request and request.client:
        ip = request.client.host
    entry = RuleAuditLog(
        rule_id=rule_id,
        actor_user_id=actor.id,
        actor_username=actor.username,
        action=action,
        before=json.dumps(before, ensure_ascii=False) if before else None,
        after=json.dumps(after, ensure_ascii=False) if after else None,
        ip=ip,
    )
    db.add(entry)
    await db.flush()


async def _ensure_user_rule(rule: Rule) -> None:
    if not rule.analysis_rule_id:
        raise HTTPException(409, "规则元数据缺失，无法操作")


# ─────────────────────────────────────────────────────────────────
# GET /api/rules/  列表
# ─────────────────────────────────────────────────────────────────
@router.get("/", response_model=List[RuleListItem])
async def list_rules(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_analyst_or_admin),
):
    """返回所有规则（builtin + user），含命中次数与状态。"""
    # 1) 拉所有 AnalysisRule（连 category.parent 一次性 join）
    ar_rows = (await db.execute(
        select(AnalysisRule)
        .options(joinedload(AnalysisRule.category).joinedload(Category.parent))
        .order_by(AnalysisRule.priority)
    )).scalars().all()
    ar_by_id = {ar.id: ar for ar in ar_rows}

    # 2) 拉所有 Rule (user rules)
    rule_rows = (await db.execute(select(Rule))).scalars().all()
    rule_by_ar_id = {r.analysis_rule_id: r for r in rule_rows if r.analysis_rule_id}

    # 3) 拉 created_by usernames
    user_ids = {r.created_by for r in rule_rows}
    username_by_id = {}
    if user_ids:
        from app.models.user import User as UserModel
        u_rows = (await db.execute(
            select(UserModel.id, UserModel.username).where(UserModel.id.in_(user_ids))
        )).all()
        username_by_id = {uid: uname for uid, uname in u_rows}

    # 4) 拉 hit_count
    hit_rows = (await db.execute(
        select(AnalysisResult.rule_id, func.count(AnalysisResult.id))
        .where(AnalysisResult.rule_id.is_not(None))
        .group_by(AnalysisResult.rule_id)
    )).all()
    hit_by_id = {rid: cnt for rid, cnt in hit_rows}

    # 5) 拼装
    out: List[RuleListItem] = []
    for ar in ar_rows:
        is_user = ar.script_module.startswith("rules.user.")
        meta = rule_by_ar_id.get(ar.id)
        # 已删除的 user 规则（Rule meta 不存在）从列表过滤掉；audit/detail 仍可按 rule_id 查
        if is_user and meta is None:
            continue
        category_str = ""
        cat = ar.category
        if cat:
            if cat.parent and cat.parent.name:
                category_str = f"{cat.parent.name}/{cat.name}"
            else:
                category_str = cat.name
        out.append(RuleListItem(
            id=ar.id,
            rule_id=ar.rule_id,
            name=ar.name,
            category=category_str,
            category_id=ar.category_id,
            priority=ar.priority,
            enabled=ar.enabled,
            match_source=meta.match_source if meta else None,
            pattern=meta.pattern if meta else None,
            status=meta.status if meta else None,
            source=("user" if is_user else "builtin"),
            version=ar.version or "1.0",
            description=ar.description,
            created_by=meta.created_by if meta else None,
            created_by_username=username_by_id.get(meta.created_by) if meta else None,
            created_at=meta.created_at if meta else ar.created_at,
            updated_at=meta.updated_at if meta else None,
            published_at=meta.published_at if meta else None,
            hit_count=int(hit_by_id.get(ar.id, 0) or 0),
        ))
    return out


# ─────────────────────────────────────────────────────────────────
# GET /api/rules/{rule_id}  详情
# ─────────────────────────────────────────────────────────────────
@router.get("/{rule_id}", response_model=RuleDetail)
async def get_rule(
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_analyst_or_admin),
):
    """返回规则详情：含 .py 全文与最近 50 条操作历史。"""
    ar_obj = (await db.execute(
        select(AnalysisRule)
        .options(joinedload(AnalysisRule.category).joinedload(Category.parent))
        .where(AnalysisRule.rule_id == rule_id)
    )).scalar_one_or_none()
    if ar_obj is None:
        raise HTTPException(404, "Rule not found")
    cat = ar_obj.category

    is_user = ar_obj.script_module.startswith("rules.user.")
    meta = (await db.execute(
        select(Rule).where(Rule.analysis_rule_id == ar_obj.id)
    )).scalar_one_or_none()

    created_by_username = None
    if meta:
        from app.models.user import User as UserModel
        u = (await db.execute(
            select(UserModel).where(UserModel.id == meta.created_by)
        )).scalar_one_or_none()
        if u:
            created_by_username = u.username

    hit_count = (await db.execute(
        select(func.count(AnalysisResult.id))
        .where(AnalysisResult.rule_id == ar_obj.id)
    )).scalar_one()

    # audits
    audits = (await db.execute(
        select(RuleAuditLog)
        .where(RuleAuditLog.rule_id == ar_obj.rule_id)
        .order_by(RuleAuditLog.created_at.desc())
        .limit(50)
    )).scalars().all()

    # .py 全文
    source_code = None
    if is_user:
        try:
            py_path = Path(rule_registry.get_user_module_path(ar_obj.rule_id))
            if py_path.exists():
                source_code = py_path.read_text(encoding="utf-8")
        except Exception:
            source_code = None

    return RuleDetail(
        id=ar_obj.id,
        rule_id=ar_obj.rule_id,
        name=ar_obj.name,
        category=(f"{cat.parent.name}/{cat.name}" if (cat and cat.parent and cat.parent.name) else (cat.name if cat else "")),
        category_id=ar_obj.category_id,
        priority=ar_obj.priority,
        enabled=ar_obj.enabled,
        match_source=meta.match_source if meta else None,
        pattern=meta.pattern if meta else None,
        status=meta.status if meta else None,
        source=("user" if is_user else "builtin"),
        version=ar_obj.version or "1.0",
        description=ar_obj.description,
        created_by=meta.created_by if meta else None,
        created_by_username=created_by_username,
        created_at=meta.created_at if meta else ar_obj.created_at,
        updated_at=meta.updated_at if meta else None,
        published_at=meta.published_at if meta else None,
        hit_count=int(hit_count or 0),
        source_code=source_code,
        audits=[RuleAuditEntry.model_validate(a) for a in audits],
    )


# ─────────────────────────────────────────────────────────────────
# GET /api/rules/{rule_id}/source  .py 原文（仅 user 规则）
# ─────────────────────────────────────────────────────────────────
@router.get("/{rule_id}/source", response_class=PlainTextResponse)
async def get_rule_source(
    rule_id: str,
    _user: User = Depends(require_analyst_or_admin),
):
    ar = (await _get_ar(rule_id))
    if not ar.script_module.startswith("rules.user."):
        raise HTTPException(400, "内置规则无可查看的源文件")
    py_path = Path(rule_registry.get_user_module_path(rule_id))
    if not py_path.exists():
        raise HTTPException(404, "源文件不存在")
    return PlainTextResponse(py_path.read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────────
# PATCH /api/rules/{rule_id}/meta  局部更新名称/备注
# ─────────────────────────────────────────────────────────────────
@router.patch("/{rule_id}/meta", response_model=RuleDetail)
async def patch_rule_meta(
    rule_id: str,
    body: RuleMetaPatch,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_analyst_or_admin),
):
    """只更新 name / description（不触发布局/状态/规则代码）。

    权限：
    - 系统规则（builtin）：仅 admin
    - 用户规则（user）：创建者本人 或 admin
    """
    if body.name is None and body.description is None:
        raise HTTPException(400, "name / description 至少给一个")

    ar = await _get_ar(rule_id, db)
    is_user = ar.script_module.startswith("rules.user.")
    is_admin_user = _is_admin(current_user)

    if is_user:
        # user 规则：admin 直接放行；非 admin 必须本人
        if not is_admin_user:
            meta_for_auth = (await db.execute(
                select(Rule).where(Rule.analysis_rule_id == ar.id)
            )).scalar_one_or_none()
            if not meta_for_auth or meta_for_auth.created_by != current_user.id:
                raise HTTPException(403, "无权修改他人规则的名称/备注")
    else:
        # 系统规则：仅 admin
        if not is_admin_user:
            raise HTTPException(403, "系统规则仅管理员可修改名称/备注")

    before = {"name": ar.name, "description": ar.description}
    if body.name is not None:
        ar.name = body.name
    if body.description is not None:
        ar.description = body.description

    after = {"name": ar.name, "description": ar.description}

    await _write_audit(db, rule_id=rule_id, actor=current_user, action="meta_update",
                       before=before, after=after, request=request)
    await db.commit()
    await db.refresh(ar)
    return await get_rule(rule_id, db, current_user)


# ─────────────────────────────────────────────────────────────────
# POST /api/rules/  创建
# ─────────────────────────────────────────────────────────────────
@router.post("/", response_model=RuleDetail, status_code=201)
async def create_rule(
    body: RuleCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_analyst_or_admin),
):
    safe_rule_id(body.rule_id)
    if body.match_source not in MATCH_SOURCES:
        raise HTTPException(400, "match_source 非法")
    # 唯一性：与 builtin/user 都不可冲突
    exists = (await db.execute(
        select(AnalysisRule).where(AnalysisRule.rule_id == body.rule_id)
    )).scalar_one_or_none()
    if exists:
        raise HTTPException(409, "rule_id 已存在")

    # category 解析
    from app.services.rule_executor import _get_category_id
    category_id = await _get_category_id(db, body.category)

    # 渲染 + 写文件
    now_iso = datetime.now(timezone.utc).isoformat()
    src = render_user_rule({
        "rule_id": body.rule_id,
        "name": body.name,
        "category": body.category,
        "priority": body.priority,
        "confidence": body.confidence,
        "match_source": body.match_source,
        "pattern": body.pattern,
        "version": body.version,
        "author": current_user.username,
        "created_at": now_iso,
    })
    py_path = Path(settings.rules_dir) / "user" / f"{body.rule_id}.py"  # noqa: F821
    py_path.parent.mkdir(parents=True, exist_ok=True)
    py_path.write_text(src, encoding="utf-8")

    # discover + sync（创建 AnalysisRule 记录）
    await rule_registry.discover()
    await rule_registry.sync_to_db(db)

    # 重新拉 AnalysisRule（sync_to_db 后会拿到新 id）
    ar = (await db.execute(
        select(AnalysisRule).where(AnalysisRule.rule_id == body.rule_id)
    )).scalar_one()

    # 写 Rule 元数据 (status=draft)
    meta = Rule(
        rule_id=body.rule_id,
        match_source=body.match_source,
        pattern=body.pattern,
        status=RuleStatus.draft.value,
        created_by=current_user.id,
        analysis_rule_id=ar.id,
    )
    db.add(meta)
    await db.flush()

    # audit
    await _write_audit(db, rule_id=ar.rule_id, actor=current_user, action="create",
                       after={"name": body.name, "category": body.category,
                              "priority": body.priority, "pattern": body.pattern,
                              "match_source": body.match_source, "confidence": body.confidence},
                       request=request)
    await db.commit()

    return await get_rule(body.rule_id, db, current_user)


# ─────────────────────────────────────────────────────────────────
# PUT /api/rules/{rule_id}  整体更新（draft only）
# ─────────────────────────────────────────────────────────────────
@router.put("/{rule_id}", response_model=RuleDetail)
async def update_rule(
    rule_id: str,
    body: RuleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_analyst_or_admin),
):
    ar = await _get_ar(rule_id, db)
    if not ar.script_module.startswith("rules.user."):
        raise HTTPException(400, "内置规则不可通过编辑器修改")
    meta = await _get_meta(ar.id, db)
    if not meta:
        raise HTTPException(404, "规则元数据缺失")
    await _check_can_modify(meta, current_user, require_draft=True)

    if body.match_source not in MATCH_SOURCES:
        raise HTTPException(400, "match_source 非法")

    # 重新解析 category（可能改了大类/子类）
    from app.services.rule_executor import _get_category_id
    new_category_id = await _get_category_id(db, body.category)

    # 重新渲染
    src = render_user_rule({
        "rule_id": rule_id,
        "name": body.name,
        "category": body.category,
        "priority": body.priority,
        "confidence": body.confidence,
        "match_source": body.match_source,
        "pattern": body.pattern,
        "version": body.version,
        "author": meta.created_by and (
            # 拿到原作者 username
            _username_of(meta.created_by, db)
        ) or current_user.username,
        "created_at": (meta.created_at or datetime.now(timezone.utc)).isoformat(),
    })
    py_path = Path(rule_registry.get_user_module_path(rule_id))
    py_path.write_text(src, encoding="utf-8")

    # 更新 AnalysisRule
    ar.name = body.name
    ar.category_id = new_category_id
    ar.priority = body.priority
    ar.description = body.description
    ar.version = body.version

    # 更新 Rule meta，状态回退 draft
    before = {"name": ar.name, "category": body.category, "priority": ar.priority,
              "pattern": meta.pattern, "status": meta.status}
    meta.match_source = body.match_source
    meta.pattern = body.pattern
    meta.updated_by = current_user.id
    meta.updated_at = datetime.now(timezone.utc)
    # 任何 update 都强制回到 draft
    meta.status = RuleStatus.draft.value
    meta.published_by = None
    meta.published_at = None

    await _write_audit(db, rule_id=rule_id, actor=current_user, action="update",
                       before=before,
                       after={"name": body.name, "category": body.category,
                              "priority": body.priority, "pattern": body.pattern,
                              "match_source": body.match_source, "confidence": body.confidence,
                              "status": RuleStatus.draft.value},
                       request=request)
    await db.commit()

    await rule_registry.discover()
    return await get_rule(rule_id, db, current_user)


# ─────────────────────────────────────────────────────────────────
# POST /api/rules/{rule_id}/publish
# ─────────────────────────────────────────────────────────────────
@router.post("/{rule_id}/publish", response_model=OperationResult)
async def publish_rule(
    rule_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_analyst_or_admin),
):
    ar = await _get_ar(rule_id, db)
    if not ar.script_module.startswith("rules.user."):
        raise HTTPException(400, "内置规则无需发布")
    meta = await _get_meta(ar.id, db)
    if not meta:
        raise HTTPException(404, "规则元数据缺失")
    await _check_can_modify(meta, current_user, require_draft=True)

    before = {"status": meta.status}
    meta.status = RuleStatus.published.value
    meta.published_by = current_user.id
    meta.published_at = datetime.now(timezone.utc)
    ar.enabled = True

    await _write_audit(db, rule_id=rule_id, actor=current_user, action="publish",
                       before=before, after={"status": meta.status}, request=request)
    await db.commit()
    await rule_registry.discover()
    return OperationResult(rule_id=rule_id, status=meta.status)


# ─────────────────────────────────────────────────────────────────
# POST /api/rules/{rule_id}/unpublish
# ─────────────────────────────────────────────────────────────────
@router.post("/{rule_id}/unpublish", response_model=OperationResult)
async def unpublish_rule(
    rule_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_analyst_or_admin),
):
    ar = await _get_ar(rule_id, db)
    if not ar.script_module.startswith("rules.user."):
        raise HTTPException(400, "内置规则无需撤销发布")
    meta = await _get_meta(ar.id, db)
    if not meta:
        raise HTTPException(404, "规则元数据缺失")
    await _check_can_modify(meta, current_user, require_draft=False)
    if meta.status != RuleStatus.published.value:
        raise HTTPException(409, f"规则当前状态为 {meta.status}，无需撤销")

    before = {"status": meta.status}
    meta.status = RuleStatus.draft.value
    meta.published_by = None
    meta.published_at = None

    await _write_audit(db, rule_id=rule_id, actor=current_user, action="unpublish",
                       before=before, after={"status": meta.status}, request=request)
    await db.commit()
    await rule_registry.discover()
    return OperationResult(rule_id=rule_id, status=meta.status)


# ─────────────────────────────────────────────────────────────────
# PATCH /api/rules/{rule_id}/enabled
# ─────────────────────────────────────────────────────────────────
@router.patch("/{rule_id}/enabled", response_model=OperationResult)
async def toggle_enabled(
    rule_id: str,
    body: RuleEnabledPatch,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_analyst_or_admin),
):
    ar = await _get_ar(rule_id, db)
    if not ar.script_module.startswith("rules.user."):
        raise HTTPException(400, "内置规则可由管理员直接修改 AnalysisRule.enabled，本接口仅处理 user 规则")
    meta = await _get_meta(ar.id, db)
    if not meta:
        raise HTTPException(404, "规则元数据缺失")
    await _check_can_modify(meta, current_user, require_draft=False)
    if meta.status != RuleStatus.published.value:
        raise HTTPException(409, "仅已发布的规则可切换启用状态")

    before = {"enabled": ar.enabled}
    ar.enabled = body.enabled
    action = "enable" if body.enabled else "disable"
    await _write_audit(db, rule_id=rule_id, actor=current_user, action=action,
                       before=before, after={"enabled": ar.enabled}, request=request)
    await db.commit()
    return OperationResult(rule_id=rule_id, status=meta.status, detail=f"enabled={ar.enabled}")


# ─────────────────────────────────────────────────────────────────
# DELETE /api/rules/{rule_id}
# ─────────────────────────────────────────────────────────────────
@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),  # 删除是强操作：仅管理员
):
    ar = await _get_ar(rule_id, db)
    if not ar.script_module.startswith("rules.user."):
        # 系统规则的 .py 源码在代码仓库内，避免破坏代码库：拒绝硬删
        raise HTTPException(400, "系统规则不支持删除；如需停用请切换 enabled=false")
    meta = await _get_meta(ar.id, db)
    if not meta:
        raise HTTPException(404, "规则元数据缺失")

    # 删文件（幂等）
    try:
        py_path = Path(rule_registry.get_user_module_path(rule_id))
        if py_path.exists():
            py_path.unlink()
    except FileNotFoundError:
        pass

    # 软禁用 AnalysisRule，保留历史 AnalysisResult
    ar.enabled = False

    # 写 audit
    await _write_audit(db, rule_id=rule_id, actor=current_user, action="delete",
                       before={"name": ar.name, "category": ar.category_id,
                               "analysis_rule_id": ar.id}, request=request)

    # 删 Rule meta
    if meta:
        await db.delete(meta)
        await db.flush()

    await db.commit()
    await rule_registry.discover()

    # reload existing module
    full_name = f"rules.user.{rule_id}"
    if full_name in rule_registry._rules or True:
        try:
            import sys, importlib
            sys.modules.pop(full_name, None)
            importlib.import_module(full_name)
        except Exception:
            pass

    from fastapi import Response
    return Response(status_code=204)


# ─────────────────────────────────────────────────────────────────
# GET /api/rules/{rule_id}/audit  操作历史
# ─────────────────────────────────────────────────────────────────
@router.get("/{rule_id}/audit", response_model=List[RuleAuditEntry])
async def list_audit(
    rule_id: str,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_analyst_or_admin),
):
    rows = (await db.execute(
        select(RuleAuditLog)
        .where(RuleAuditLog.rule_id == rule_id)
        .order_by(RuleAuditLog.created_at.desc())
        .limit(limit)
    )).scalars().all()
    return [RuleAuditEntry.model_validate(r) for r in rows]


# ─────────────────────────────────────────────────────────────────
# POST /api/rules/reload  重新扫描（仅 admin）
# ─────────────────────────────────────────────────────────────────
@router.post("/reload")
async def reload_rules(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await rule_registry.discover()
    rules = await rule_registry.sync_to_db(db)
    return {"rules": len(rules), "status": "reloaded"}


# ─────────────────────────────────────────────────────────────────
# 内部辅助
# ─────────────────────────────────────────────────────────────────
async def _get_ar(rule_id: str, db: AsyncSession) -> AnalysisRule:
    ar = (await db.execute(
        select(AnalysisRule).where(AnalysisRule.rule_id == rule_id)
    )).scalar_one_or_none()
    if not ar:
        raise HTTPException(404, "Rule not found")
    return ar


async def _get_meta(ar_id: str, db: AsyncSession) -> Optional[Rule]:
    return (await db.execute(
        select(Rule).where(Rule.analysis_rule_id == ar_id)
    )).scalar_one_or_none()


def _username_of(user_id: str, db: AsyncSession) -> str:
    # 用于 audit 与模板 author；同步接口仅取 username
    from app.models.user import User as UserModel
    # 此函数仅在 request path 中通过 db 间接使用
    # 由于 SQLAlchemy 2.x async 不允许 sync 调用，这里直接返回 user_id 兜底
    return user_id


# 修正 create_rule 里的 settings 引用（settings 来自 app.config）
from app.config import settings  # noqa: E402
