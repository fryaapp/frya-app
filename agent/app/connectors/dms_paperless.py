from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse, urlunparse

import httpx

from app.connectors.contracts import DMSConnector

logger = logging.getLogger(__name__)


class PaperlessConnector(DMSConnector):
    def __init__(self, base_url: str, token: str | None) -> None:
        self.base_url = base_url.rstrip('/')
        self.token = token
        self._custom_field_cache: dict[str, int] = {}
        self._tenant_tag_cache: dict[str, int] = {}

    def _headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        return {'Authorization': f'Token {self.token}'}

    # ── Tenant-Isolation helpers ────────────────────────────────────

    async def _ensure_tenant_tag(self, tenant_id: str) -> int | None:
        """Ensure a Paperless tag ``tenant:<tenant_id>`` exists and return its ID.

        Uses an in-memory cache so repeated calls within the same process
        don't hit the Paperless API again.
        """
        tag_name = f"tenant:{tenant_id}"
        if tag_name in self._tenant_tag_cache:
            return self._tenant_tag_cache[tag_name]
        tag_id = await self.find_or_create_tag(tag_name, color='#607D8B')
        if tag_id is not None:
            self._tenant_tag_cache[tag_name] = tag_id
        return tag_id

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

    async def get_thumbnail_bytes(self, doc_id: str) -> bytes:
        """Download the thumbnail image for a Paperless document."""
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f'{self.base_url}/api/documents/{doc_id}/thumb/',
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.content

    async def get_document(self, doc_id: str, tenant_id: str | None = None) -> dict | None:
        """Fetch a single document. If *tenant_id* is given, verify that the
        document carries the expected ``tenant:<tenant_id>`` tag.  Returns
        ``None`` when the tenant check fails (the caller decides whether to
        raise 403 or similar)."""
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f'{self.base_url}/api/documents/{doc_id}/', headers=self._headers())
            response.raise_for_status()
            doc = response.json()

        if tenant_id:
            tag_id = await self._ensure_tenant_tag(tenant_id)
            if tag_id is None or tag_id not in doc.get('tags', []):
                logger.warning(
                    'Tenant isolation: doc %s does not belong to tenant %s',
                    doc_id,
                    tenant_id,
                )
                return None
        return doc

    async def search_documents(self, query: str, tenant_id: str | None = None) -> list[dict]:
        params: dict[str, str | int] = {'query': query}
        if tenant_id:
            tag_id = await self._ensure_tenant_tag(tenant_id)
            if tag_id is not None:
                params['tags__id__in'] = tag_id
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f'{self.base_url}/api/documents/',
                params=params,
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
        self,
        file_bytes: bytes,
        filename: str,
        title: str | None = None,
        tenant_id: str | None = None,
    ) -> dict:
        """Upload a document to Paperless via POST /api/documents/post_document/.

        If *tenant_id* is provided the Paperless tag ``tenant:<tenant_id>``
        will be resolved (or created) **before** the upload and passed along
        so Paperless assigns it immediately.

        Returns: {'task_id': 'uuid-string'}
        Raises: httpx.HTTPStatusError on HTTP 4xx/5xx, httpx.TimeoutException on timeout.
        """
        files = {'document': (filename, file_bytes, 'application/octet-stream')}
        data: dict[str, str] = {}
        if title:
            data['title'] = title

        # Resolve tenant tag *before* upload so we can include it in the
        # POST request — Paperless accepts ``tags`` as form field.
        tag_id: int | None = None
        if tenant_id:
            tag_id = await self._ensure_tenant_tag(tenant_id)
            if tag_id is not None:
                data['tags'] = str(tag_id)

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

    async def list_all_documents(
        self, page_size: int = 100, tenant_id: str | None = None
    ) -> list[dict]:
        """Fetch all documents from Paperless (paginated).

        When *tenant_id* is given only documents tagged with
        ``tenant:<tenant_id>`` are returned.
        """
        results: list[dict] = []
        url = f'{self.base_url}/api/documents/'
        params: dict[str, int] = {'page_size': page_size}
        if tenant_id:
            tag_id = await self._ensure_tenant_tag(tenant_id)
            if tag_id is not None:
                params['tags__id__in'] = tag_id
        async with httpx.AsyncClient(timeout=30.0) as client:
            while url:
                resp = await client.get(url, headers=self._headers(), params=params)
                resp.raise_for_status()
                payload = resp.json()
                results.extend(payload.get('results', []))
                next_url = payload.get('next')
                if next_url:
                    # Paperless generates next-page URLs using its public PAPERLESS_URL
                    # (e.g. https://paperless.staging.myfrya.de), but we must stay on
                    # the internal base_url (e.g. http://frya-paperless:8000) to avoid
                    # unnecessary external round-trips and to not depend on public
                    # reachability during pagination.
                    parsed = urlparse(next_url)
                    base = urlparse(self.base_url)
                    next_url = urlunparse(parsed._replace(scheme=base.scheme, netloc=base.netloc))
                url = next_url
                params = {}  # next URL already includes query params
        return results

    async def get_custom_field_ids(self) -> dict[str, int]:
        """Return cached mapping of custom field name → ID."""
        if self._custom_field_cache:
            return dict(self._custom_field_cache)
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    f'{self.base_url}/api/custom_fields/',
                    headers=self._headers(),
                )
                resp.raise_for_status()
                fields = resp.json().get('results', [])
                self._custom_field_cache = {f['name']: f['id'] for f in fields}
                return dict(self._custom_field_cache)
        except Exception:
            return {}

    def invalidate_custom_field_cache(self) -> None:
        """Clear the custom field cache (e.g. after creating new fields)."""
        self._custom_field_cache = {}
