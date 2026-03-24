"""ContactService — manages vendor/customer contacts from document analysis."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from app.accounting.models import Contact
from app.accounting.repository import AccountingRepository

logger = logging.getLogger(__name__)


class ContactService:
    def __init__(self, repo: AccountingRepository) -> None:
        self._repo = repo

    async def find_or_create_from_analysis(
        self, tenant_id: uuid.UUID, analysis_data: dict,
    ) -> Contact:
        """Create or find a contact from semantic analysis data."""
        name = analysis_data.get('sender') or analysis_data.get('vendor_name') or 'Unbekannt'
        contact = await self._repo.find_or_create_contact(
            tenant_id, name,
            contact_type='VENDOR',
        )

        # Enrich with analysis data if available
        # (future: update IBAN, tax_id etc. from analysis)
        return contact

    async def list_all(self, tenant_id: uuid.UUID) -> list[Contact]:
        return await self._repo.list_contacts(tenant_id)
