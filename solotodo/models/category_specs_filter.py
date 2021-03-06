from django.db import models
from django import forms
from elasticsearch_dsl import Q

from metamodel.models import MetaModel
from .category import Category


class CategorySpecsFilter(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    meta_model = models.ForeignKey(MetaModel, on_delete=models.CASCADE)
    type = models.CharField(max_length=20, choices=[
        ('exact', 'Exact'),
        ('gte', 'Greater than or equal'),
        ('lte', 'Less than or equal'),
        ('range', 'Range (from / to)'),
    ])
    es_field = models.CharField(max_length=100)
    value_field = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return '{} - {}'.format(self.category, self.name)

    def choices(self):
        if self.meta_model.is_primitive():
            return None
        else:
            return self.meta_model.instancemodel_set.all()

    def form_fields_dict(self):
        field_names = []
        if self.type == 'exact':
            field_names = [self.name]
        else:
            if self.type in ['gte', 'range']:
                field_names = ['{}_min'.format(self.name)]
            if self.type in ['lte', 'range']:
                field_names.append('{}_max'.format(self.name))

        if self.type == 'exact':
            if self.meta_model.name == 'BooleanField':
                field = forms.IntegerField(
                    required=False
                )
            elif self.meta_model.is_primitive():
                raise Exception('Exact query {} not allowed'.format(self.name))
            else:
                field = forms.ModelMultipleChoiceField(
                    queryset=self.meta_model.instancemodel_set.all(),
                    required=False
                )
        else:
            if self.meta_model.is_primitive():
                field_class = getattr(forms, self.meta_model.name)
                field = field_class(required=False)
            else:
                field = forms.ModelChoiceField(
                    queryset=self.meta_model.instancemodel_set.all(),
                    required=False
                )

        return {field_name: field for field_name in field_names}

    def value_field_or_default(self):
        value_field = self.value_field
        if value_field is None:
            if self.type == 'exact':
                value_field = 'id'
            else:
                value_field = 'value'
        return value_field

    def es_value_field(self):
        if self.meta_model.is_primitive():
            return self.es_field
        else:
            value_field = self.value_field_or_default()
            return '{}_{}'.format(self.es_field, value_field)

    def es_id_field(self):
        if self.meta_model.is_primitive():
            return self.es_field
        else:
            return '{}_id'.format(self.es_field)

    def es_filter(self, form_data, prefix=''):
        # TODO: Remove unnecesary prefix parameter once browse codepath is gone
        result = Q()

        mm_value_field = self.value_field_or_default()
        es_value_field = '{}{}'.format(prefix, self.es_value_field())

        if self.type == 'exact' and form_data[self.name] is not None:
            if self.meta_model.is_primitive():
                # The only exact primitive filter is BooleanField
                filter_values = [bool(form_data[self.name])]
            else:
                filter_values = [getattr(obj, mm_value_field) for obj in
                                 form_data[self.name]]

            if filter_values:
                result &= Q('terms', **{es_value_field: filter_values})

        if self.type in ['gte', 'range']:
            min_form_field = '{}_min'.format(self.name)
            if form_data[min_form_field] is not None:
                if self.meta_model.is_primitive():
                    filter_value = form_data[min_form_field]
                else:
                    filter_value = getattr(form_data[min_form_field],
                                           mm_value_field)
                result &= Q('range', **{es_value_field: {'gte': filter_value}})

        if self.type in ['lte', 'range']:
            max_form_field = '{}_max'.format(self.name)
            if form_data[max_form_field] is not None:
                if self.meta_model.is_primitive():
                    filter_value = form_data[max_form_field]
                else:
                    filter_value = getattr(form_data[max_form_field],
                                           mm_value_field)
                result &= Q('range', **{es_value_field: {'lte': filter_value}})

        return result

    def process_buckets(self, buckets):
        if self.meta_model.is_primitive():
            sorted_buckets = sorted(buckets, key=lambda bucket: bucket['key'])

            result = []
            for bucket in sorted_buckets:
                if 'search_bucket' in bucket:
                    doc_count = len(bucket['search_bucket']['buckets'])
                else:
                    doc_count = bucket['doc_count']

                bucket_result = {
                    'id': bucket['key'],
                    'value': bucket['key'],
                    'doc_count': doc_count
                }
                result.append(bucket_result)

            return result

        bucket_key_dict = {bucket['key']: bucket for bucket in buckets}
        value_field = self.value_field_or_default()
        instance_models = self.meta_model.instancemodel_set.all()

        if value_field == 'id':
            instance_models_values_dict = {
                instance_model: instance_model.id
                for instance_model in instance_models
            }
        else:
            # Querying metamodel for fields is expensive, so execute them all
            # at once with a utility queryset method
            instance_models_values_dict = instance_models.get_field_values(
                value_field)

        processed_buckets = []
        for instance_model in instance_models:
            instance_model_value = instance_models_values_dict[instance_model]
            bucket = bucket_key_dict.get(instance_model.id)

            if bucket:
                if 'search_bucket' in bucket:
                    # The search is bucketed
                    doc_count = len(bucket['search_bucket']['buckets'])
                else:
                    doc_count = bucket['doc_count']

                processed_buckets.append({
                    'id': instance_model.id,
                    'value': instance_model_value,
                    'doc_count': doc_count
                })
        return processed_buckets

    class Meta:
        app_label = 'solotodo'
        ordering = ('category', 'name')
