"""认证模块：JWT 签发/验证 + bcrypt 密码哈希 + 权限依赖注入。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User, UserRole

# ── 密码哈希 ──
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── JWT 配置 ──
SECRET_KEY = settings.jwt_secret
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

# ── Bearer token 提取 ──
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: str, username: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """从 Bearer token 解析当前登录用户。未登录返回 401。"""
    if not credentials:
        raise HTTPException(401, "未登录，请先登录")
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(401, "登录已过期，请重新登录")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(401, "无效的登录凭证")
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(401, "用户不存在")
    return user


def require_role(*roles: UserRole):
    """生成 FastAPI 依赖：当前用户必须是指定角色之一。"""

    async def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(403, "权限不足，当前角色不允许执行此操作")
        return current_user

    return checker


# ── 常用权限组合 ──
require_admin = require_role(UserRole.admin)
require_write_review = require_role(UserRole.analyst, UserRole.reviewer, UserRole.admin)
require_start_task = require_role(UserRole.reviewer, UserRole.admin)

# ── 可选的当前用户（游客也可访问，但标记未登录） ──
async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if not credentials:
        return None
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    return (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
