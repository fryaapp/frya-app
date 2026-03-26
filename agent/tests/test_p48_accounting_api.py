"""Tests for P-48 accounting API endpoints."""
import pytest


def test_accounting_router_exists():
    from app.api.accounting_api import router
    assert router.prefix == '/api/v1'
    paths = [r.path for r in router.routes if hasattr(r, 'path')]
    assert '/api/v1/bookings' in paths
    assert '/api/v1/contacts' in paths
    assert '/api/v1/invoices' in paths
    assert '/api/v1/open-items' in paths
    assert '/api/v1/reports/euer' in paths
    assert '/api/v1/reports/ust' in paths
    assert '/api/v1/reports/account-balances' in paths
    assert '/api/v1/admin/verify-hash-chain' in paths
