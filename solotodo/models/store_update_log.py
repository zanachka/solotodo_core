import json
import logging

from django.db import models
from django.core.cache import cache

from .category import Category
from .store import Store


class StoreUpdateLog(models.Model):
    PENDING, IN_PROCESS, SUCCESS, ERROR = [1, 2, 3, 4]

    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    categories = models.ManyToManyField(Category)
    status = models.IntegerField(
        choices=[
            (PENDING, "Pending"),
            (IN_PROCESS, "In process"),
            (SUCCESS, "Success"),
            (ERROR, "Error"),
        ],
        default=PENDING,
    )
    creation_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    discovery_url_concurrency = models.IntegerField(null=True, blank=True)
    products_for_url_concurrency = models.IntegerField(null=True, blank=True)
    use_async = models.BooleanField(null=True)
    available_products_count = models.IntegerField(null=True, blank=True)
    unavailable_products_count = models.IntegerField(null=True, blank=True)
    discovery_urls_without_products_count = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return "{} - {}".format(self.store, self.creation_date)

    def initialize_task_counter(self, value):
        cache.set(self._caching_key(), value, timeout=60 * 60 * 24)
        available_products_cache_key = f"{self._caching_key()}_available_products_count"
        cache.set(available_products_cache_key, 0, timeout=60 * 60 * 24)
        unavailable_products_cache_key = (
            f"{self._caching_key()}_unavailable_products_count"
        )
        cache.set(unavailable_products_cache_key, 0, timeout=60 * 60 * 24)
        discovery_urls_without_products_cache_key = (
            f"{self._caching_key()}_discovery_urls_without_products_count"
        )
        cache.set(discovery_urls_without_products_cache_key, 0, timeout=60 * 60 * 24)

    def increment_task_counter(self):
        new_val = cache.incr(self._caching_key())
        return new_val

    def increment_available_products_count(self):
        available_products_cache_key = f"{self._caching_key()}_available_products_count"
        cache.incr(available_products_cache_key)

    def increment_unavailable_products_count(self):
        unavailable_products_cache_key = (
            f"{self._caching_key()}_unavailable_products_count"
        )
        cache.incr(unavailable_products_cache_key)

    def increment_discovery_urls_without_products_count(self):
        discovery_urls_without_products_cache_key = (
            f"{self._caching_key()}_discovery_urls_without_products_count"
        )
        cache.incr(discovery_urls_without_products_cache_key)

    def decrement_task_counter(self):
        new_val = cache.decr(self._caching_key())
        if new_val == 0:
            logger = logging.getLogger("logstash")
            logger.info(
                json.dumps(
                    {"message": "Finished pricing update", "update_log_id": self.id}
                )
            )
            if self.status == StoreUpdateLog.IN_PROCESS:
                self.status = StoreUpdateLog.SUCCESS
                self.available_products_count = cache.get(
                    f"{self._caching_key()}_available_products_count"
                )
                self.unavailable_products_count = cache.get(
                    f"{self._caching_key()}_unavailable_products_count"
                )
                self.discovery_urls_without_products_count = cache.get(
                    f"{self._caching_key()}_discovery_urls_without_products_count"
                )
                self.save()

    def _caching_key(self):
        return f"UPDATE_LOG_{self.id}"

    class Meta:
        app_label = "solotodo"
        ordering = ["store", "-creation_date"]
