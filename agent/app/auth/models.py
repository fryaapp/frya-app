from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

RoleName = Literal['operator', 'admin', 'customer']


class AuthUser(BaseModel):
    username: str
    role: RoleName
    tenant_id: str | None = None


class AuthUserRecord(AuthUser):
    password_hash: str


class SessionUser(BaseModel):
    username: str
    role: RoleName
