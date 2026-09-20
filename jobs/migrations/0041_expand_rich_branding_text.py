from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('jobs', '0040_job_display_mode_per_job'),
    ]

    operations = [
        migrations.AlterField(
            model_name='sitesetting',
            name='top_bar_text',
            field=models.TextField(blank=True, default='Find your next opportunity in Ethiopia'),
        ),
        migrations.AlterField(
            model_name='sitesetting',
            name='background_text',
            field=models.TextField(blank=True, default='AFRI JOB ETHIOPIA'),
        ),
    ]