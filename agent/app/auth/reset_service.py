"""Password reset and invitation token service.

Redis key layout:
  frya:pw_reset:{token}          → username   (TTL 30 min)
  frya:invite:{token}            → username   (TTL 72 h)
  frya:pw_reset_attempts:{token} → int        (TTL 30 min, max 5)
  frya:rate:forgotpw:{ip}        → int        (TTL 600 s, max 3)
"""
from __future__ import annotations

import secrets
import time

PW_RESET_TTL = 30 * 60        # 30 minutes in seconds
INVITE_TTL = 72 * 60 * 60    # 72 hours in seconds
MAX_RESET_ATTEMPTS = 5
RATE_LIMIT_WINDOW = 600       # 10 minutes
RATE_LIMIT_MAX = 3


class PasswordResetService:
    def __init__(self, redis_url: str) -> None:
        self.redis_url = redis_url
        # In-memory fallback for tests
        self._tokens: dict[str, tuple[str, float]] = {}   # token → (username, expires_at)
        self._attempts: dict[str, int] = {}               # token → count
        self._rate: dict[str, tuple[int, float]] = {}     # ip → (count, window_start)

    @property
    def is_memory(self) -> bool:
        return self.redis_url.startswith('memory://')

    def _redis(self):
        import redis.asyncio as aioredis
        return aioredis.Redis.from_url(self.redis_url, decode_responses=True)

    # ── Token issuance ────────────────────────────────────────────────────────

    async def issue_reset_token(self, username: str) -> str:
        token = secrets.token_urlsafe(32)
        if self.is_memory:
            self._tokens[token] = (username, time.time() + PW_RESET_TTL)
            return token
        async with self._redis() as r:
            await r.set(f'frya:pw_reset:{token}', username, ex=PW_RESET_TTL)
        return token

    async def issue_invite_token(self, username: str) -> str:
        token = secrets.token_urlsafe(32)
        if self.is_memory:
            self._tokens[f'invite:{token}'] = (username, time.time() + INVITE_TTL)
            return token
        async with self._redis() as r:
            await r.set(f'frya:invite:{token}', username, ex=INVITE_TTL)
        return token

    # ── Token validation ──────────────────────────────────────────────────────

    async def validate_token(self, token: str) -> str | None:
        """Returns username if token is valid, None otherwise. Does NOT consume."""
        if self.is_memory:
            entry = self._tokens.get(token) or self._tokens.get(f'invite:{token}')
            if not entry:
                return None
            username, expires_at = entry
            if time.time() >= expires_at:
                return None
            # Check attempts
            if self._attempts.get(token, 0) >= MAX_RESET_ATTEMPTS:
                return None
            return username
        async with self._redis() as r:
            attempts_key = f'frya:pw_reset_attempts:{token}'
            attempts_raw = await r.get(attempts_key)
            if attempts_raw and int(attempts_raw) >= MAX_RESET_ATTEMPTS:
                await r.delete(f'frya:pw_reset:{token}', f'frya:invite:{token}')
                return None
            username = await r.get(f'frya:pw_reset:{token}')
            if username is None:
                username = await r.get(f'frya:invite:{token}')
            return username

    async def consume_token(self, token: str) -> str | None:
        """Validate and delete the token (single-use). Returns username or None."""
        if self.is_memory:
            entry = self._tokens.pop(token, None) or self._tokens.pop(f'invite:{token}', None)
            if not entry:
                return None
            username, expires_at = entry
            self._attempts.pop(token, None)
            return username if time.time() < expires_at else None
        async with self._redis() as r:
            username = await r.getdel(f'frya:pw_reset:{token}')
            if username is None:
                username = await r.getdel(f'frya:invite:{token}')
            if username:
                await r.delete(f'frya:pw_reset_attempts:{token}')
            return username

    async def record_failed_attempt(self, token: str) -> int:
        """Increment failed attempt counter. Returns new count."""
        if self.is_memory:
            count = self._attempts.get(token, 0) + 1
            self._attempts[token] = count
            return count
        async with self._redis() as r:
            key = f'frya:pw_reset_attempts:{token}'
            count = await r.incr(key)
            await r.expire(key, PW_RESET_TTL)
            return count

    # ── Rate limiting ─────────────────────────────────────────────────────────

    async def check_rate_limit(self, ip: str) -> bool:
        """Returns True if request is allowed, False if rate-limited."""
        if self.is_memory:
            now = time.time()
            count, window_start = self._rate.get(ip, (0, now))
            if now - window_start > RATE_LIMIT_WINDOW:
                count, window_start = 0, now
            count += 1
            self._rate[ip] = (count, window_start)
            return count <= RATE_LIMIT_MAX
        async with self._redis() as r:
            key = f'frya:rate:forgotpw:{ip}'
            count = await r.incr(key)
            if count == 1:
                await r.expire(key, RATE_LIMIT_WINDOW)
            return count <= RATE_LIMIT_MAX
