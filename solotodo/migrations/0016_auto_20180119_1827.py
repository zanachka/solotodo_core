# Generated by Django 2.0 on 2018-01-19 18:27

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('solotodo', '0015_auto_20180119_1752'),
    ]

    operations = [
        migrations.AlterField(
            model_name='solotodouser',
            name='preferred_stores',
            field=models.ManyToManyField(blank=True, related_name='_solotodouser_preferred_stores_+', to='solotodo.Store'),
        ),
    ]
