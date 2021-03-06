# -*- coding: utf-8 -*-
# Generated by Django 1.11.3 on 2017-11-24 20:11
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('solotodo', '0009_auto_20171114_2039'),
    ]

    operations = [
        migrations.CreateModel(
            name='CategoryColumn',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('country', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='solotodo.Country')),
            ],
            options={
                'ordering': ('field', 'purpose', 'country'),
            },
        ),
        migrations.CreateModel(
            name='CategoryColumnPurpose',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
            ],
            options={
                'ordering': ('name',),
            },
        ),
        migrations.CreateModel(
            name='CategoryField',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('es_field', models.CharField(max_length=100)),
                ('label', models.CharField(max_length=100)),
                ('category', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='solotodo.Category')),
            ],
            options={
                'ordering': ('category', 'label', 'es_field'),
            },
        ),
        migrations.AddField(
            model_name='categorycolumn',
            name='field',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='category_columns.CategoryField'),
        ),
        migrations.AddField(
            model_name='categorycolumn',
            name='purpose',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='category_columns.CategoryColumnPurpose'),
        ),
    ]
