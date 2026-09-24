from django.db import migrations, models
from django.core.validators import RegexValidator


class Migration(migrations.Migration):
    dependencies = [
        ('jobs', '0043_image_palette'),
    ]

    operations = [
        migrations.AddField(
            model_name='sitesetting',
            name='admin_primary_color',
            field=models.CharField(
                default='#38bdf8',
                max_length=7,
                validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
                verbose_name='Admin primary color',
            ),
        ),
        migrations.AddField(
            model_name='sitesetting',
            name='admin_secondary_color',
            field=models.CharField(
                default='#a855f7',
                max_length=7,
                validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
                verbose_name='Admin secondary color',
            ),
        ),
        migrations.AddField(
            model_name='sitesetting',
            name='admin_text_color',
            field=models.CharField(
                default='#e0f2fe',
                max_length=7,
                validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
                verbose_name='Admin text color',
            ),
        ),
    ]
