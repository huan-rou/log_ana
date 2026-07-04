"""认证 API：登录、当前用户、用户管理（仅管理员）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User, UserRole
from app.auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    require_admin,
)

router = APIRouter()

# ── Schemas ──

class LoginRequest(BaseModel):
    username: str
    password: str = Field(max_length=20)


class LoginResponse(BaseModel):
    token: str
    user: dict


class CreateUserRequest(BaseModel):
    username: str
    password: str = Field(max_length=20)
    role: str = "visitor"


@router.post("/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """用户名 + 密码登录，返回 JWT token。"""
    user = (await db.execute(
        select(User).where(User.username == req.username)
    )).scalar_one_or_none()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(401, "用户名或密码错误")
    token = create_access_token(user.id, user.username, user.role.value)
    return LoginResponse(
        token=token,
        user={"id": user.id, "username": user.username, "role": user.role.value},
    )


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息。"""
    return {
        "id": current_user.id,
        "username": current_user.username,
        "role": current_user.role.value,
    }


@router.get("/users")
async def list_users(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """管理员：列出所有用户。"""
    rows = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    return [
        {"id": u.id, "username": u.username, "role": u.role.value, "created_at": u.created_at}
        for u in rows
    ]


@router.post("/users")
async def create_user(
    req: CreateUserRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """管理员：创建新用户。"""
    # 用户名唯一性检查
    existing = (await db.execute(
        select(User).where(User.username == req.username)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(400, "用户名已存在")

    try:
        role = UserRole(req.role)
    except ValueError:
        raise HTTPException(400, f"无效的角色: {req.role}。可选: visitor, analyst, reviewer, admin")

    user = User(
        username=req.username,
        hashed_password=hash_password(req.password),
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {"id": user.id, "username": user.username, "role": user.role.value}


@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    req: CreateUserRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """管理员：修改用户（角色、密码）。"""
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "用户不存在")

    try:
        user.role = UserRole(req.role)
    except ValueError:
        raise HTTPException(400, f"无效的角色: {req.role}")

    if req.password:
        user.hashed_password = hash_password(req.password)

    await db.commit()
    return {"id": user.id, "username": user.username, "role": user.role.value}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """管理员：删除用户。"""
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "用户不存在")
    if user.role == UserRole.admin:
        admin_count = (await db.execute(
            select(User).where(User.role == UserRole.admin)
        )).scalars().all()
        if len(admin_count) <= 1:
            raise HTTPException(400, "不能删除最后一个管理员")
    await db.delete(user)
    await db.commit()
    return {"ok": True}
