"""P-29 tests: Document workflows, chart templates, vendor alias, dunning, model hot-swap."""


# ── TEIL 0: Model Hot-Swap (already works) ───────────────────────────────────

def test_model_swap_cache_delete_exists():
    """upsert_config calls _cache_delete after save."""
    import inspect
    from app.llm_config import LLMConfigRepository
    source = inspect.getsource(LLMConfigRepository.upsert_config)
    assert '_cache_delete' in source


# ── TEIL 4: Document Workflows ───────────────────────────────────────────────

def test_load_workflows():
    from app.utils.document_workflows import load_workflows
    workflows = load_workflows()
    assert 'eingangsrechnung' in workflows
    assert 'sonstiges' in workflows
    assert len(workflows) >= 10


def test_get_field_priority():
    from app.utils.document_workflows import get_field_priority
    assert get_field_priority('eingangsrechnung', 'gross_amount') == 'high'
    assert get_field_priority('eingangsrechnung', 'iban') == 'normal'
    assert get_field_priority('eingangsrechnung', 'line_items') == 'low'
    assert get_field_priority('eingangsrechnung', 'unknown_field') == 'normal'


def test_get_workflow_fallback():
    from app.utils.document_workflows import get_workflow
    fallback = get_workflow('unbekannter_typ')
    sonstiges = get_workflow('sonstiges')
    assert fallback == sonstiges


# ── TEIL 6: Chart Templates ──────────────────────────────────────────────────

def test_category_color():
    from app.utils.chart_templates import get_category_color
    assert get_category_color('telekommunikation') == '#3b82f6'
    assert get_category_color('unbekannt') == '#6b7280'


def test_confidence_color():
    from app.utils.chart_templates import get_confidence_color
    assert get_confidence_color('CERTAIN') == '#16a34a'
    assert get_confidence_color('LOW') == '#dc2626'


def test_chart_type():
    from app.utils.chart_templates import get_chart_type
    chart = get_chart_type('monthly_expense')
    assert chart['type'] == 'bar'


# ── TEIL 3: Vendor Alias ─────────────────────────────────────────────────────

def test_vendor_alias_repo_exists():
    from app.vendors.alias_repository import VendorAliasRepository
    repo = VendorAliasRepository('memory://')
    assert hasattr(repo, 'resolve')
    assert hasattr(repo, 'add_alias')
    assert hasattr(repo, 'get_all')


# ── TEIL 5: Dunning ──────────────────────────────────────────────────────────

def test_dunning_text():
    from app.dunning.service import DunningService
    svc = DunningService('memory://')
    text = svc.get_dunning_text(1, vendor='1&1', amount='8.54', days=10)
    assert '1&1' in text
    assert '8.54' in text
    assert '10' in text


def test_dunning_text_level4():
    from app.dunning.service import DunningService
    svc = DunningService('memory://')
    text = svc.get_dunning_text(4, vendor='Test', amount='100', ref='RE-001', days=50)
    assert 'Inkasso' in text or 'Letzte' in text
