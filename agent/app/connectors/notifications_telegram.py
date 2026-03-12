from __future__ import annotations

import httpx

from app.connectors.contracts import NotificationConnector, NotificationMessage


class TelegramConnector(NotificationConnector):
    def __init__(self, bot_token: str | None) -> None:
        self.bot_token = bot_token

    async def send(self, message: NotificationMessage) -> dict:
        if not self.bot_token:
            return {'ok': False, 'reason': 'telegram_bot_token_missing'}

        url = f'https://api.telegram.org/bot{self.bot_token}/sendMessage'
        payload = {'chat_id': message.target, 'text': message.text}

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, json=payload)
            return {'ok': response.is_success, 'status_code': response.status_code, 'body': response.text}
