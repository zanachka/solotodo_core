# -*- coding: utf-8 -*-
# Generated by Django 1.11.3 on 2017-07-24 21:03
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('solotodo', '0011_auto_20170724_1628'),
    ]

    operations = [
        migrations.AddField(
            model_name='store',
            name='type',
            field=models.IntegerField(choices=[(1, 'Retail'), (2, 'Wholesaler'), (3, 'Mobile network operator')], default=1),
        ),
    ]
