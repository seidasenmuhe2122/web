from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0019_advertisement_ad_text'),
    ]

    operations = [
        migrations.AddField(
            model_name='advertisement',
            name='image_height',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Manual height (px)'),
        ),
        migrations.AddField(
            model_name='advertisement',
            name='image_width',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Manual width (px)'),
        ),
        migrations.AddField(
            model_name='advertisement',
            name='size_mode',
            field=models.CharField(choices=[('auto', 'Auto (responsive)'), ('manual', 'Manual')], default='auto', max_length=10),
        ),
        migrations.AddField(
            model_name='advertisement',
            name='text_color',
            field=models.CharField(default='#ffffff', max_length=7, verbose_name='Text color'),
        ),
        migrations.AddField(
            model_name='advertisement',
            name='text_placement',
            field=models.CharField(choices=[('below', 'Below advertisement'), ('above', 'Above advertisement'), ('left', 'Left of advertisement'), ('right', 'Right of advertisement')], default='below', max_length=10),
        ),
        migrations.AddField(
            model_name='advertisement',
            name='text_size',
            field=models.PositiveIntegerField(default=16, verbose_name='Text size (px)'),
        ),
    ]