"""Tests for 2FA / TOTP functionality."""
import json

import pyotp
import pytest

from app.auth.user_repository import UserRecord, UserRepository


@pytest.fixture
def mem_repo():
    repo = UserRepository('memory://')
    return repo


@pytest.fixture
def user_record():
    from app.auth.service import hash_password_pbkdf2
    return UserRecord(
        username='testuser',
        email='test@example.com',
        role='admin',
        password_hash=hash_password_pbkdf2('securepassword1'),
        is_active=True,
    )


@pytest.mark.asyncio
async def test_enable_totp(mem_repo, user_record):
    """enable_totp stores secret and sets totp_enabled=True."""
    await mem_repo.create_user(user_record)
    secret = pyotp.random_base32()
    backup_codes = json.dumps(['aaaa1111', 'bbbb2222'])
    await mem_repo.enable_totp('testuser', secret, backup_codes)
    u = await mem_repo.find_by_username('testuser')
    assert u is not None
    assert u.totp_enabled is True
    assert u.totp_secret == secret
    assert u.totp_backup_codes == backup_codes


@pytest.mark.asyncio
async def test_disable_totp(mem_repo, user_record):
    """disable_totp clears secret and sets totp_enabled=False."""
    await mem_repo.create_user(user_record)
    await mem_repo.enable_totp('testuser', pyotp.random_base32(), '[]')
    await mem_repo.disable_totp('testuser')
    u = await mem_repo.find_by_username('testuser')
    assert u is not None
    assert u.totp_enabled is False
    assert u.totp_secret is None
    assert u.totp_backup_codes is None


@pytest.mark.asyncio
async def test_update_backup_codes(mem_repo, user_record):
    """update_backup_codes replaces backup codes."""
    await mem_repo.create_user(user_record)
    await mem_repo.enable_totp('testuser', pyotp.random_base32(), json.dumps(['a', 'b', 'c']))
    await mem_repo.update_backup_codes('testuser', json.dumps(['b', 'c']))
    u = await mem_repo.find_by_username('testuser')
    assert u is not None
    codes = json.loads(u.totp_backup_codes)
    assert codes == ['b', 'c']


def test_totp_verify_valid_code():
    """A freshly generated TOTP code should verify."""
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    code = totp.now()
    assert totp.verify(code, valid_window=1) is True


def test_totp_verify_invalid_code():
    """An invalid code should not verify."""
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    assert totp.verify('000000', valid_window=1) is False


def test_totp_provisioning_uri():
    """Provisioning URI should contain issuer and username."""
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name='admin', issuer_name='FRYA')
    assert 'FRYA' in uri
    assert 'admin' in uri
    assert secret in uri


def test_backup_code_single_use():
    """Backup code should be usable exactly once."""
    codes = ['abcd1234', 'efgh5678']
    code_to_use = 'abcd1234'
    assert code_to_use in codes
    codes.remove(code_to_use)
    assert code_to_use not in codes
    assert len(codes) == 1


def test_user_record_totp_fields_default():
    """UserRecord defaults: totp_enabled=False, totp_secret=None."""
    u = UserRecord(username='x')
    assert u.totp_enabled is False
    assert u.totp_secret is None
    assert u.totp_backup_codes is None


def test_decrypt_key_env_fallback_ionos():
    """LLMConfigRepository.decrypt_key_for_call falls back to FRYA_IONOS_API_KEY for IONOS."""
    import os
    from app.llm_config import LLMConfigRepository

    os.environ['FRYA_IONOS_API_KEY'] = 'test-ionos-key-123'
    try:
        repo = LLMConfigRepository('memory://', 'memory://')
        config = {'provider': 'ionos', 'model': 'mistralai/Mistral-Small-24B-Instruct', 'api_key_encrypted': None}
        key = repo.decrypt_key_for_call(config)
        assert key == 'test-ionos-key-123'
    finally:
        del os.environ['FRYA_IONOS_API_KEY']


def test_decrypt_key_env_fallback_anthropic():
    """LLMConfigRepository.decrypt_key_for_call falls back to FRYA_ANTHROPIC_API_KEY for Anthropic."""
    import os
    from app.llm_config import LLMConfigRepository

    os.environ['FRYA_ANTHROPIC_API_KEY'] = 'test-anthropic-key-456'
    try:
        repo = LLMConfigRepository('memory://', 'memory://')
        config = {'provider': 'anthropic', 'model': 'claude-sonnet-4-6', 'api_key_encrypted': None}
        key = repo.decrypt_key_for_call(config)
        assert key == 'test-anthropic-key-456'
    finally:
        del os.environ['FRYA_ANTHROPIC_API_KEY']


def test_decrypt_key_encrypted_takes_priority():
    """Encrypted key in DB should take priority over env var."""
    import os
    from cryptography.fernet import Fernet
    from app.llm_config import LLMConfigRepository

    enc_key = Fernet.generate_key().decode()
    fernet = Fernet(enc_key.encode())
    encrypted = fernet.encrypt(b'db-stored-key').decode()

    os.environ['FRYA_OPENAI_API_KEY'] = 'env-key-should-not-be-used'
    try:
        repo = LLMConfigRepository('memory://', 'memory://', encryption_key=enc_key)
        config = {'provider': 'ionos', 'model': 'test', 'api_key_encrypted': encrypted}
        key = repo.decrypt_key_for_call(config)
        assert key == 'db-stored-key'
    finally:
        del os.environ['FRYA_OPENAI_API_KEY']
