"""UI-Uebersetzungsverzeichnis Deutsch."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_TRANSLATIONS_PATH = Path(__file__).resolve().parent.parent.parent / 'data' / 'config' / 'ui_translations.yaml'


@lru_cache(maxsize=1)
def _load_translations() -> dict:
    with open(_TRANSLATIONS_PATH, encoding='utf-8') as f:
        return yaml.safe_load(f)


def t(category: str, key: str, fallback: str | None = None) -> str:
    """Translate an internal key to a German UI label.

    Example: t('confidence', 'CERTAIN') -> 'Sicher'
    """
    translations = _load_translations()
    cat = translations.get(category, {})
    return cat.get(key, cat.get(str(key), fallback or key))


def t_confidence(level: str) -> str:
    return t('confidence', level)


def t_status(status: str) -> str:
    return t('case_status', status, t('item_status', status, status))


def t_doc_type(doc_type: str) -> str:
    return t('document_type', doc_type)


def t_risk(flag: str) -> str:
    return t('risk_flags', flag)


def t_agent(agent_id: str) -> str:
    return t('agents', agent_id)
