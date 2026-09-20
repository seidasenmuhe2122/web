from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0018_alter_advertisement_position_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='advertisement',
            name='ad_text',
            field=models.TextField(blank=True, verbose_name='Advertisement text'),
        ),
    ]