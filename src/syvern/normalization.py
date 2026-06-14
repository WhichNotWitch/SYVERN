from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def normalize_ws(text: str) -> str:
    return " ".join(text.split())


def sha256_text(text: str) -> str:
    return hashlib.sha256(normalize_ws(text).encode("utf-8")).hexdigest()


def token_count(text: str) -> int:
    normalized = normalize_ws(text)
    if not normalized:
        return 0
    return len(re.findall(r"\S+", normalized))


def reference_identity(reference: Any | None) -> str:
    if reference is None:
        return "none"
    encoded = json.dumps(reference, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
