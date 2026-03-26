"""One-shot backfill: update Paperless documents with CaseEngine metadata."""
import asyncio
import sys

sys.path.insert(0, '/app')


DOCUMENT_TYPE_MAP = {
    'INVOICE': 'Eingangsrechnung', 'REMINDER': 'Mahnung',
    'CONTRACT': 'Vertrag', 'NOTICE': 'Bescheid',
    'TAX_DOCUMENT': 'Steuerdokument', 'RECEIPT': 'Quittung',
    'BANK_STATEMENT': 'Kontoauszug', 'PAYSLIP': 'Lohnabrechnung',
    'INSURANCE': 'Versicherung', 'OFFER': 'Angebot',
    'CREDIT_NOTE': 'Gutschrift', 'DELIVERY_NOTE': 'Lieferschein',
    'LETTER': 'Brief', 'PRIVATE': 'Privat', 'AGB': 'AGB',
    'WIDERRUF': 'Sonstiges', 'OTHER': 'Sonstiges',
}


async def run():
    from app.dependencies import get_paperless_connector, get_case_repository

    paperless = get_paperless_connector()
    case_repo = get_case_repository()
    await case_repo.initialize()

    paperless.invalidate_custom_field_cache()
    documents = await paperless.list_all_documents()
    field_ids = await paperless.get_custom_field_ids()

    print(f'Documents: {len(documents)}')
    print(f'Custom field IDs: {field_ids}')

    updated = 0
    skipped = 0
    errors = 0

    import asyncpg

    for doc in documents:
        doc_id = doc.get('id')
        if doc_id is None:
            continue

        try:
            # Find case for this doc
            conn = await asyncpg.connect(case_repo.database_url)
            try:
                row = await conn.fetchrow(
                    "SELECT * FROM case_documents WHERE document_source='paperless' AND document_source_id=$1 LIMIT 1",
                    str(doc_id),
                )
            finally:
                await conn.close()

            if row is None:
                skipped += 1
                continue

            case_id = row['case_id']
            conn2 = await asyncpg.connect(case_repo.database_url)
            try:
                case_row = await conn2.fetchrow('SELECT * FROM case_cases WHERE id=$1', case_id)
            finally:
                await conn2.close()

            if case_row is None:
                skipped += 1
                continue

            patch_data = {}

            vendor = case_row.get('vendor_name')
            if vendor:
                corr_id = await paperless.find_or_create_correspondent(vendor)
                if corr_id is not None:
                    patch_data['correspondent'] = corr_id

            doc_type_val = row.get('document_type')
            if doc_type_val:
                dt_name = DOCUMENT_TYPE_MAP.get(doc_type_val, 'Sonstiges')
                dt_id = await paperless.find_or_create_document_type(dt_name)
                if dt_id is not None:
                    patch_data['document_type'] = dt_id

            # Tags (merge with existing)
            existing_doc = await paperless.get_document(str(doc_id))
            tag_ids = list(existing_doc.get('tags', []))
            a_id = await paperless.find_or_create_tag('frya:analysiert', '#2196F3')
            if a_id and a_id not in tag_ids:
                tag_ids.append(a_id)
            if doc_type_val == 'INVOICE':
                v_id = await paperless.find_or_create_tag('vorsteuer-relevant', '#673AB7')
                if v_id and v_id not in tag_ids:
                    tag_ids.append(v_id)
            status_val = case_row.get('status', '')
            if status_val == 'BOOKED':
                b_id = await paperless.find_or_create_tag('frya:gebucht', '#4CAF50')
                if b_id and b_id not in tag_ids:
                    tag_ids.append(b_id)
            if tag_ids:
                patch_data['tags'] = tag_ids

            # Title: "Vendor — Betrag — Datum"
            parts = []
            if vendor:
                parts.append(vendor)
            total = case_row.get('total_amount')
            if total is not None:
                currency = case_row.get('currency') or 'EUR'
                parts.append(f'{float(total):.2f}{currency}')
            due = case_row.get('due_date')
            if due:
                parts.append(due.strftime('%b %Y'))
            if parts:
                patch_data['title'] = ' \u2014 '.join(parts)

            # Custom Fields
            cfs = []
            if 'frya_case_id' in field_ids:
                cfs.append({'field': field_ids['frya_case_id'], 'value': str(case_id)})
            if 'frya_status' in field_ids:
                cfs.append({'field': field_ids['frya_status'], 'value': status_val.lower()})
            if total is not None and 'betrag_brutto' in field_ids:
                cfs.append({'field': field_ids['betrag_brutto'], 'value': str(total)})
            if cfs:
                patch_data['custom_fields'] = cfs

            if patch_data:
                ok = await paperless.update_document_metadata(doc_id, patch_data)
                if ok:
                    updated += 1
                    print(f'  Updated doc {doc_id}: {list(patch_data.keys())}')
                else:
                    errors += 1
                    print(f'  Error doc {doc_id}')
            else:
                skipped += 1

        except Exception as exc:
            errors += 1
            print(f'  Error doc {doc_id}: {exc}')

    print(f'\nDone: updated={updated}, skipped={skipped}, errors={errors}')


if __name__ == '__main__':
    asyncio.run(run())
