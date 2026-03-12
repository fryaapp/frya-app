from __future__ import annotations

import httpx

from app.connectors.contracts import DMSConnector


class PaperlessConnector(DMSConnector):
    def __init__(self, base_url: str, token: str | None) -> None:
        self.base_url = base_url.rstrip('/')
        self.token = token

    def _headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        return {'Authorization': f'Token {self.token}'}

    async def get_document(self, doc_id: str) -> dict:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f'{self.base_url}/api/documents/{doc_id}/', headers=self._headers())
            response.raise_for_status()
            return response.json()

    async def search_documents(self, query: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f'{self.base_url}/api/documents/',
                params={'query': query},
                headers=self._headers(),
            )
            response.raise_for_status()
            payload = response.json()
            return payload.get('results', []) if isinstance(payload, dict) else []

    async def add_tag(self, doc_id: str, tag: str) -> None:
        document = await self.get_document(doc_id)
        current_tags = document.get('tags', [])
        if tag in current_tags:
            return
        new_tags = current_tags + [tag]
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.patch(
                f'{self.base_url}/api/documents/{doc_id}/',
                headers=self._headers(),
                json={'tags': new_tags},
            )
            response.raise_for_status()
