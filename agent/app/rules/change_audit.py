from __future__ import annotations

import hashlib
import json
from datetime import datetime


def build_rule_change_event(file_name: str, payload: dict, changed_by: str) -> dict:
    content = json.dumps(payload, sort_keys=True)
    return {
        'event_type': 'RULE_CHANGE',
        'file_name': file_name,
        'changed_by': changed_by,
        'changed_at': datetime.utcnow().isoformat(),
        'payload_hash': hashlib.sha256(content.encode('utf-8')).hexdigest(),
    }
