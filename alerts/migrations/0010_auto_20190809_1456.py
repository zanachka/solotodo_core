# Generated by Django 2.0.3 on 2019-08-09 14:56

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('alerts', '0009_productpricealert_active_history'),
    ]

    operations = [
        migrations.DeleteModel(
            name='ProductPriceAlertHistoryEntry',
        ),
    ]
