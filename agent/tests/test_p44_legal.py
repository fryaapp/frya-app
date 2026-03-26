"""Tests for P-44: Legal Placeholders + AVV Archive."""
import pytest
import tempfile
from pathlib import Path


def test_legal_placeholders_config():
    from app.ui.router import LEGAL_PLACEHOLDERS
    assert 'company_name' in LEGAL_PLACEHOLDERS
    assert 'ust_id' in LEGAL_PLACEHOLDERS
    assert len(LEGAL_PLACEHOLDERS) >= 15


@pytest.mark.asyncio
async def test_avv_repository_upload_and_list():
    from app.legal.avv_repository import AvvRepository
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = AvvRepository('memory://', Path(tmpdir))
        doc = await repo.upload(
            tenant_id='test-tenant', provider_name='IONOS SE',
            document_type='AVV', filename='ionos_avv.pdf',
            file_bytes=b'%PDF-test', uploaded_by='admin', notes='Test',
        )
        assert doc.provider_name == 'IONOS SE'
        assert doc.version == 1
        assert doc.is_current is True

        docs = await repo.list_all('test-tenant')
        assert len(docs) == 1


@pytest.mark.asyncio
async def test_avv_versioning():
    from app.legal.avv_repository import AvvRepository
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = AvvRepository('memory://', Path(tmpdir))
        v1 = await repo.upload(
            tenant_id='t', provider_name='Hetzner',
            document_type='AVV', filename='v1.pdf',
            file_bytes=b'v1', uploaded_by='admin',
        )
        v2 = await repo.upload(
            tenant_id='t', provider_name='Hetzner',
            document_type='AVV', filename='v2.pdf',
            file_bytes=b'v2', uploaded_by='admin',
        )
        assert v1.version == 1
        assert v2.version == 2
        assert v2.is_current is True

        docs = await repo.list_all('t')
        current = [d for d in docs if d.is_current]
        assert len(current) == 1
        assert current[0].version == 2
