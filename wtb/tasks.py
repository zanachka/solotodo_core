import json
import logging

from celery import shared_task

from solotodo.memcached_limiter import (
    memcached_site_limit,
    ConcurrencyLimitReached,
    memcached_retry_tracker,
    RetryLimitExceeded,
)
from solotodo.models import Category
from storescraper.store import StoreScrapError

from solotodo.utils import sha256
from wtb.models import WtbBrandUpdateLog, WtbBrand

MAX_RETRIES = 400


@shared_task(
    bind=True,
    queue="storescraper",
    ignore_result=True,
    max_retries=MAX_RETRIES,
)
def wtb_brand_category_update_pricing(
    self,
    wtb_brand_id,
    category_id,
    discover_urls_concurrency,
    products_for_url_concurrency,
    use_async,
    wtb_brand_update_log_id,
    extra_args,
):
    category = Category.objects.get(pk=category_id)
    logger = logging.getLogger("logstash")
    wtb_brand_update_log = WtbBrandUpdateLog.objects.get(pk=wtb_brand_update_log_id)
    print(f"Category {category} WTB Update Entities retry # {self.request.retries}")

    try:
        with memcached_site_limit(
            f"wtb_{wtb_brand_id}_discover_entries",
            limit=discover_urls_concurrency,
        ):
            wtb_brand = WtbBrand.objects.get(pk=wtb_brand_id)
            wtb_brand.update_entities_category(
                category,
                products_for_url_concurrency,
                use_async,
                wtb_brand_update_log,
                extra_args,
            )
    except ConcurrencyLimitReached as e:
        cache_key = f"wtb_category_update_entities:ConcurrencyLimitReached:{wtb_brand_update_log.id}:{category.storescraper_name}"

        try:
            with memcached_retry_tracker(cache_key, MAX_RETRIES):
                raise self.retry(exc=e, countdown=3)
        except RetryLimitExceeded:
            wtb_brand_update_log.save_with_error(logger)

    except StoreScrapError as e:
        payload = {
            "message": f"Error: {e}",
            "wtb_update_log_id": wtb_brand_update_log.id,
        }
        cache_key = f"wtb_category_update_entities:StoreScrapError:{wtb_brand_update_log.id}:{category.storescraper_name}"
        limit = 5

        try:
            with memcached_retry_tracker(cache_key, limit):
                logger.warning(json.dumps(payload))
                raise self.retry(exc=e, countdown=10)
        except RetryLimitExceeded:
            wtb_brand_update_log.decrement_task_counter()
            wtb_brand_update_log.save_with_error(logger)
    except Exception:
        wtb_brand_update_log.decrement_task_counter()
        wtb_brand_update_log.save_with_error(logger)


@shared_task(
    bind=True, queue="storescraper", ignore_result=True, max_retries=MAX_RETRIES
)
def store_create_or_update_entity_from_discovery_url(
    self,
    store_id,
    update_log_id,
    discovery_url,
    category_id,
    extra_args,
    products_for_url_concurrency,
):
    print(f"Create or update entity retry # {self.request.retries}")
    update_log = StoreUpdateLog.objects.get(pk=update_log_id)
    logger = logging.getLogger("logstash")

    try:
        with memcached_site_limit(
            f"{store_id}_products_for_url",
            limit=products_for_url_concurrency,
        ):
            store = Store.objects.get(pk=store_id)
            category = Category.objects.get(pk=category_id)
            store.create_or_update_entity_from_discovery_url(
                update_log, discovery_url, category, extra_args
            )
    except ConcurrencyLimitReached as e:
        cache_key = f"store_create_or_update_entity_from_discovery_url:ConcurrencyLimitReached:{update_log_id}:{sha256(discovery_url)}"

        try:
            with memcached_retry_tracker(cache_key, MAX_RETRIES):
                raise self.retry(exc=e, countdown=3, max_retries=MAX_RETRIES)
        except RetryLimitExceeded:
            update_log.save_with_error(logger, discovery_url)
    except StoreScrapError as e:
        cache_key = f"store_create_or_update_entity_from_discovery_url:StoreScrapError:{update_log_id}:{sha256(discovery_url)}"
        limit = 5

        try:
            with memcached_retry_tracker(cache_key, limit) as tracker:
                payload = {
                    "message": f"Error: {e}, Current: {tracker}",
                    "update_log_id": update_log.id,
                    "current": tracker,
                    "discovery_url": discovery_url,
                }
                logger.warning(json.dumps(payload))
                raise self.retry(exc=e, countdown=10)
        except RetryLimitExceeded:
            update_log.decrement_task_counter()
            update_log.save_with_error(logger, discovery_url)
    except Exception:
        update_log.decrement_task_counter()
        update_log.save_with_error(logger, discovery_url)


@shared_task(
    bind=True, queue="storescraper", ignore_result=True, max_retries=MAX_RETRIES
)
def wtb_brand_create_or_update_entity_from_discovery_url(
    self,
    wtb_brand_id,
    wtb_brand_update_log_id,
    discovery_url,
    category_id,
    extra_args,
    products_for_url_concurrency,
):
    print(f"Create or update entity retry # {self.request.retries}")
    wtb_brand_update_log = WtbBrandUpdateLog.objects.get(pk=wtb_brand_update_log_id)
    logger = logging.getLogger("logstash")

    try:
        with memcached_site_limit(
            f"wtb_{wtb_brand_id}_products_for_url",
            limit=products_for_url_concurrency,
        ):
            wtb_brand = WtbBrand.objects.get(pk=wtb_brand_id)
            category = Category.objects.get(pk=category_id)
            wtb_brand.create_or_update_entity_from_discovery_url(
                wtb_brand_update_log, discovery_url, category, extra_args
            )
    except ConcurrencyLimitReached as e:
        cache_key = f"wtb_create_or_update_entity_from_discovery_url:ConcurrencyLimitReached:{wtb_brand_update_log_id}:{sha256(discovery_url)}"

        try:
            with memcached_retry_tracker(cache_key, MAX_RETRIES):
                raise self.retry(exc=e, countdown=3, max_retries=MAX_RETRIES)
        except RetryLimitExceeded:
            wtb_brand_update_log.save_with_error(logger, discovery_url)
    except StoreScrapError as e:
        cache_key = f"wtb_create_or_update_entity_from_discovery_url:StoreScrapError:{wtb_brand_update_log_id}:{sha256(discovery_url)}"
        limit = 5

        try:
            with memcached_retry_tracker(cache_key, limit) as tracker:
                payload = {
                    "message": f"Error: {e}, Current: {tracker}",
                    "wtb_update_log_id": wtb_brand_update_log.id,
                    "current": tracker,
                    "discovery_url": discovery_url,
                }
                logger.warning(json.dumps(payload))
                raise self.retry(exc=e, countdown=10)
        except RetryLimitExceeded:
            wtb_brand_update_log.decrement_task_counter()
            wtb_brand_update_log.save_with_error(logger, discovery_url)
    except Exception:
        wtb_brand_update_log.decrement_task_counter()
        wtb_brand_update_log.save_with_error(logger, discovery_url)
