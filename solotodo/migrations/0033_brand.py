# Generated by Django 2.0.3 on 2019-02-13 18:43

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('solotodo', '0032_auto_20190206_1357'),
    ]

    operations = [
        migrations.CreateModel(
            name='Brand',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(db_index=True, max_length=255, unique=True)),
            ],
            options={
                'ordering': ('name',),
            },
        ),
    ]
