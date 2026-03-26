"""Chart template configuration loader."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_CHARTS_PATH = Path(__file__).resolve().parent.parent.parent / 'data' / 'config' / 'chart_templates.yaml'


@lru_cache(maxsize=1)
def load_chart_config() -> dict:
    with open(_CHARTS_PATH, encoding='utf-8') as f:
        return yaml.safe_load(f)


def get_category_color(category: str) -> str:
    config = load_chart_config()
    colors = config.get('category_colors', {})
    return colors.get(category.lower(), colors.get('sonstiges', '#6b7280'))


def get_confidence_color(level: str) -> str:
    config = load_chart_config()
    colors = config.get('confidence_colors', {})
    return colors.get(level, '#6b7280')


def get_chart_type(chart_name: str) -> dict:
    config = load_chart_config()
    return config.get('chart_types', {}).get(chart_name, {})
