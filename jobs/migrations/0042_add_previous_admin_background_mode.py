from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('jobs', '0041_expand_rich_branding_text'),
    ]

    operations = [
        migrations.AlterField(
            model_name='sitesetting',
            name='admin_background_mode',
            field=models.CharField(
                choices=[
                    ('previous', 'Previous dashboard background'),
                    ('image', 'Image'),
                    ('video', 'Video'),
                    ('3d', '3D video'),
                    ('4k', '4K video'),
                ],
                default='image',
                max_length=10,
                verbose_name='Admin background mode',
            ),
        ),
    ]