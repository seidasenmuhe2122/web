from django.core.management.base import BaseCommand
from django.utils import timezone
from jobs.models import JobSource, RawJobPost, AutomationRun
from jobs.services.collectors import collect_website, collect_telegram
from jobs.services.processor import process_raw
from jobs.services.telegram_service import send_job

class Command(BaseCommand):
    help = 'Run one complete AFRIJOB collection -> AI -> publish -> Telegram cycle.'
    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=50)
        parser.add_argument('--no-telegram', action='store_true')
    def handle(self, *args, **opts):
        run = AutomationRun.objects.create(command='automation_cycle')
        for source in JobSource.objects.filter(enabled=True):
            try:
                if source.source_type == 'website' and hasattr(source, 'website_config'):
                    raws = collect_website(source.website_config)
                elif source.source_type == 'telegram' and hasattr(source, 'telegram_config'):
                    raws = collect_telegram(source.telegram_config)
                else:
                    continue
                run.collected += len(raws)
                source.last_run_at, source.last_error = timezone.now(), ''
                source.save(update_fields=['last_run_at','last_error'])
            except Exception as exc:
                run.failed += 1
                source.last_run_at, source.last_error = timezone.now(), str(exc)
                source.save(update_fields=['last_run_at','last_error'])
                self.stderr.write(f'{source.name}: {exc}')
        for raw in RawJobPost.objects.filter(status='new').order_by('discovered_at')[:opts['limit']]:
            job = process_raw(raw)
            if raw.status == 'processed': run.processed += 1
            elif raw.status == 'rejected': run.rejected += 1
            elif raw.status == 'duplicate': run.duplicates += 1
            elif raw.status == 'failed': run.failed += 1
            if job and not opts['no_telegram'] and not job.telegram_notification_sent_at:
                try:
                    send_job(job); run.published += 1
                except Exception as exc:
                    run.failed += 1
                    self.stderr.write(f'Telegram: {exc}')
        run.finished_at = timezone.now()
        run.summary = f'collected={run.collected}, processed={run.processed}, published={run.published}, rejected={run.rejected}, duplicates={run.duplicates}, failed={run.failed}'
        run.save()
        self.stdout.write(self.style.SUCCESS(run.summary))
