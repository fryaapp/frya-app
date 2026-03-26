"""Document workflow configuration loader."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_WORKFLOWS_PATH = Path(__file__).resolve().parent.parent.parent / 'data' / 'rules' / 'document_workflows.yaml'


@lru_cache(maxsize=1)
def load_workflows() -> dict:
    with open(_WORKFLOWS_PATH, encoding='utf-8') as f:
        return yaml.safe_load(f)


def get_workflow(doc_type: str) -> dict:
    workflows = load_workflows()
    return workflows.get(doc_type.lower(), workflows.get('sonstiges', {}))


def get_field_priority(doc_type: str, field_name: str) -> str:
    workflow = get_workflow(doc_type)
    priorities = workflow.get('field_priority', {})
    return priorities.get(field_name, 'normal')
