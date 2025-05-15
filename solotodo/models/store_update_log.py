from django.db import models
from django.core.cache import cache

from .category import Category
from .store import Store
from solotodo_core.s3utils import PrivateS3Boto3Storage


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
    registry_file = models.FileField(
        storage=PrivateS3Boto3Storage(),
        upload_to="logs/scrapings",
        null=True,
        blank=True,
    )

    available_products_count = models.IntegerField(null=True, blank=True)
    unavailable_products_count = models.IntegerField(null=True, blank=True)
    discovery_urls_without_products_count = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return "{} - {}".format(self.store, self.creation_date)

    def initialize_task_counter(self, value):
        cache.set(self._caching_key(), value, timeout=60 * 60 * 24)

    def increment_task_counter(self):
        new_val = cache.incr(self._caching_key())
        # print(f"Incrementing: {new_val}")
        return new_val

    def decrement_task_counter(self):
        new_val = cache.decr(self._caching_key())
        # print(f"Decrementing: {new_val}")
        if new_val == 0:
            print("No pending tasks, setting as SUCCESS")
            self.status = StoreUpdateLog.SUCCESS
            self.save()

    def _caching_key(self):
        return f"UPDATE_LOG_{self.id}"

    class Meta:
        app_label = "solotodo"
        ordering = ["store", "-creation_date"]
