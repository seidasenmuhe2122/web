from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0021_sitesetting_contact_action'),
    ]

    operations = [
        migrations.AddField(
            model_name='sitesetting',
            name='contact_submit_enabled',
            field=models.BooleanField(default=True, verbose_name='Show Send message button'),
        ),
    ]