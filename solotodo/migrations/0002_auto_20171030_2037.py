# -*- coding: utf-8 -*-
# Generated by Django 1.11.3 on 2017-10-30 20:37
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('solotodo', '0001_initial'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='apiclient',
            options={'ordering': ('name',), 'permissions': [('view_api_client', 'Can view the API client'), ('view_api_client_leads', 'Can view the leads associated to this API client')]},
        ),
        migrations.AlterModelOptions(
            name='store',
            options={'ordering': ['name'], 'permissions': (['view_store', 'Can view the store'], ['view_store_update_logs', 'Can view the store update logs'], ['view_store_stocks', 'Can view the store entities stock'], ['update_store_pricing', 'Can update the store pricing'], ['is_store_staff', 'Is staff of the store'], ('view_store_leads', 'View the leads associated to this store'), ['backend_list_stores', 'Can view store list in backend'])},
        ),
    ]