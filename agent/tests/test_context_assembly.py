from datetime import date, timedelta

from app.memory.context_assembler import ContextAssembler
from app.memory.file_store import FileStore


def test_context_assembly_loads_core_and_today_yesterday(tmp_path):
    store = FileStore(tmp_path)
    store.write_text('agent.md', 'agent')
    store.write_text('user.md', 'user')
    store.write_text('soul.md', 'soul')
    store.write_text('memory.md', 'memory')
    store.write_text('dms-state.md', 'state')

    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    older = (date.today() - timedelta(days=10)).isoformat()

    store.write_text(f'memory/{today}.md', 'today-log')
    store.write_text(f'memory/{yesterday}.md', 'yesterday-log')
    store.write_text(f'memory/{older}.md', 'older-log')

    assembler = ContextAssembler(store)
    context = assembler.assemble()

    assert context['agent.md'] == 'agent'
    assert context[f'memory/{today}.md'] == 'today-log'
    assert context[f'memory/{yesterday}.md'] == 'yesterday-log'
    assert f'memory/{older}.md' not in context


def test_context_assembly_with_explicit_older_logs(tmp_path):
    store = FileStore(tmp_path)
    store.write_text('agent.md', 'x')
    store.write_text('user.md', 'x')
    store.write_text('soul.md', 'x')
    store.write_text('memory.md', 'x')
    store.write_text('dms-state.md', 'x')
    store.write_text('memory/2000-01-01.md', 'old')

    assembler = ContextAssembler(store)
    context = assembler.assemble_with_explicit_logs(['memory/2000-01-01.md'])

    assert context['memory/2000-01-01.md'] == 'old'
