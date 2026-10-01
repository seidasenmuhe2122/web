from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from jobs.models import JobSource, RawJobPost, AutomationRun, AutomationControl
from jobs.services.collectors import collect_website, collect_telegram
from jobs.services.processor import process_raw
from jobs.services.telegram_service import send_job


class Command(BaseCommand):
    help = 'Run one complete AFRIJOB collection -> AI -> publish -> Telegram cycle.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=50)
        parser.add_argument('--no-telegram', action='store_true')

    def handle(self, *args, **opts):
        now = timezone.now()

        control, _ = AutomationControl.objects.get_or_create(
            pk=1,
            defaults={'enabled': True, 'frequency_minutes': 15},
        )

        if not control.enabled:
            self.stdout.write(self.style.WARNING('Automation is disabled.'))
            return

        if control.frequency_minutes == 0:
            self.stdout.write(
                self.style.WARNING('Automation is set to Manual only.')
            )
            return

        if control.last_run_at:
            next_allowed = control.last_run_at + timedelta(
                minutes=control.frequency_minutes
            )

            if now < next_allowed:
                remaining = next_allowed - now
                self.stdout.write(
                    self.style.WARNING(
                        f'Automation skipped. Next run in {remaining}.'
                    )
                )
                control.next_run_at = next_allowed
                control.save(update_fields=['next_run_at'])
                return

        control.last_run_at = now
        control.next_run_at = now + timedelta(
            minutes=control.frequency_minutes
        )
        control.last_error = ''
        control.save(
            update_fields=[
                'last_run_at',
                'next_run_at',
                'last_error',
                'updated_at',
            ]
        )

        run = AutomationRun.objects.create(command='automation_cycle')

        try:
            for source in JobSource.objects.filter(enabled=True):
                try:
                    if source.source_type == 'website' and hasattr(
                        source, 'website_config'
                    ):
                        raws = collect_website(source.website_config)

                    elif source.source_type == 'telegram' and hasattr(
                        source, 'telegram_config'
                    ):
                        raws = collect_telegram(source.telegram_config)

                    else:
                        continue

                    run.collected += len(raws)

                    source.last_run_at = timezone.now()
                    source.last_error = ''
                    source.save(
                        update_fields=['last_run_at', 'last_error']
                    )

                except Exception as exc:
                    run.failed += 1
                    source.last_run_at = timezone.now()
                    source.last_error = str(exc)
                    source.save(
                        update_fields=['last_run_at', 'last_error']
                    )
                    self.stderr.write(
                        f'{source.name}: {exc}'
                    )

            for raw in RawJobPost.objects.filter(
                status='new'
            ).order_by('discovered_at')[:opts['limit']]:

                job = process_raw(raw)

                if raw.status == 'processed':
                    run.processed += 1
                elif raw.status == 'rejected':
                    run.rejected += 1
                elif raw.status == 'duplicate':
                    run.duplicates += 1
                elif raw.status == 'failed':
                    run.failed += 1
                if (
                    job
                    and not opts['no_telegram']
                    and not job.telegram_notification_sent_at
                ):
                    try:
                        send_job(job)
                        run.published += 1
                    except Exception as exc:
                        run.failed += 1
                        self.stderr.write(
                            f'Telegram: {exc}'
                        )

            run.finished_at = timezone.now()
            run.summary = (
                f'collected={run.collected}, '
                f'processed={run.processed}, '
                f'published={run.published}, '
                f'rejected={run.rejected}, '
                f'duplicates={run.duplicates}, '
                f'failed={run.failed}'
            )
            run.save()

            self.stdout.write(
                self.style.SUCCESS(run.summary)
            )

        except Exception as exc:
            control.last_error = str(exc)
            control.save(update_fields=['last_error', 'updated_at'])
            raise
