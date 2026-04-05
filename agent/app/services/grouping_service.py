"""Group related cases for accordion display in inbox."""
from __future__ import annotations
import logging
from collections import defaultdict

_logger = logging.getLogger(__name__)


def group_inbox_items(items: list[dict], references: list[dict]) -> dict:
    """Group inbox items by reference relationships.

    Args:
        items: List of inbox case dicts (with vendor, document_type, amount, confidence, case_id etc.)
        references: List of case_references rows (case_id, reference_type, reference_value)

    Returns:
        dict with 'groups' and 'ungrouped_items'
    """
    # Build reference_value -> list of case_ids mapping
    ref_to_cases: dict[str, list[str]] = defaultdict(list)
    case_to_refs: dict[str, list[str]] = defaultdict(list)

    for ref in references:
        case_id = str(ref.get('case_id', ''))
        ref_value = ref.get('reference_value', '')
        if case_id and ref_value:
            ref_to_cases[ref_value].append(case_id)
            case_to_refs[case_id].append(ref_value)

    # Build item lookup by case_id
    item_by_case = {}
    for item in items:
        cid = str(item.get('case_id', ''))
        if cid:
            item_by_case[cid] = item

    # Strategy 1: Group by shared reference_value (invoice number, contract number)
    # Strategy 2: Group by same vendor_name + same document_type

    used_case_ids: set[str] = set()
    groups: list[dict] = []

    # --- Strategy 1: Shared references ---
    for ref_value, case_ids in ref_to_cases.items():
        unique_ids = list(set(cid for cid in case_ids if cid in item_by_case and cid not in used_case_ids))
        if len(unique_ids) >= 2:
            group_items = [item_by_case[cid] for cid in unique_ids]
            vendor = _most_common([i.get('vendor', '') for i in group_items])
            groups.append(_build_group(
                name=vendor or 'Verknuepfte Belege',
                reference=ref_value,
                group_type='same_reference',
                items=group_items,
            ))
            used_case_ids.update(unique_ids)

    # --- Strategy 2: Same vendor + recurring pattern ---
    vendor_groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        cid = str(item.get('case_id', ''))
        if cid in used_case_ids:
            continue
        vendor = (item.get('vendor') or '').strip()
        if vendor and vendor not in ('Unbekannter Absender', '?', '', 'None'):
            vendor_groups[vendor].append(item)

    for vendor, vitems in vendor_groups.items():
        if len(vitems) >= 2:
            groups.append(_build_group(
                name=vendor,
                reference=None,
                group_type='same_vendor',
                items=vitems,
            ))
            for vi in vitems:
                used_case_ids.add(str(vi.get('case_id', '')))

    # --- Ungrouped ---
    ungrouped = [item for item in items if str(item.get('case_id', '')) not in used_case_ids]

    _logger.info('Grouped %d items into %d groups + %d ungrouped', len(items), len(groups), len(ungrouped))
    return {'groups': groups, 'ungrouped_items': ungrouped}


def _build_group(name: str, reference: str | None, group_type: str, items: list[dict]) -> dict:
    total = sum(float(i.get('amount') or 0) for i in items)

    # Determine highest priority badge
    badge_priority = {'Niedrig': 0, 'Mittel': 1, 'Hoch': 2, 'Sicher': 3}
    highest_badge = None
    min_priority = 999
    for item in items:
        badge = item.get('confidence_label')
        if not badge:
            badge_data = item.get('badge')
            if isinstance(badge_data, dict):
                badge = badge_data.get('label', 'Niedrig')
            else:
                badge = 'Niedrig'
        p = badge_priority.get(badge, 0)
        if p < min_priority:
            min_priority = p
            highest_badge = badge

    # Check for dunning chain (Mahnung in items)
    has_dunning = any(
        'mahnung' in (i.get('document_type') or '').lower()
        or 'mahnung' in (i.get('subtitle') or '').lower()
        for i in items
    )
    if has_dunning:
        group_type = 'dunning_chain'

    return {
        'name': name,
        'reference': reference,
        'group_type': group_type,
        'total_amount': total,
        'count': len(items),
        'highest_badge': highest_badge,
        'warning': 'Offene Forderung' if has_dunning else None,
        'items': items,
    }


def _most_common(values: list[str]) -> str:
    if not values:
        return ''
    counts: dict[str, int] = {}
    for v in values:
        if v:
            counts[v] = counts.get(v, 0) + 1
    if not counts:
        return ''
    return max(counts, key=counts.get)
