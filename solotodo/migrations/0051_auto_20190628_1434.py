# Generated by Django 2.0.3 on 2019-06-28 14:34

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('solotodo', '0050_auto_20190625_2048'),
    ]

    operations = [
        migrations.AddField(
            model_name='entity',
            name='has_virtual_assistant',
            field=models.NullBooleanField(),
        ),
        migrations.AddField(
            model_name='entitylog',
            name='has_virtual_assistant',
            field=models.NullBooleanField(),
        ),
    ]
