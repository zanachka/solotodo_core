# Generated by Django 2.0.3 on 2018-06-25 16:05

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('solotodo', '0028_productpicture'),
    ]

    operations = [
        migrations.AddField(
            model_name='entityhistory',
            name='estimated_sales_since_previous_registry',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
