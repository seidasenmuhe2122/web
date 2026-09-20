from django.db import migrations, models


def move_jobs_to_site_default(apps, schema_editor):
    Job = apps.get_model('jobs', 'Job')
    Job.objects.all().update(display_mode='site')


class Migration(migrations.Migration):
    dependencies = [
        ('jobs', '0039_alter_advertisement_position_alter_job_category'),
    ]

    operations = [
        migrations.RunPython(move_jobs_to_site_default, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='job',
            name='display_mode',
            field=models.CharField(
                choices=[
                    ('site', 'Use site default'),
                    ('previous', 'Previous display'),
                    ('work', 'Work display'),
                    ('list', 'List display'),
                ],
                default='site',
                help_text='Choose the display for this job, or inherit the Website Settings default.',
                max_length=10,
            ),
        ),
    ]