from django.core.management.base import BaseCommand
from jobs.models import JobSource
from jobs.services.collectors import collect_website, collect_telegram


class Command(BaseCommand):
    help = 'Collect new posts from enabled configured sources.'

    def handle(self, *args, **opts):
        for source in JobSource.objects.filter(enabled=True):
            try:
                if source.source_type == 'website' and hasattr(source, 'website_config'):
                    collect_website(source.website_config)

                elif source.source_type == 'telegram' and hasattr(source, 'telegram_config'):
                    collect_telegram(source.telegram_config)

            except Exception as exc:
                self.stderr.write(
                    self.style.ERROR(f'{source.name}: {exc}')
                )
                continue
