import hashlib
from typing import Optional

from memos.core.models import File


def compute_file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def should_reindex(existing: Optional[File], current_hash: str, full: bool) -> bool:
    if full:
        return True
    if existing is None:
        return True
    return existing.content_hash != current_hash
