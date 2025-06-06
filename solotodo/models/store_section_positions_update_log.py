import json
import logging
import traceback

from django.db import models
from django.core.cache import cache

from .store import Store


class StoreSectionPositionsUpdateLog(models.Model):
    PENDING, IN_PROCESS, SUCCESS, ERROR = [1, 2, 3, 4]

    store = models.ForeignKey(Store, on_delete=models.CASCADE)
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
    concurrency = models.IntegerField()
    use_async = models.BooleanField()

    def __str__(self):
        return "{} - {}".format(self.store, self.creation_date)

    def initialize_task_counter(self, value):
        cache.set(self._caching_key(), value, timeout=60 * 60 * 24)

    def increment_task_counter(self):
        new_val = cache.incr(self._caching_key())
        return new_val

    def decrement_task_counter(self):
        new_val = cache.decr(self._caching_key())
        if new_val == 0:
            logger = logging.getLogger("logstash")
            logger.info(
                json.dumps(
                    {
                        "message": "Finished section position update",
                        "section_positions_update_log_id": self.id,
                    }
                )
            )
            if self.status == StoreSectionPositionsUpdateLog.IN_PROCESS:
                self.status = StoreSectionPositionsUpdateLog.SUCCESS
                self.save()

    def save_with_error(self, logger):
        self.status = self.ERROR
        self.save()
        payload = {
            "message": f"Error: {traceback.format_exc()}",
            "section_positions_update_log_id": self.id,
        }
        logger.error(json.dumps(payload))

    def _caching_key(self):
        return f"SECTION_POSITION_LOG_{self.id}"

    class Meta:
        app_label = "solotodo"
        ordering = ["store", "-creation_date"]
