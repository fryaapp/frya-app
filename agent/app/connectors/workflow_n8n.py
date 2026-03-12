from __future__ import annotations

import httpx

from app.connectors.contracts import WorkflowConnector


class N8NConnector(WorkflowConnector):
    def __init__(self, base_url: str, token: str | None) -> None:
        self.base_url = base_url.rstrip('/')
        self.token = token

    def _headers(self, idempotency_key: str) -> dict[str, str]:
        headers = {'X-Idempotency-Key': idempotency_key}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        return headers

    async def trigger(self, workflow_name: str, payload: dict, idempotency_key: str) -> dict:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f'{self.base_url}/webhook/{workflow_name}',
                json=payload,
                headers=self._headers(idempotency_key),
            )
            return {'ok': response.is_success, 'status_code': response.status_code, 'body': response.text}
