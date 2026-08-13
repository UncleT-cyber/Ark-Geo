"""State cache – persists each user's last verified outdoor GPS stream.

In production this would sit on top of Redis or Postgres; for local/dev it
uses an in-memory dict keyed by ``user_id``.  The interface is identical so
swapping the backend later requires no pipeline changes.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from app.models import Coordinates, GpsFix


class StateCache:
    """Thread-safe in-memory store for last-known outdoor GPS per user."""

    def __init__(self) -> None:
        self._store: dict[str, GpsFix] = {}
        self._lock = threading.Lock()

    def set_outdoor_gps(self, user_id: str, fix: GpsFix) -> None:
        with self._lock:
            self._store[user_id] = fix

    def get_outdoor_gps(self, user_id: str, max_age_seconds: int = 7200) -> Optional[Coordinates]:
        with self._lock:
            fix = self._store.get(user_id)
        if not fix:
            return None
        ts = fix.timestamp or 0
        if ts and (time.time() - ts) > max_age_seconds:
            return None
        return Coordinates(lat=fix.lat, lon=fix.lon)

    def clear(self, user_id: str) -> None:
        with self._lock:
            self._store.pop(user_id, None)


# Module-level singleton
state_cache = StateCache()
