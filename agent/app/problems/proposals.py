from __future__ import annotations

from datetime import date

from app.memory.file_store import FileStore


class ProposalEngine:
    def __init__(self, file_store: FileStore) -> None:
        self.file_store = file_store

    def generate_daily_scaffold(self, summary: str) -> str:
        today = date.today().isoformat()
        path = f'system/proposals/{today}.md'
        content = (
            '# Verbesserungsvorschlaege\n\n'
            'Hinweis: Vorschlaege sind unverbindlich und aendern keine Regeln automatisch.\n\n'
            f'## Tageszusammenfassung\n{summary}\n\n'
            '## Vorschlaege\n- [ ] Regelpraezisierung\n- [ ] Deterministischen Workflow in n8n ergaenzen\n- [ ] Ausnahmefall dokumentieren\n'
        )
        self.file_store.write_text(path, content)
        return path
