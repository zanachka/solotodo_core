# Generated by Django 2.0.3 on 2019-07-17 19:45

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('soicos_conversions', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='soicosconversion',
            name='lead',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='solotodo.Lead'),
        ),
    ]
