from contextlib import contextmanager
from django.core.cache import cache


class ConcurrencyLimitReached(Exception):
    pass


@contextmanager
def memcached_site_limit(key, limit=10, expire=60 * 60):
    acquired = False
    # print("Acquiring lock")

    try:
        current = cache.get_or_set(key, 0, expire)
        # print(f"{key}: {current}")
        if int(current) <= limit:
            cache.incr(key, 1)
            acquired = True

        if not acquired:
            # print("Failed to acquire cache lock, raising exception")
            raise ConcurrencyLimitReached()

        yield

    finally:
        if acquired:
            # print("Releasing lock, decreasing cache value")
            cache.decr(key, 1)


class RetryLimitExceeded(Exception):
    pass


@contextmanager
def memcached_retry_tracker(key, limit=5, expire=60 * 60):
    current = cache.get_or_set(key, 0, expire)

    if int(current) >= limit:
        raise RetryLimitExceeded(f"Retry limit exceeded for key: {key}")

    cache.incr(key, 1)
    yield
