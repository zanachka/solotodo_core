# -*- coding: utf-8 -*-
# Generated by Django 1.11.3 on 2017-07-24 20:28
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('solotodo', '0010_auto_20170715_1539'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='store',
            options={'ordering': ['name'], 'permissions': (['view_store', 'Can view store'],)},
        ),
    ]
