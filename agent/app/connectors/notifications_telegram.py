from __future__ import annotations

import json

import httpx

from app.connectors.contracts import NotificationConnector, NotificationMessage


class TelegramConnector(NotificationConnector):
    def __init__(self, bot_token: str | None) -> None:
        self.bot_token = bot_token

    async def send(self, message: NotificationMessage, disable_notification: bool = False) -> dict:
        if not self.bot_token:
            return {'ok': False, 'reason': 'telegram_bot_token_missing'}

        url = f'https://api.telegram.org/bot{self.bot_token}/sendMessage'
        payload: dict = {'chat_id': message.target, 'text': message.text, 'disable_notification': disable_notification}
        if message.reply_markup:
            payload['reply_markup'] = message.reply_markup

        async with httpx.AsyncClient(timeout=20) as client:
            try:
                response = await client.post(url, json=payload)
            except httpx.HTTPError as exc:
                return {'ok': False, 'reason': 'telegram_send_failed', 'status_code': None, 'body': str(exc)}
            return {
                'ok': response.is_success,
                'status_code': response.status_code,
                'body': response.text,
                'json': self._safe_json(response.text),
            }

    async def get_file_info(self, file_id: str) -> dict:
        if not self.bot_token:
            return {'ok': False, 'reason': 'telegram_bot_token_missing'}

        url = f'https://api.telegram.org/bot{self.bot_token}/getFile'
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                response = await client.get(url, params={'file_id': file_id})
            except httpx.HTTPError as exc:
                return {'ok': False, 'reason': 'telegram_get_file_failed', 'status_code': None, 'body': str(exc)}
            return {
                'ok': response.is_success,
                'status_code': response.status_code,
                'body': response.text,
                'json': self._safe_json(response.text),
                'reason': None if response.is_success else 'telegram_get_file_failed',
            }

    async def download_file(self, file_path: str) -> dict:
        if not self.bot_token:
            return {'ok': False, 'reason': 'telegram_bot_token_missing'}

        url = f'https://api.telegram.org/file/bot{self.bot_token}/{file_path}'
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.get(url)
            except httpx.HTTPError as exc:
                return {'ok': False, 'reason': 'telegram_file_download_failed', 'status_code': None, 'body': str(exc)}
            return {
                'ok': response.is_success,
                'status_code': response.status_code,
                'body': None if response.is_success else response.text,
                'content': response.content if response.is_success else b'',
                'content_type': response.headers.get('content-type'),
                'reason': None if response.is_success else 'telegram_file_download_failed',
            }

    @staticmethod
    def _safe_json(payload: str) -> dict | None:
        try:
            parsed = json.loads(payload)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None
