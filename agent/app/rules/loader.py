from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


class RuleLoader:
    def __init__(self, rules_dir: Path) -> None:
        self.rules_dir = rules_dir

    @property
    def registry_file(self) -> Path:
        return self.rules_dir / 'rule_registry.yaml'

    def _resolve_target(self, relative_path: str) -> Path:
        target = (self.rules_dir / relative_path).resolve()
        rules_root = self.rules_dir.resolve()
        if rules_root not in target.parents and target != rules_root:
            raise ValueError('Ungueltiger Regelpfad')
        return target

    def _read_registry(self) -> list[dict[str, Any]]:
        if not self.registry_file.exists():
            return []
        raw = yaml.safe_load(self.registry_file.read_text(encoding='utf-8')) or {}
        entries = raw.get('entries', [])
        return entries if isinstance(entries, list) else []

    def _infer_files(self) -> list[str]:
        if not self.rules_dir.exists():
            return []
        files: list[str] = []
        for pattern in ('*.yaml', '*.yml', '*.md'):
            files.extend(str(p.relative_to(self.rules_dir)).replace('\\', '/') for p in self.rules_dir.rglob(pattern))
        return sorted(set(files))

    def _detect_format(self, file_name: str) -> str:
        lower = file_name.lower()
        if lower.endswith('.md'):
            return 'markdown'
        if lower.endswith('.yaml') or lower.endswith('.yml'):
            return 'yaml'
        return 'text'

    def _extract_version(self, raw_content: str, parsed_payload: Any, fmt: str) -> str | None:
        if fmt == 'yaml' and isinstance(parsed_payload, dict):
            version = parsed_payload.get('version')
            return str(version) if version is not None else None

        if fmt == 'markdown':
            for line in raw_content.splitlines()[:30]:
                m = re.match(r'^\s*Version\s*:\s*(.+?)\s*$', line, flags=re.IGNORECASE)
                if m:
                    return m.group(1)
        return None

    def list_rule_entries(self) -> list[dict[str, Any]]:
        registry_entries = self._read_registry()
        if not registry_entries:
            return [
                {'file': f, 'role': 'unregistered', 'required': False}
                for f in self._infer_files()
                if f != 'rule_registry.yaml'
            ]
        return registry_entries

    def list_rule_files(self) -> list[str]:
        return [entry['file'] for entry in self.list_rule_entries() if isinstance(entry, dict) and entry.get('file')]

    def load_rule_file(self, file_name: str) -> Any:
        target = self._resolve_target(file_name)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(file_name)

        raw = target.read_text(encoding='utf-8')
        fmt = self._detect_format(file_name)
        if fmt == 'yaml':
            return yaml.safe_load(raw) or {}
        return raw

    def load_rule_text(self, file_name: str) -> str:
        target = self._resolve_target(file_name)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(file_name)
        return target.read_text(encoding='utf-8')

    def load_rule_document(self, file_name: str, role: str | None = None, required: bool | None = None) -> dict[str, Any]:
        fmt = self._detect_format(file_name)
        try:
            parsed = self.load_rule_file(file_name)
            raw = self.load_rule_text(file_name)
            version = self._extract_version(raw, parsed, fmt)
            return {
                'file': file_name,
                'role': role,
                'required': bool(required),
                'format': fmt,
                'loaded': True,
                'error': None,
                'version': version,
                'content': raw,
                'parsed': parsed if fmt == 'yaml' else None,
            }
        except Exception as exc:
            return {
                'file': file_name,
                'role': role,
                'required': bool(required),
                'format': fmt,
                'loaded': False,
                'error': str(exc),
                'version': None,
                'content': None,
                'parsed': None,
            }

    def load_status(self) -> list[dict[str, Any]]:
        docs: list[dict[str, Any]] = []
        for entry in self.list_rule_entries():
            file_name = str(entry.get('file'))
            if not file_name:
                continue
            docs.append(
                self.load_rule_document(
                    file_name=file_name,
                    role=str(entry.get('role', 'unregistered')),
                    required=bool(entry.get('required', False)),
                )
            )
        return docs

    def load_all(self) -> dict[str, Any]:
        loaded: dict[str, Any] = {}
        for item in self.load_status():
            if item['loaded']:
                loaded[item['file']] = item['parsed'] if item['format'] == 'yaml' else item['content']
        return loaded

    def save_rule_file(self, file_name: str, payload: Any) -> None:
        target = self._resolve_target(file_name)
        target.parent.mkdir(parents=True, exist_ok=True)

        fmt = self._detect_format(file_name)
        if isinstance(payload, str):
            target.write_text(payload, encoding='utf-8')
            return

        if fmt == 'yaml':
            target.write_text(yaml.safe_dump(payload or {}, sort_keys=False), encoding='utf-8')
            return

        target.write_text(str(payload), encoding='utf-8')
