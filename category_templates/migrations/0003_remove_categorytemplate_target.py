# -*- coding: utf-8 -*-
# Generated by Django 1.11.3 on 2017-09-25 14:34
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('category_templates', '0002_auto_20170925_1134'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='categorytemplate',
            name='target',
        ),
    ]