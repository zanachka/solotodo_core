from contextlib import contextmanager
from django.core.cache import cache


class ConcurrencyLimitReached(Exception):
    pass


@contextmanager
def memcached_site_limit(key, limit=10, expire=60):
    acquired = False
    print("Acquiring lock")

    try:
        current = cache.get_or_set(key, 1, expire)
        print(f"{key}: {current}")
        if int(current) <= limit:
            print(f"Value to use: {current}")
            new_val = cache.incr(key, 1)
            if new_val <= limit:
                acquired = True
        else:
            print(f"Cache {current} over limit {limit}")

        if not acquired:
            print("Failed to acquire cache lock, raising exception")
            raise ConcurrencyLimitReached()

        yield

    finally:
        if acquired:
            try:
                print("Releasing lock, decreasing cache value")
                cache.decr(key, 1)
            except Exception as e:
                print(e)
                pass
