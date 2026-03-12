from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

RoleName = Literal['operator', 'admin']


class AuthUser(BaseModel):
    username: str
    role: RoleName


class AuthUserRecord(AuthUser):
    password_hash: str


class SessionUser(BaseModel):
    username: str
    role: RoleName
