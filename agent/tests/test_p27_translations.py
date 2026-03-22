"""P-27 F.1 tests: UI translations."""


def test_translations_load():
    from app.utils.translations import t
    assert t('confidence', 'CERTAIN') == 'Sicher'
    assert t('confidence', 'HIGH') == 'Hoch'
    assert t('confidence', 'MEDIUM') == 'Mittel'


def test_translations_fallback():
    from app.utils.translations import t
    assert t('confidence', 'NONEXISTENT') == 'NONEXISTENT'
    assert t('confidence', 'NONEXISTENT', 'Fallback') == 'Fallback'


def test_translations_status():
    from app.utils.translations import t_status
    assert t_status('OPEN') == 'Offen'
    assert t_status('PENDING_APPROVAL') == 'Wartet auf Freigabe'
    assert t_status('DRAFT') == 'Entwurf'


def test_translations_doc_type():
    from app.utils.translations import t_doc_type
    assert t_doc_type('INVOICE') == 'Rechnung'
    assert t_doc_type('REMINDER') == 'Mahnung'


def test_translations_risk():
    from app.utils.translations import t_risk
    assert t_risk('duplicate_detection') == 'Moegliches Duplikat'


def test_translations_agent():
    from app.utils.translations import t_agent
    assert t_agent('communicator') == 'Kommunikator (Mund)'
    assert t_agent('document_analyst') == 'Document Analyst (Auge)'
