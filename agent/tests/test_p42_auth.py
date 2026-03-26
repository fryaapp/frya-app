"""Tests for P-42: JWT Auth + Dual Auth."""
import os
import pytest

# Ensure required env vars are set before any Settings instantiation
os.environ.setdefault('FRYA_JWT_SECRET', 'test-secret-for-jwt-p42')
os.environ.setdefault('FRYA_DATABASE_URL', 'memory://')
os.environ.setdefault('FRYA_REDIS_URL', 'redis://localhost:6379/0')
os.environ.setdefault('FRYA_AUTH_SESSION_SECRET', 'test-session-secret')
os.environ.setdefault('FRYA_PAPERLESS_BASE_URL', 'http://localhost:8000')
os.environ.setdefault('FRYA_AKAUNTING_BASE_URL', 'http://localhost:9000')
os.environ.setdefault('FRYA_N8N_BASE_URL', 'http://localhost:5678')

# Clear cached settings so env vars take effect
from app.config import get_settings
get_settings.cache_clear()


def test_jwt_create_and_decode():
    from app.auth.jwt_auth import create_access_token, create_refresh_token, decode_token

    access = create_access_token('testuser', 'tenant-1', 'customer')
    payload = decode_token(access)
    assert payload['sub'] == 'testuser'
    assert payload['tid'] == 'tenant-1'
    assert payload['role'] == 'customer'
    assert payload['type'] == 'access'


def test_jwt_refresh_token():
    from app.auth.jwt_auth import create_refresh_token, decode_token

    refresh = create_refresh_token('testuser')
    payload = decode_token(refresh)
    assert payload['sub'] == 'testuser'
    assert payload['type'] == 'refresh'


def test_auth_user_has_customer_role():
    from app.auth.models import AuthUser
    user = AuthUser(username='customer1', role='customer', tenant_id='tid-1')
    assert user.role == 'customer'
    assert user.tenant_id == 'tid-1'


def test_auth_user_has_tenant_id():
    from app.auth.models import AuthUser
    user = AuthUser(username='op', role='operator')
    assert user.tenant_id is None


def test_login_request_model():
    from app.api.customer_api import LoginRequest
    req = LoginRequest(email='test@test.de', password='pw')
    assert req.email == 'test@test.de'


def test_require_role_exists():
    from app.auth.dependencies import require_role
    dep = require_role('admin', 'operator')
    assert callable(dep)


def test_connection_manager():
    from app.api.customer_api import ConnectionManager
    mgr = ConnectionManager()
    assert mgr.active_count == 0

@pytest.mark.asyncio
async def test_ws_validate_token_empty():
    from app.api.customer_api import _validate_ws_token
    result = await _validate_ws_token('')
    assert result is None


@pytest.mark.asyncio
async def test_ws_validate_token_valid():
    import os
    os.environ['FRYA_JWT_SECRET'] = 'test-secret-for-jwt-p42'
    from app.auth.jwt_auth import create_access_token
    from app.api.customer_api import _validate_ws_token
    token = create_access_token('wsuser', 'tid-1', 'customer')
    result = await _validate_ws_token(token)
    assert result is not None
    assert result.username == 'wsuser'
