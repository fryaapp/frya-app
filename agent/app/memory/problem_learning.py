from __future__ import annotations

from app.memory.file_store import FileStore


class ProblemLearningService:
    def __init__(self, file_store: FileStore) -> None:
        self.file_store = file_store

    def append_learning(self, line: str) -> None:
        existing = self.file_store.read_text('memory/problem-learning.md')
        updated = (existing.rstrip() + '\n' + line + '\n').lstrip()
        self.file_store.write_text('memory/problem-learning.md', updated)

    def read(self) -> str:
        return self.file_store.read_text('memory/problem-learning.md')
