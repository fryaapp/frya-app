"""Multi-provider mail abstraction.

Priority: tenant-specific config > Frya system-mail fallback
Providers: smtp, mailgun (tenant), brevo (system), frya_mailgun (system fallback)

System-mail provider is controlled by FRYA_MAIL_PROVIDER env var:
  FRYA_MAIL_PROVIDER=brevo   → routes password-reset/invite via Brevo API v3
  FRYA_MAIL_PROVIDER=mailgun → routes via Mailgun (legacy default)

SMTP passwords and Mailgun API keys are Fernet-encrypted in mail_config JSONB.

Inbound mail:
  Mailgun webhook (/webhooks/mailgun) is kept for potential future use.
  # Brevo Inbound requires Business plan — MVP uses Telegram for document ingestion
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import aiohttp

from app.audit.service import AuditService

logger = logging.getLogger(__name__)


class MailService:
    def __init__(
        self,
        audit_service: AuditService,
        *,
        database_url: str = '',
        mailgun_api_key: str | None = None,
        mailgun_domain: str | None = None,
        mailgun_from: str = 'noreply@frya.app',
        encryption_key: str | None = None,
        brevo_api_key: str | None = None,
        mail_provider: str = 'mailgun',
    ) -> None:
        self.audit_service = audit_service
        self.database_url = database_url
        self.mailgun_api_key = mailgun_api_key
        self.mailgun_domain = mailgun_domain
        self.mailgun_from = mailgun_from
        self._encryption_key = encryption_key
        self.brevo_api_key = brevo_api_key
        self.mail_provider = mail_provider

    def _fernet(self):
        if not self._encryption_key:
            return None
        from cryptography.fernet import Fernet
        return Fernet(self._encryption_key.encode())

    async def send_mail(
        self,
        *,
        to: str,
        subject: str,
        body_html: str,
        body_text: str,
        tenant_id: str | None = None,
        attachments: list[dict] | None = None,
    ) -> None:
        mail_config: dict[str, Any] | None = None
        if tenant_id:
            mail_config = await self._get_tenant_mail_config(tenant_id)

        try:
            if mail_config and mail_config.get('provider') == 'smtp':
                await self._send_smtp(to, subject, body_html, body_text, mail_config)
            elif mail_config and mail_config.get('provider') == 'mailgun':
                await self._send_mailgun(to, subject, body_html, body_text, mail_config)
            elif self.mail_provider == 'brevo':
                await self._send_brevo(to, subject, body_html, body_text, attachments=attachments)
            else:
                await self._send_frya_mailgun(to, subject, body_html, body_text)
        except Exception as exc:
            await self._log_failure(to, subject, str(exc), tenant_id)
            raise

    async def send_test_mail(self, *, to: str, tenant_id: str | None = None) -> None:
        await self.send_mail(
            to=to,
            subject='FRYA Test-Mail',
            body_html='<p>Dies ist eine Test-Mail von FRYA.</p>',
            body_text='Dies ist eine Test-Mail von FRYA.',
            tenant_id=tenant_id,
        )

    async def _get_tenant_mail_config(self, tenant_id: str) -> dict[str, Any] | None:
        if not self.database_url or self.database_url.startswith('memory://'):
            return None
        try:
            import asyncpg
            conn = await asyncpg.connect(self.database_url)
            try:
                row = await conn.fetchrow(
                    "SELECT mail_config FROM frya_tenants WHERE tenant_id = $1",
                    tenant_id,
                )
                if row and row['mail_config']:
                    cfg = row['mail_config']
                    if isinstance(cfg, dict):
                        return cfg
                    import json
                    return json.loads(cfg)
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning('MailService: tenant mail config fetch failed: %s', exc)
        return None

    def _decrypt(self, encrypted: str) -> str:
        f = self._fernet()
        if f is None:
            return encrypted
        try:
            return f.decrypt(encrypted.encode()).decode()
        except Exception as exc:
            logger.warning('MailService: decrypt failed: %s', exc)
            return encrypted

    async def _send_smtp(
        self,
        to: str,
        subject: str,
        body_html: str,
        body_text: str,
        config: dict[str, Any],
    ) -> None:
        host = config.get('smtp_host', '')
        port = int(config.get('smtp_port', 587))
        user = config.get('smtp_user', '')
        password = self._decrypt(config.get('smtp_password_enc', ''))
        from_addr = config.get('from_address', self.mailgun_from)

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = from_addr
        msg['To'] = to
        msg.attach(MIMEText(body_text, 'plain', 'utf-8'))
        msg.attach(MIMEText(body_html, 'html', 'utf-8'))

        loop = asyncio.get_event_loop()
        await asyncio.wait_for(
            loop.run_in_executor(
                None,
                self._smtp_send_sync,
                host, port, user, password, from_addr, to, msg,
            ),
            timeout=10.0,
        )

    @staticmethod
    def _smtp_send_sync(
        host: str, port: int, user: str, password: str,
        from_addr: str, to: str, msg: MIMEMultipart,
    ) -> None:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ctx)
            smtp.login(user, password)
            smtp.sendmail(from_addr, [to], msg.as_string())

    async def _send_mailgun(
        self,
        to: str,
        subject: str,
        body_html: str,
        body_text: str,
        config: dict[str, Any],
    ) -> None:
        api_key = self._decrypt(config.get('mailgun_api_key_enc', ''))
        domain = config.get('mailgun_domain', '')
        from_addr = config.get('from_address', f'noreply@{domain}')
        await self._mailgun_post(
            api_key=api_key,
            domain=domain,
            from_addr=from_addr,
            to=to,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
        )

    async def _send_frya_mailgun(
        self,
        to: str,
        subject: str,
        body_html: str,
        body_text: str,
    ) -> None:
        if not self.mailgun_api_key or not self.mailgun_domain:
            # No Frya Mailgun configured (dev/test mode): silently skip
            return
        await self._mailgun_post(
            api_key=self.mailgun_api_key,
            domain=self.mailgun_domain,
            from_addr=self.mailgun_from,
            to=to,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
        )

    async def _send_brevo(
        self,
        to: str,
        subject: str,
        body_html: str,
        body_text: str,
        attachments: list[dict] | None = None,
    ) -> None:
        if not self.brevo_api_key:
            # No Brevo API key configured (dev/test mode): silently skip
            return
        url = 'https://api.brevo.com/v3/smtp/email'
        payload: dict = {
            'sender': {'name': 'FRYA', 'email': self.mailgun_from},
            'to': [{'email': to}],
            'subject': subject,
            'htmlContent': body_html,
            'textContent': body_text,
        }
        # Aufgabe 7: Support file attachments (e.g. invoice PDFs)
        # Each attachment: {'name': 'rechnung.pdf', 'content': base64_str}
        if attachments:
            payload['attachment'] = [
                {'name': a['name'], 'content': a['content']}
                for a in attachments if a.get('name') and a.get('content')
            ]
        headers = {
            'api-key': self.brevo_api_key,
            'Content-Type': 'application/json',
        }
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status not in (200, 201, 202):
                    body = await resp.text()
                    raise RuntimeError(f'Brevo API error {resp.status}: {body[:200]}')

    @staticmethod
    async def _mailgun_post(
        *,
        api_key: str,
        domain: str,
        from_addr: str,
        to: str,
        subject: str,
        body_html: str,
        body_text: str,
    ) -> None:
        url = f'https://api.eu.mailgun.net/v3/{domain}/messages'
        data = {
            'from': from_addr,
            'to': to,
            'subject': subject,
            'text': body_text,
            'html': body_html,
        }
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url,
                data=data,
                auth=aiohttp.BasicAuth('api', api_key),
            ) as resp:
                if resp.status not in (200, 202):
                    body = await resp.text()
                    raise RuntimeError(f'Mailgun API error {resp.status}: {body[:200]}')

    async def _log_failure(
        self,
        to: str,
        subject: str,
        error: str,
        tenant_id: str | None,
    ) -> None:
        try:
            await self.audit_service.log_event({
                'event_id': str(uuid.uuid4()),
                'case_id': f'mail-error:{tenant_id or "frya"}',
                'source': 'mail',
                'agent_name': 'mail-service',
                'approval_status': 'NOT_REQUIRED',
                'action': 'MAIL_SEND_FAILED',
                'result': error[:200],
                'llm_output': {'to': to, 'subject': subject, 'error': error[:500]},
            })
        except Exception as exc:
            logger.warning('MailService: audit log_failure failed: %s', exc)
