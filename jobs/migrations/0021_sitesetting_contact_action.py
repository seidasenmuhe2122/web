from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0020_advertisement_display_controls'),
    ]

    operations = [
        migrations.AddField(
            model_name='sitesetting',
            name='contact_action_enabled',
            field=models.BooleanField(default=False, verbose_name='Show contact action button'),
        ),
        migrations.AddField(
            model_name='sitesetting',
            name='contact_action_label',
            field=models.CharField(default='Contact us directly', blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name='sitesetting',
            name='contact_action_url',
            field=models.URLField(blank=True, verbose_name='Contact action URL'),
        ),
    ]