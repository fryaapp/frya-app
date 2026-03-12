from __future__ import annotations

import hashlib
import json


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def record_hash(payload: dict, previous_hash: str | None) -> str:
    normalized = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return sha256_text((previous_hash or '') + normalized)
