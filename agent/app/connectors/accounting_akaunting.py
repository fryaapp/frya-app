from __future__ import annotations

import httpx

from app.connectors.contracts import AccountingConnector


class AkauntingConnector(AccountingConnector):
    """Akaunting connector starts intentionally conservative.

    Financial truth is Akaunting. This connector exposes read and draft boundaries only.
    """

    def __init__(self, base_url: str, token: str | None) -> None:
        self.base_url = base_url.rstrip('/')
        self.token = token

    def _headers(self) -> dict[str, str]:
        headers = {'Accept': 'application/json'}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        return headers

    async def get_object(self, object_type: str, object_id: str) -> dict:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f'{self.base_url}/api/{object_type}/{object_id}',
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.json()

    async def create_booking_draft(self, payload: dict) -> dict:
        return {
            'status': 'stub',
            'message': 'create_booking_draft ist als sicherer Stub implementiert und fuehrt keine Buchung aus.',
            'payload': payload,
        }
