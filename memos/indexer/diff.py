import hashlib
from pathlib import Path

from memos.core.models import File


def compute_file_hash(path: str) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        h.update(f.read())
    return h.hexdigest()


def should_reindex(
    existing: File | None,
    current_hash: str,
    *,
    full: bool = False,
) -> bool:
    if full:
        return True
    if existing is None:
        return True
    return existing.content_hash != current_hash
