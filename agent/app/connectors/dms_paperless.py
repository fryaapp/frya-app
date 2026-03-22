from __future__ import annotations

import asyncio
import logging

import httpx

from app.connectors.contracts import DMSConnector

logger = logging.getLogger(__name__)


class PaperlessConnector(DMSConnector):
    def __init__(self, base_url: str, token: str | None) -> None:
        self.base_url = base_url.rstrip('/')
        self.token = token

    def _headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        return {'Authorization': f'Token {self.token}'}

    async def download_document_bytes(self, doc_id: str) -> bytes:
        """Download the raw PDF/file bytes for a Paperless document.

        GET /api/documents/{doc_id}/download/
        Raises httpx.HTTPStatusError on 4xx/5xx.
        """
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(
                f'{self.base_url}/api/documents/{doc_id}/download/',
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.content

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

    async def upload_document(
        self, file_bytes: bytes, filename: str, title: str | None = None
    ) -> dict:
        """Upload a document to Paperless via POST /api/documents/post_document/.

        Returns: {'task_id': 'uuid-string'}
        Raises: httpx.HTTPStatusError on HTTP 4xx/5xx, httpx.TimeoutException on timeout.
        """
        files = {'document': (filename, file_bytes, 'application/octet-stream')}
        data: dict[str, str] = {}
        if title:
            data['title'] = title

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f'{self.base_url}/api/documents/post_document/',
                headers=self._headers(),
                files=files,
                data=data,
            )
            response.raise_for_status()
            return response.json()

    async def get_task_status(self, task_id: str) -> dict:
        """Query the processing status of an upload task.

        GET /api/tasks/?task_id={task_id}
        Returns task dict with keys: id, task_id, status, result, related_document, acknowledged
        Raises: httpx.HTTPStatusError on HTTP error.
        """
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f'{self.base_url}/api/tasks/',
                params={'task_id': task_id},
                headers=self._headers(),
            )
            response.raise_for_status()
            payload = response.json()
            # Paperless returns a list; pick the matching task
            if isinstance(payload, list) and payload:
                return payload[0]
            if isinstance(payload, list) and not payload:
                return {'task_id': task_id, 'status': 'PENDING', 'result': None, 'related_document': None}
            return payload

    async def upload_documents_batch(
        self,
        files: list[tuple[bytes, str]],
        max_concurrent: int = 5,
    ) -> list[dict]:
        """Upload multiple documents with concurrency limit.

        Uses asyncio.Semaphore(max_concurrent) to avoid overloading Paperless/Tika.
        Server has only 8GB RAM — do NOT fire all uploads in parallel.

        Args:
            files: List of (file_bytes, filename) tuples.
            max_concurrent: Max simultaneous uploads (default 5).

        Returns:
            List of {'filename': str, 'task_id': str|None, 'error': str|None}
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _upload_one(file_bytes: bytes, filename: str) -> dict:
            async with semaphore:
                try:
                    result = await self.upload_document(file_bytes, filename)
                    task_id = result.get('task_id') if isinstance(result, dict) else str(result)
                    return {'filename': filename, 'task_id': task_id, 'error': None}
                except Exception as exc:
                    logger.warning('Paperless upload failed for %s: %s', filename, exc)
                    return {'filename': filename, 'task_id': None, 'error': str(exc)}

        tasks = [_upload_one(fb, fn) for fb, fn in files]
        return list(await asyncio.gather(*tasks))

    async def find_or_create_correspondent(self, name: str) -> int | None:
        """Find correspondent by name or create new one."""
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    f'{self.base_url}/api/correspondents/',
                    headers=self._headers(),
                    params={'name__iexact': name},
                )
                resp.raise_for_status()
                results = resp.json().get('results', [])
                if results:
                    return results[0]['id']
                # Create new
                resp = await client.post(
                    f'{self.base_url}/api/correspondents/',
                    headers=self._headers(),
                    json={'name': name},
                )
                resp.raise_for_status()
                return resp.json().get('id')
        except Exception:
            return None

    async def find_or_create_document_type(self, name: str) -> int | None:
        """Find document type by name or create new one."""
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    f'{self.base_url}/api/document_types/',
                    headers=self._headers(),
                    params={'name__iexact': name},
                )
                resp.raise_for_status()
                results = resp.json().get('results', [])
                if results:
                    return results[0]['id']
                resp = await client.post(
                    f'{self.base_url}/api/document_types/',
                    headers=self._headers(),
                    json={'name': name},
                )
                resp.raise_for_status()
                return resp.json().get('id')
        except Exception:
            return None

    async def find_or_create_tag(self, name: str, color: str = '#2196F3') -> int | None:
        """Find tag by name or create new one."""
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    f'{self.base_url}/api/tags/',
                    headers=self._headers(),
                    params={'name__iexact': name},
                )
                resp.raise_for_status()
                results = resp.json().get('results', [])
                if results:
                    return results[0]['id']
                resp = await client.post(
                    f'{self.base_url}/api/tags/',
                    headers=self._headers(),
                    json={'name': name, 'color': color},
                )
                resp.raise_for_status()
                return resp.json().get('id')
        except Exception:
            return None

    async def update_document_metadata(self, doc_id: int, data: dict) -> bool:
        """PATCH document metadata (title, correspondent, document_type, tags)."""
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.patch(
                    f'{self.base_url}/api/documents/{doc_id}/',
                    headers=self._headers(),
                    json=data,
                )
                resp.raise_for_status()
                return True
        except Exception:
            return False
