from __future__ import annotations

from urllib.parse import quote


def encode_case_id(case_id: str) -> str:
    return quote(case_id, safe='')


def ui_case_href(case_id: str) -> str:
    return f'/ui/cases/{encode_case_id(case_id)}'


def inspect_case_href(case_id: str) -> str:
    return f'/inspect/cases/{encode_case_id(case_id)}'


def inspect_case_json_href(case_id: str) -> str:
    return f'{inspect_case_href(case_id)}/json'
