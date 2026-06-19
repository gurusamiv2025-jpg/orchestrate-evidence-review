"""Content-addressed disk cache for model responses.

Key = sha256(model + system + serialized messages + tool schema). Because the
pipeline is deterministic (temperature 0), an identical request always maps to
the same key, so re-runs, eval iterations, and crash-resumes never re-pay for a
call we have already made. This is central to the cost / rate-limit story.
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path


class DiskCache:
    def __init__(self, cache_dir: Path):
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def make_key(payload: dict) -> str:
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self.dir / f"{key}.json"

    def get(self, key: str):
        p = self._path(key)
        if p.exists():
            with self._lock:
                self.hits += 1
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return None
        with self._lock:
            self.misses += 1
        return None

    def set(self, key: str, value: dict) -> None:
        tmp = self._path(key + ".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path(key))
