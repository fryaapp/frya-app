from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.rules.loader import RuleLoader


class RuleRegistry:
    def __init__(self, loader: RuleLoader) -> None:
        self.loader = loader
        self._cache: dict[str, Any] = {}

    def refresh(self) -> dict[str, Any]:
        self._cache = self.loader.load_all()
        return self._cache

    def get(self, file_name: str) -> Any:
        if file_name not in self._cache:
            self._cache[file_name] = self.loader.load_rule_file(file_name)
        return self._cache[file_name]

    def update(self, file_name: str, payload: Any, on_change: Callable[[str, Any], None] | None = None) -> None:
        self.loader.save_rule_file(file_name, payload)
        self._cache[file_name] = payload
        if on_change is not None:
            on_change(file_name, payload)
