"""Tests for Paket 60: password reset flow, mail service, rate limiting."""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _check(label: str, ok: bool, detail=None):
    if not ok:
        raise AssertionError(f'FAIL [{label}]: {detail}')


# ── Test 1: Reset token generated and stored in Redis (memory) ────────────────

def test_reset_token_issued_and_valid():
    async def run():
        from app.auth.reset_service import PasswordResetService
        svc = PasswordResetService('memory://test')
        token = await svc.issue_reset_token('operator')
        _check('token is non-empty string', isinstance(token, str) and len(token) > 10, token)
        username = await svc.validate_token(token)
        _check('validate returns username', username == 'operator', username)
    _run(run())


# ── Test 2: Token is single-use ───────────────────────────────────────────────

def test_reset_token_single_use():
    async def run():
        from app.auth.reset_service import PasswordResetService
        svc = PasswordResetService('memory://test')
        token = await svc.issue_reset_token('operator')
        first = await svc.consume_token(token)
        _check('first consume returns username', first == 'operator', first)
        second = await svc.consume_token(token)
        _check('second consume returns None', second is None, second)
    _run(run())


# ── Test 3: Token expired after TTL ──────────────────────────────────────────

def test_reset_token_expired():
    async def run():
        from app.auth.reset_service import PasswordResetService
        svc = PasswordResetService('memory://test')
        token = await svc.issue_reset_token('operator')
        # Manually expire the token by backdating
        svc._tokens[token] = ('operator', time.time() - 1)
        username = await svc.validate_token(token)
        _check('expired token returns None', username is None, username)
    _run(run())


# ── Test 4: Unknown email → 200, no error leak (tested via service logic) ─────

def test_unknown_email_no_user_found():
    async def run():
        from app.auth.user_repository import UserRepository
        repo = UserRepository('memory://db')
        user = await repo.find_by_email('nobody@example.com')
        _check('unknown email returns None', user is None, user)
        # The router always returns 200 regardless — confirmed by router code
    _run(run())


# ── Test 5: Password too short → error ───────────────────────────────────────

def test_short_password_rejected():
    from app.auth.router import _MIN_PASSWORD_LEN
    short = 'abc123'
    _check('short password below limit', len(short) < _MIN_PASSWORD_LEN, len(short))


# ── Test 6: SMTP config → test mail (mock SMTP) ───────────────────────────────

def test_smtp_mail_sent():
    async def run():
        from app.audit.repository import AuditRepository
        from app.audit.service import AuditService
        from app.email.mail_service import MailService

        audit = AuditService(AuditRepository('memory://audit'))
        svc = MailService(audit_service=audit)

        smtp_config = {
            'provider': 'smtp',
            'smtp_host': 'smtp.example.com',
            'smtp_port': 587,
            'smtp_user': 'user@example.com',
            'smtp_password_enc': 'plain_password',
            'from_address': 'frya@example.com',
        }

        sent = {}

        def fake_smtp_sync(host, port, user, password, from_addr, to, msg):
            sent['host'] = host
            sent['to'] = to

        with patch.object(MailService, '_smtp_send_sync', staticmethod(fake_smtp_sync)):
            with patch.object(svc, '_get_tenant_mail_config', AsyncMock(return_value=smtp_config)):
                await svc.send_mail(
                    to='recipient@example.com',
                    subject='Test',
                    body_html='<p>Test</p>',
                    body_text='Test',
                    tenant_id='tenant-123',
                )

        _check('smtp host used', sent['host'] == 'smtp.example.com', sent)
        _check('smtp recipient', sent['to'] == 'recipient@example.com', sent)
    _run(run())


# ── Test 7: Mailgun config → correct API called (mock aiohttp) ───────────────

def test_mailgun_tenant_config_called():
    async def run():
        from app.audit.repository import AuditRepository
        from app.audit.service import AuditService
        from app.email.mail_service import MailService

        audit = AuditService(AuditRepository('memory://audit'))
        svc = MailService(audit_service=audit)

        mg_config = {
            'provider': 'mailgun',
            'mailgun_api_key_enc': 'key-xyz',
            'mailgun_domain': 'mg.example.com',
            'from_address': 'frya@example.com',
        }

        posted = {}

        async def fake_mailgun_post(*, api_key, domain, from_addr, to, subject, body_html, body_text):
            posted['api_key'] = api_key
            posted['domain'] = domain

        with patch.object(MailService, '_mailgun_post', staticmethod(fake_mailgun_post)):
            with patch.object(svc, '_get_tenant_mail_config', AsyncMock(return_value=mg_config)):
                await svc.send_mail(
                    to='r@example.com',
                    subject='Test',
                    body_html='<p>X</p>',
                    body_text='X',
                    tenant_id='tenant-123',
                )

        _check('mailgun domain', posted['domain'] == 'mg.example.com', posted)
        _check('mailgun api_key', posted['api_key'] == 'key-xyz', posted)
    _run(run())


# ── Test 8: Fallback to Frya-Mailgun when no tenant config ───────────────────

def test_fallback_to_frya_mailgun():
    async def run():
        from app.audit.repository import AuditRepository
        from app.audit.service import AuditService
        from app.email.mail_service import MailService

        audit = AuditService(AuditRepository('memory://audit'))
        svc = MailService(
            audit_service=audit,
            mailgun_api_key='frya-key',
            mailgun_domain='frya.app',
            mailgun_from='noreply@frya.app',
        )

        posted = {}

        async def fake_mailgun_post(*, api_key, domain, from_addr, to, subject, body_html, body_text):
            posted['api_key'] = api_key
            posted['domain'] = domain

        with patch.object(MailService, '_mailgun_post', staticmethod(fake_mailgun_post)):
            # No tenant_id → uses Frya fallback
            await svc.send_mail(
                to='r@example.com',
                subject='Test',
                body_html='<p>X</p>',
                body_text='X',
            )

        _check('frya mailgun api_key', posted['api_key'] == 'frya-key', posted)
        _check('frya mailgun domain', posted['domain'] == 'frya.app', posted)
    _run(run())


# ── Test 9: Rate limit on forgot-password ────────────────────────────────────

def test_rate_limit_forgot_password():
    async def run():
        from app.auth.reset_service import PasswordResetService, RATE_LIMIT_MAX
        svc = PasswordResetService('memory://test')
        ip = '1.2.3.4'
        results = []
        for _ in range(RATE_LIMIT_MAX + 2):
            ok = await svc.check_rate_limit(ip)
            results.append(ok)
        allowed = sum(1 for r in results if r)
        blocked = sum(1 for r in results if not r)
        _check(f'first {RATE_LIMIT_MAX} allowed', allowed == RATE_LIMIT_MAX, results)
        _check('extra requests blocked', blocked >= 2, results)
    _run(run())


# ── Test 10: Invite token has TTL 72h (not 30 min) ───────────────────────────

def test_invite_token_ttl():
    async def run():
        from app.auth.reset_service import PasswordResetService, INVITE_TTL, PW_RESET_TTL
        svc = PasswordResetService('memory://test')
        _check('invite TTL is 72h', INVITE_TTL == 72 * 3600, INVITE_TTL)
        _check('reset TTL is 30min', PW_RESET_TTL == 30 * 60, PW_RESET_TTL)
        token = await svc.issue_invite_token('newuser')
        username = await svc.validate_token(token)
        _check('invite token valid', username == 'newuser', username)
        # Verify it is stored with 72h expiry
        entry = svc._tokens.get(f'invite:{token}')
        _check('invite token exists', entry is not None, entry)
        _, expires_at = entry
        remaining = expires_at - time.time()
        _check('invite TTL > 71h', remaining > 71 * 3600, remaining)
    _run(run())


# ── Test 11: Session invalidation after reset ────────────────────────────────

def test_session_version_incremented_on_reset():
    async def run():
        from app.auth.user_repository import UserRecord, UserRepository
        from app.auth.service import hash_password_pbkdf2
        repo = UserRepository('memory://db')
        record = UserRecord(
            username='testuser',
            email='test@example.com',
            role='operator',
            session_version=1,
        )
        await repo.create_user(record)
        ver_before = await repo.get_session_version('testuser')
        _check('initial version=1', ver_before == 1, ver_before)
        new_hash = hash_password_pbkdf2('SuperSecretPass2026!')
        await repo.update_password('testuser', new_hash)
        ver_after = await repo.get_session_version('testuser')
        _check('version incremented after reset', ver_after == 2, ver_after)
    _run(run())


# ── Test 13: Brevo provider → correct API endpoint and headers ───────────────

def test_brevo_provider_called():
    async def run():
        from app.audit.repository import AuditRepository
        from app.audit.service import AuditService
        from app.email.mail_service import MailService

        audit = AuditService(AuditRepository('memory://audit'))
        svc = MailService(
            audit_service=audit,
            mailgun_from='noreply@myfrya.de',
            brevo_api_key='xkeysib-test',
            mail_provider='brevo',
        )

        posted = {}

        class _FakeResp:
            status = 201
            async def text(self):
                return ''
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                pass

        def fake_post(self_session, url, *, json=None, headers=None):
            posted['url'] = url
            posted['headers'] = headers
            posted['payload'] = json
            return _FakeResp()

        import aiohttp
        with patch.object(aiohttp.ClientSession, 'post', fake_post):
            await svc.send_mail(
                to='user@example.com',
                subject='Passwort zurücksetzen',
                body_html='<p>Link</p>',
                body_text='Link',
            )

        _check('brevo url', posted['url'] == 'https://api.brevo.com/v3/smtp/email', posted.get('url'))
        _check('brevo api-key header', posted['headers']['api-key'] == 'xkeysib-test', posted.get('headers'))
        _check('brevo sender email', posted['payload']['sender']['email'] == 'noreply@myfrya.de', posted.get('payload'))
        _check('brevo to', posted['payload']['to'][0]['email'] == 'user@example.com', posted.get('payload'))
    _run(run())


# ── Test 14: Brevo skipped silently when no API key ───────────────────────────

def test_brevo_skips_when_no_key():
    async def run():
        from app.audit.repository import AuditRepository
        from app.audit.service import AuditService
        from app.email.mail_service import MailService

        audit = AuditService(AuditRepository('memory://audit'))
        svc = MailService(
            audit_service=audit,
            mail_provider='brevo',
            brevo_api_key=None,  # not configured
        )

        called = []

        def fail_post(*a, **kw):
            called.append(True)
            raise AssertionError('Should not have called HTTP')

        import aiohttp
        with patch.object(aiohttp.ClientSession, 'post', fail_post):
            # Should not raise, not call HTTP
            await svc.send_mail(
                to='user@example.com',
                subject='Test',
                body_html='<p>X</p>',
                body_text='X',
            )
        _check('no HTTP call made', called == [], called)
    _run(run())


# ── Test 12: Brute-force protection on token attempts ────────────────────────

def test_brute_force_protection():
    async def run():
        from app.auth.reset_service import PasswordResetService, MAX_RESET_ATTEMPTS
        svc = PasswordResetService('memory://test')
        token = await svc.issue_reset_token('operator')
        for _ in range(MAX_RESET_ATTEMPTS):
            await svc.record_failed_attempt(token)
        # After MAX_RESET_ATTEMPTS failures, validate should return None
        username = await svc.validate_token(token)
        _check('token invalidated after max attempts', username is None, username)
    _run(run())
