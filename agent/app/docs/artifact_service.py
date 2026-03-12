from __future__ import annotations

from app.memory.file_store import FileStore


class ArtifactService:
    def __init__(self, file_store: FileStore) -> None:
        self.file_store = file_store

    def list_artifacts(self) -> list[str]:
        return self.file_store.list_files('verfahrensdoku')

    def read_artifact(self, relative_path: str) -> str:
        return self.file_store.read_text(relative_path)
