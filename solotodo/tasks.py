import json
import logging

from celery import shared_task
from django.core.mail import EmailMessage
from django.http import QueryDict

from solotodo.memcached_limiter import (
    ConcurrencyLimitReached,
    memcached_site_limit,
    RetryLimitExceeded,
    memcached_retry_tracker,
)
from solotodo.models import (
    Store,
    Category,
    StoreUpdateLog,
    Product,
    Entity,
    StoreSectionPositionsUpdateLog,
)
from storescraper.store import StoreScrapError

from solotodo.utils import sha256

MAX_RETRIES = 400


@shared_task(queue="general", ignore_result=True)
def product_save(product_id):
    Product.objects.get(pk=product_id).save()


@shared_task(queue="general", ignore_result=True)
def entity_save(entity_id):
    Entity.objects.get(pk=entity_id).save()


@shared_task(queue="general", ignore_result=True)
def es_leads_index():
    from solotodo.models import Lead
    from solotodo.es_models.es_lead import EsLead

    bucket_count = Lead.objects.count() // 5000

    for i in range(bucket_count):
        offset = i * 5000
        print("{} de {}".format(i, bucket_count))

        lead_ids = [
            x["id"] for x in Lead.objects.all()[offset : offset + 5000].values("id")
        ]

        leads = Lead.objects.filter(pk__in=lead_ids)

        EsLead.create_from_db_leads(leads)


@shared_task(queue="general", ignore_result=True)
def entity_save(entity_id):
    Entity.objects.get(pk=entity_id).save()


@shared_task(queue="reports", ignore_result=True, task_time_limit=60 * 30)
def send_historic_entity_positions_report_task(store_id, user_id, query_string):
    from django.contrib.auth import get_user_model
    from solotodo.forms.store_historic_entity_positions_form import (
        StoreHistoricEntityPositionsForm,
    )

    user = get_user_model().objects.get(pk=user_id)
    store = Store.objects.get(pk=store_id)

    q_dict = QueryDict(query_string)
    form = StoreHistoricEntityPositionsForm(user, q_dict)

    if not form.is_valid():
        return

    report_data = form.generate_report(store)
    report_filename = "{}.xlsx".format(report_data["filename"])
    report_file = report_data["file"]

    formatted_start_date = form.cleaned_data["timestamp"].start.strftime("%Y-%m-%d")
    formatted_end_date = form.cleaned_data["timestamp"].stop.strftime("%Y-%m-%d")

    selected_categories = form.cleaned_data["categories"]
    available_categories = form.fields["categories"].queryset

    if len(selected_categories) == len(available_categories):
        formatted_categories = "Todas las categorias"
    else:
        formatted_categories = ", ".join([str(x) for x in selected_categories])

    sender = get_user_model().get_bot().email_recipient_text()
    message = (
        "Se adjunta el reporte de posicionamiento histórico para la "
        "tienda {} entre {} y {} para las categorias: {}"
        "".format(store, formatted_start_date, formatted_end_date, formatted_categories)
    )

    subject = "Reporte posicionamiento histórico {} - {} al {} - {}".format(
        store, formatted_start_date, formatted_end_date, formatted_categories
    )

    email = EmailMessage(subject, message, sender, [user.email])
    email.attach(
        report_filename,
        report_file,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    email.send()


@shared_task(queue="general", ignore_result=True)
def update_entity_sec_qr_codes(entity_id):
    e = Entity.objects.get(pk=entity_id)
    e.update_sec_qr_codes()


@shared_task(
    queue="ai",
    ignore_result=True,
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=10,
)
def ai_associate_entity(entity_id):
    entity = Entity.objects.get(pk=entity_id)
    entity.ai_associate()


@shared_task(
    queue="ai",
    ignore_result=True,
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=10,
)
def ai_entity_update_category(entity_id):
    entity = Entity.objects.get(pk=entity_id)
    entity.ai_update_category()


@shared_task(
    bind=True,
    queue="storescraper",
    ignore_result=True,
    max_retries=MAX_RETRIES,
)
def store_category_update_pricing(
    self,
    store_id,
    category_id,
    discover_urls_concurrency,
    products_for_url_concurrency,
    use_async,
    update_log_id,
    extra_args,
):
    category = Category.objects.get(pk=category_id)
    logger = logging.getLogger("logstash")
    update_log = StoreUpdateLog.objects.get(pk=update_log_id)
    print(f"Category {category} Update Pricing retry # {self.request.retries}")

    try:
        with memcached_site_limit(
            f"{store_id}_discover_entries",
            limit=discover_urls_concurrency,
        ):
            store = Store.objects.get(pk=store_id)
            store.update_pricing_category(
                category,
                products_for_url_concurrency,
                use_async,
                update_log,
                extra_args,
            )
    except ConcurrencyLimitReached as e:
        cache_key = f"store_category_update_pricing:ConcurrencyLimitReached:{update_log.id}:{category.storescraper_name}"

        try:
            with memcached_retry_tracker(cache_key, MAX_RETRIES):
                raise self.retry(exc=e, countdown=3)
        except RetryLimitExceeded:
            update_log.save_with_error(logger)

    except StoreScrapError as e:
        payload = {
            "message": f"Error: {e}",
            "update_log_id": update_log.id,
        }
        cache_key = f"store_category_update_pricing:StoreScrapError:{update_log.id}:{category.storescraper_name}"
        limit = 5

        try:
            with memcached_retry_tracker(cache_key, limit):
                logger.warning(json.dumps(payload))
                raise self.retry(exc=e, countdown=10)
        except RetryLimitExceeded:
            update_log.decrement_task_counter()
            update_log.save_with_error(logger)
    except Exception:
        update_log.decrement_task_counter()
        update_log.save_with_error(logger)


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
    bind=True,
    queue="storescraper",
    ignore_result=True,
    max_retries=MAX_RETRIES,
)
def store_update_individual_section_positions(
    self,
    store_id,
    section,
    concurrency,
    section_positions_update_log_id,
    extra_args,
):
    print(f"Section {section} Update Pricing retry # {self.request.retries}")
    update_log = StoreSectionPositionsUpdateLog.objects.get(
        pk=section_positions_update_log_id
    )
    logger = logging.getLogger("logstash")

    try:
        with memcached_site_limit(
            f"{store_id}_section_positions",
            limit=concurrency,
        ):
            store = Store.objects.get(pk=store_id)
            store.update_individual_section_positions(
                section,
                update_log,
                extra_args,
            )
    except ConcurrencyLimitReached as e:
        cache_key = f"store_update_individual_section_positions:ConcurrencyLimitReached:{update_log.id}:{sha256(section)}"

        try:
            with memcached_retry_tracker(cache_key, MAX_RETRIES):
                raise self.retry(exc=e, countdown=20)
        except RetryLimitExceeded:
            update_log.save_with_error(logger)
    except StoreScrapError as e:
        cache_key = f"store_update_individual_section_positions:StoreScrapError:{update_log.id}:{sha256(section)}"
        limit = 5

        try:
            with memcached_retry_tracker(cache_key, limit):
                raise self.retry(exc=e, countdown=10)
        except RetryLimitExceeded:
            update_log.decrement_task_counter()
            update_log.save_with_error(logger)
    except Exception:
        update_log.decrement_task_counter()
        update_log.save_with_error(logger)
