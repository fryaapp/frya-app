from __future__ import annotations

from datetime import date

from app.memory.file_store import FileStore


class DailyLogService:
    def __init__(self, file_store: FileStore) -> None:
        self.file_store = file_store

    def append(self, message: str, day: date | None = None) -> str:
        target_day = day or date.today()
        relative_path = f'memory/{target_day.isoformat()}.md'
        existing = self.file_store.read_text(relative_path)
        updated = (existing.rstrip() + '\n' + message + '\n').lstrip()
        self.file_store.write_text(relative_path, updated)
        return relative_path
