import logging
from django.conf import settings
from celery import shared_task

from solotodo.models import Product
from solotodo.tasks import product_save
from .futuremark_utils import \
    get_tdmark_11_score, get_tdmark_cloud_gate_score, \
    get_tdmark_fire_strike_score, get_pcmark_7_score, get_pcmark_8_score
from metamodel.models import InstanceModel


@shared_task(queue='general', ignore_result=True)
def video_card_gpu_save(instance_model_id):
    instance_model = InstanceModel.objects.get(pk=instance_model_id)

    # Create or update the elasticsearch entry for the GPU, as it is not
    # a Product so we must handle it manually
    es = settings.ES
    document, keywords = instance_model.elasticsearch_document()
    es.index(index='videocard-gpus',
             doc_type='GPU',
             id=instance_model.id,
             body=document)

    # Update the GPU score in various benchmarks
    tdmark_id = instance_model.tdmark_id

    instance_model.tdmark_11_score = get_tdmark_11_score(tdmark_id)
    instance_model.tdmark_cloud_gate_score = \
        get_tdmark_cloud_gate_score(tdmark_id)
    instance_model.tdmark_fire_strike_score = \
        get_tdmark_fire_strike_score(tdmark_id)

    # Update the associated VideoCard instances so that their ElasticSearch
    # entries are updated with the new score
    for im in instance_model.fields_usage.all():
        logging.info(u'saving {}'.format(im.parent))
        product = Product.objects.get(instance_model=im.parent)
        product_save.delay(product.id)


@shared_task(queue='general', ignore_result=True)
def processor_save(instance_model_id):
    instance_model = InstanceModel.objects.get(pk=instance_model_id)

    # Update the processor score in various benchmarks
    pcmark_id = instance_model.pcmark_id

    instance_model.pcmark_7_score = get_pcmark_7_score(pcmark_id)
    instance_model.pcmark_8_score = get_pcmark_8_score(pcmark_id)

    product = Product.objects.get(instance_model=instance_model)
    product.save()