"""A small in-process TTL cache.

Serverless platforms such as Vercel keep a warm instance alive for a few
minutes, so caching Hub responses in memory removes most repeat round-trips
(for example when a user downloads the JSON and then the PDF for the same
model). The cache is deliberately simple: it is per-process, bounded, and
never shared between instances. Nothing is written to disk.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any


class TTLCache:
    """Bounded mapping whose entries expire ``ttl_seconds`` after they were stored.

    A ``ttl_seconds`` of ``0`` (or a ``max_entries`` of ``0``) turns the cache
    into a no-op, which is useful in tests and when operators want fresh data.
    """

    def __init__(
        self,
        ttl_seconds: float,
        max_entries: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = float(ttl_seconds)
        self.max_entries = int(max_entries)
        self._clock = clock
        self._items: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()

    @property
    def enabled(self) -> bool:
        return self.ttl_seconds > 0 and self.max_entries > 0

    def get(self, key: Hashable) -> Any | None:
        """Return the cached value for ``key`` or ``None`` if missing or expired."""
        entry = self._items.get(key)
        if entry is None:
            return None
        stored_at, value = entry
        if self._clock() - stored_at > self.ttl_seconds:
            self._items.pop(key, None)
            return None
        self._items.move_to_end(key)
        return value

    def set(self, key: Hashable, value: Any) -> None:
        if not self.enabled:
            return
        self._items[key] = (self._clock(), value)
        self._items.move_to_end(key)
        self._evict()

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)

    def _evict(self) -> None:
        now = self._clock()
        expired = [k for k, (stored_at, _) in self._items.items() if now - stored_at > self.ttl_seconds]
        for key in expired:
            self._items.pop(key, None)
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)
