"""P-45 R2: Tests for backfill-case-metadata endpoint."""
from __future__ import annotations


def test_backfill_endpoint_exists():
    """Backfill endpoint is registered."""
    from app.api.customer_api import router
    paths = [r.path for r in router.routes if hasattr(r, 'path')]
    # router has prefix '/api/v1', so the full path is '/api/v1/admin/backfill-case-metadata'
    assert any('backfill-case-metadata' in p for p in paths)
