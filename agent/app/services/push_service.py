"""Firebase Cloud Messaging push notification service.

Usage:
  from app.services.push_service import send_push, save_push_token, init_firebase, ensure_push_tokens_table

  # In lifespan:
  init_firebase()
  await ensure_push_tokens_table()

  # When a user registers a device:
  await save_push_token(tenant_id, fcm_token, platform='android')

  # When sending a notification:
  await send_push(tenant_id, title='Frya', body='Neuer Beleg verarbeitet.', data={'screen': 'inbox'})
"""
from __future__ import annotations

import logging
import os
import uuid

logger = logging.getLogger(__name__)

_firebase_initialized = False


def init_firebase() -> None:
    """Initialize the Firebase Admin SDK (idempotent — safe to call multiple times)."""
    global _firebase_initialized
    if _firebase_initialized:
        return
    try:
        import firebase_admin
        from firebase_admin import credentials

        if not firebase_admin._apps:
            cred_path = os.environ.get(
                'GOOGLE_APPLICATION_CREDENTIALS',
                '/app/firebase-service-account.json',
            )
            if not os.path.exists(cred_path):
                logger.warning(
                    'Firebase service account not found at %s — push notifications disabled.',
                    cred_path,
                )
                return
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)

        _firebase_initialized = True
        logger.info('Firebase Admin SDK initialized (project: %s)', firebase_admin.get_app().project_id)
    except ImportError:
        logger.warning('firebase-admin package not installed — push notifications disabled.')
    except Exception as exc:
        logger.warning('Firebase Admin SDK initialization failed: %s', exc)


async def ensure_push_tokens_table() -> None:
    """Create the frya_push_tokens table if it does not yet exist."""
    try:
        from app.dependencies import get_db_pool
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS frya_push_tokens (
                    tenant_id  UUID         NOT NULL,
                    token      TEXT         NOT NULL,
                    platform   VARCHAR(20)  NOT NULL DEFAULT 'android',
                    updated_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
                    PRIMARY KEY (tenant_id, platform)
                )
            """)
        logger.debug('frya_push_tokens table ensured')
    except Exception as exc:
        logger.warning('Could not ensure frya_push_tokens table: %s', exc)


async def save_push_token(tenant_id: str, token: str, platform: str = 'android') -> None:
    """Upsert an FCM push token for a tenant+platform combination."""
    from app.dependencies import get_db_pool
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO frya_push_tokens (tenant_id, token, platform, updated_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (tenant_id, platform)
            DO UPDATE SET token = EXCLUDED.token, updated_at = now()
            """,
            uuid.UUID(tenant_id),
            token,
            platform,
        )
    logger.debug('Push token saved for tenant %s (%s)', tenant_id, platform)


async def send_push(
    tenant_id: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> bool:
    """Send a push notification to all registered devices of a tenant.

    Returns True if at least one message was sent successfully.
    """
    if not _firebase_initialized:
        logger.debug('Firebase not initialized — skipping push for tenant %s', tenant_id)
        return False

    try:
        from app.dependencies import get_db_pool
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                'SELECT token, platform FROM frya_push_tokens WHERE tenant_id = $1',
                uuid.UUID(tenant_id),
            )

        if not rows:
            logger.debug('No push tokens registered for tenant %s', tenant_id)
            return False

        from firebase_admin import messaging

        sent_any = False
        for row in rows:
            token = row['token']
            if not token:
                continue
            try:
                msg = messaging.Message(
                    notification=messaging.Notification(title=title, body=body),
                    data={k: str(v) for k, v in (data or {}).items()},
                    token=token,
                    android=messaging.AndroidConfig(
                        priority='high',
                        notification=messaging.AndroidNotification(
                            icon='ic_notification',
                            color='#E87830',
                            channel_id='frya_default',
                        ),
                    ),
                )
                messaging.send(msg)
                logger.info('Push sent to tenant %s (%s): %s', tenant_id, row['platform'], title)
                sent_any = True
            except Exception as exc:
                logger.warning('Push send failed for tenant %s token %s: %s', tenant_id, token[:20], exc)

        return sent_any

    except Exception as exc:
        logger.error('send_push error for tenant %s: %s', tenant_id, exc)
        return False
