"""Tenant-aware Database Connection Pool.

Setzt app.current_tenant bei JEDER Connection aus dem Pool,
BEVOR irgendeine Query ausgefuehrt wird.
Setzt den Wert zurueck wenn die Connection zurueck in den Pool geht.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import asyncpg

logger = logging.getLogger(__name__)


@asynccontextmanager
async def tenant_connection(
    database_url: str,
    tenant_id: str,
) -> AsyncGenerator[asyncpg.Connection, None]:
    """Acquires a connection and sets the tenant context for RLS.

    Usage:
        async with tenant_connection(db_url, tenant_id) as conn:
            rows = await conn.fetch("SELECT * FROM frya_bookings")
            # RLS filters automatically by tenant_id
    """
    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute(
            "SELECT set_config('app.current_tenant', $1, false)",
            tenant_id,
        )
        yield conn
    finally:
        try:
            await conn.execute("RESET app.current_tenant")
        except Exception:
            pass
        await conn.close()


@asynccontextmanager
async def tenant_pool_connection(
    pool: asyncpg.Pool,
    tenant_id: str,
) -> AsyncGenerator[asyncpg.Connection, None]:
    """Same as tenant_connection but from an existing pool."""
    async with pool.acquire() as conn:
        await conn.execute(
            "SELECT set_config('app.current_tenant', $1, false)",
            tenant_id,
        )
        try:
            yield conn
        finally:
            try:
                await conn.execute("RESET app.current_tenant")
            except Exception:
                pass
