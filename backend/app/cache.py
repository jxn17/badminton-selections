"""In-memory read cache for the public bracket/draws endpoints.

Everyone looking at a draw sees byte-identical data, so during a traffic spike
(the moment a round's times go out and 200 people open the page at once) it is
pure waste to re-run the same three queries per visitor. These endpoints are
served from a process-local TTL cache holding the already-built Pydantic models,
so a cache hit never touches the database at all.

Two properties keep this safe to look at during a live event:

* **Writes bust it.** Every admin mutation clears the cache (see the router
  dependency in routers/admin.py), so the TTL only ever delays data that hasn't
  changed. A score entered at 10:00:01 is visible on the very next request.
* **Admins are never served from it.** Admin responses embed phone numbers and
  the shortlist flag; only the public (PII-free) shape is ever cached, and only
  a request without an admin session can read it.

Scope is one process. With multiple uvicorn workers each keeps its own copy —
that's fine, they're all derived from the same DB and expire on the same TTL.
"""
from __future__ import annotations

from typing import Any

from cachetools import TTLCache

from .config import get_settings

_ttl = max(1, get_settings().public_cache_ttl)

# ~a dozen live keys in practice (men A–D + women, plus a few stale spellings).
_public: TTLCache[Any, Any] = TTLCache(maxsize=64, ttl=_ttl)

# Bumped on every write; folded into cache keys so an in-flight miss that
# populates *after* a bust can never resurrect pre-write data.
_version = 0


def get(key: Any) -> Any | None:
    """Cached value for `key`, or None on miss/expiry."""
    return _public.get((_version, key))


def put(key: Any, value: Any) -> None:
    _public[(_version, key)] = value


def invalidate() -> None:
    """Drop everything. Called after any admin write."""
    global _version
    _version += 1
    _public.clear()


def stats() -> dict:
    return {"entries": len(_public), "ttl_seconds": _ttl, "version": _version}
