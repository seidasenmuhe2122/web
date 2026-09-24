from django.db import migrations, models
from django.core.validators import RegexValidator


class Migration(migrations.Migration):
    dependencies = [
        ('jobs', '0042_add_previous_admin_background_mode'),
    ]

    operations = [
        migrations.AlterField(
            model_name='sitesetting',
            name='primary_color',
            field=models.CharField(
                default='#38bdf8',
                max_length=7,
                validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
            ),
        ),
        migrations.AlterField(
            model_name='sitesetting',
            name='secondary_color',
            field=models.CharField(
                default='#a855f7',
                max_length=7,
                validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
            ),
        ),
        migrations.AlterField(
            model_name='sitesetting',
            name='background_color',
            field=models.CharField(
                default='#070b16',
                max_length=7,
                validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
            ),
        ),
        migrations.AlterField(
            model_name='sitesetting',
            name='text_color',
            field=models.CharField(
                default='#e0f2fe',
                max_length=7,
                validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
            ),
        ),
        migrations.AlterField(
            model_name='sitesetting',
            name='admin_sidebar_color',
            field=models.CharField(
                default='#070b16',
                max_length=7,
                validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
                verbose_name='Admin sidebar color',
            ),
        ),
        migrations.AlterField(
            model_name='sitesetting',
            name='admin_accent_color',
            field=models.CharField(
                default='#22d3ee',
                max_length=7,
                validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
                verbose_name='Admin accent color',
            ),
        ),
        migrations.AlterField(
            model_name='sitesetting',
            name='admin_workspace_color',
            field=models.CharField(
                default='#0b1120',
                max_length=7,
                validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
                verbose_name='Admin workspace color',
            ),
        ),
    ]
