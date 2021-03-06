# Generated by Django 2.2.13 on 2020-08-17 21:04

from django.db import migrations, models
import storages.backends.s3boto3


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0005_report_slug'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='report',
            options={'ordering': ('name',), 'permissions': (('backend_list_reports', 'Can view report list in backend'),)},
        ),
        migrations.AlterField(
            model_name='reportdownload',
            name='file',
            field=models.FileField(storage=storages.backends.s3boto3.S3Boto3Storage(custom_domain=None, default_acl='private'), upload_to=''),
        ),
    ]
