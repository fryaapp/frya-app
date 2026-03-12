from __future__ import annotations

from pathlib import Path


class FileStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def resolve(self, relative_path: str) -> Path:
        return self.data_dir / relative_path

    def read_text(self, relative_path: str) -> str:
        path = self.resolve(relative_path)
        if not path.exists():
            return ''
        return path.read_text(encoding='utf-8')

    def write_text(self, relative_path: str, content: str) -> None:
        path = self.resolve(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

    def list_files(self, relative_dir: str) -> list[str]:
        base = self.resolve(relative_dir)
        if not base.exists():
            return []
        return sorted(str(p.relative_to(self.data_dir)) for p in base.glob('**/*') if p.is_file())
