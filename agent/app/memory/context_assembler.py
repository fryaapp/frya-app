from __future__ import annotations

from datetime import date, timedelta

from app.memory.file_store import FileStore


class ContextAssembler:
    CORE_FILES = ['agent.md', 'user.md', 'soul.md', 'memory.md', 'dms-state.md']

    def __init__(self, file_store: FileStore) -> None:
        self.file_store = file_store

    def _daily_log_path(self, day: date) -> str:
        return f'memory/{day.isoformat()}.md'

    def assemble(self) -> dict[str, str]:
        today = date.today()
        yesterday = today - timedelta(days=1)

        assembled: dict[str, str] = {}
        for file_name in self.CORE_FILES:
            assembled[file_name] = self.file_store.read_text(file_name)

        assembled[self._daily_log_path(today)] = self.file_store.read_text(self._daily_log_path(today))
        assembled[self._daily_log_path(yesterday)] = self.file_store.read_text(self._daily_log_path(yesterday))

        return assembled

    def assemble_with_explicit_logs(self, extra_daily_logs: list[str] | None = None) -> dict[str, str]:
        context = self.assemble()
        for path in extra_daily_logs or []:
            context[path] = self.file_store.read_text(path)
        return context
