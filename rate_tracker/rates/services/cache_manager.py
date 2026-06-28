"""
Cache management for Rate-Tracker API.

Cache-aside pattern: read → miss → DB fetch → write cache.
Invalidation: POST /rates/ingest and seed_data both call invalidate_latest_cache().
"""
import logging
from typing import Optional

from django.core.cache import cache

logger = logging.getLogger('rates.cache')

CACHE_TTL = 300  # 5 minutes
CACHE_PREFIX = 'rates'


def _build_latest_key(rate_type: Optional[str] = None) -> str:
    if rate_type:
        return f"{CACHE_PREFIX}:latest:type={rate_type}"
    return f"{CACHE_PREFIX}:latest"


def get_cached_latest(rate_type: Optional[str] = None):
    """Return (data, is_cached) tuple from cache or None if miss."""
    key = _build_latest_key(rate_type)
    data = cache.get(key)
    if data is not None:
        logger.info(f"Cache HIT: {key}")
        return data, True
    logger.info(f"Cache MISS: {key}")
    return None, False


def set_latest_cache(data, rate_type: Optional[str] = None, ttl: int = CACHE_TTL) -> None:
    key = _build_latest_key(rate_type)
    cache.set(key, data, ttl)
    logger.info(f"Cache SET: {key} (ttl={ttl}s, items={len(data) if data else 0})")


def invalidate_latest_cache() -> None:
    """
    Delete all cached 'latest rates' entries.
    Called after any write operation (ingest endpoint or seed_data).

    Uses delete_many with known key patterns since django-redis delete_pattern
    can have performance implications on large key sets.
    """
    from rates.services.data_cleaner import VALID_RATE_TYPES

    keys_to_delete = [_build_latest_key()]  # unfiltered
    for rt in VALID_RATE_TYPES:
        keys_to_delete.append(_build_latest_key(rt))

    deleted = cache.delete_many(keys_to_delete)
    logger.info(f"Cache INVALIDATED: {len(keys_to_delete)} keys cleared")
