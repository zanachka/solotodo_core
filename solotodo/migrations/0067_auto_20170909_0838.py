# -*- coding: utf-8 -*-
# Generated by Django 1.11.3 on 2017-09-09 11:38
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('solotodo', '0066_product_last_updated'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='solotodouser',
            options={'ordering': ('-date_joined',), 'verbose_name': 'SoloTodo User', 'verbose_name_plural': 'SoloTodo Users'},
        ),
    ]
