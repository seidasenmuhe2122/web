from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from jobs.models import (
    AutomationControl,
    AutomationRun,
    AutomationSchedule,
    Job,
    JobSource,
    RawJobPost,
    TelegramNotification,
)
from jobs.services.collectors import collect_website, collect_telegram
from jobs.services.processor import process_raw
from jobs.services.telegram_service import send_job
from jobs.services.scheduler_service import (
    get_automation_day_bounds,
    get_active_schedule,
    get_schedule_published_count,
    schedule_allows_job,
)
from jobs.services.automation_run import claim_automation_run, finish_automation_run
from jobs.services.utils import safe_error_message


class Command(BaseCommand):
    help = 'Run one complete AFRIJOB collection -> AI -> publish -> Telegram cycle.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=50)
        parser.add_argument('--no-telegram', action='store_true')
        parser.add_argument('--run-id', type=int)

    def handle(self, *args, **opts):
        now = timezone.now()
        run = AutomationRun.objects.filter(pk=opts.get('run_id')).first() if opts.get('run_id') else None
        if opts.get('run_id') and not run:
            raise CommandError('The requested automation run does not exist.')
        if run is None:
            run = claim_automation_run()
            if run is None:
                self.stdout.write(self.style.WARNING('Another automation cycle is already active.'))
                return

        control = AutomationControl.objects.get(pk=1)
        if control.active_run_id != run.pk:
            raise CommandError('This automation run does not own the active worker lease.')

        run.status = 'running'
        run.started_at = now
        run.save(update_fields=['status', 'started_at'])

        def skip_run(reason):
            run.summary = f'skipped: {reason}'
            run.save(update_fields=['summary'])
            finish_automation_run(run, 'skipped')
            self.stdout.write(self.style.WARNING(reason))

        try:
            if not control.enabled:
                skip_run('Automation is disabled.')
                return

            control.last_run_at = now
            control.next_run_at = None
            control.last_error = ''
            control.save(update_fields=['last_run_at', 'next_run_at', 'last_error', 'updated_at'])

            schedule = get_active_schedule(now)
            if not schedule:
                skip_run('No active schedule for the current automation timezone, time, and weekday.')
                return

            schedule_published = get_schedule_published_count(schedule, now)
            remaining_window = max(0, schedule.max_jobs - schedule_published)
            day_start, day_end = get_automation_day_bounds(now)
            local_today = day_start.date()
            daily_published = TelegramNotification.objects.filter(
                status='sent', sent_at__gte=day_start, sent_at__lt=day_end,
            ).values('job_id').distinct().count()
            daily_remaining = (
                max(0, control.daily_max_jobs - daily_published)
                if control.daily_max_jobs else opts['limit']
            )
            publication_limit = min(
                opts['limit'],
                schedule.max_jobs_per_run,
                remaining_window,
                daily_remaining,
            )

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
                    run.save(update_fields=['collected'])

                    source.last_run_at = timezone.now()
                    source.last_error = ''
                    source.save(
                        update_fields=['last_run_at', 'last_error']
                    )

                except Exception as exc:
                    run.failed += 1
                    run.error_message = safe_error_message(f'{source.name}: {exc}')
                    run.save(update_fields=['failed', 'error_message'])
                    source.last_run_at = timezone.now()
                    source.last_error = safe_error_message(exc)
                    source.save(
                        update_fields=['last_run_at', 'last_error']
                    )
                    self.stderr.write(f'{source.name}: {safe_error_message(exc)}')

            stale_before = now - timedelta(hours=1)
            RawJobPost.objects.filter(
                status='processing',
                discovered_at__lt=stale_before,
            ).update(status='new')
            RawJobPost.objects.filter(
                status='failed',
                attempts__lt=3,
            ).update(status='new')

            jobs_to_publish = {}
            for raw in RawJobPost.objects.filter(
                status='new'
            ).order_by('discovered_at')[:opts['limit']]:
                try:
                    job = process_raw(raw)
                except Exception as exc:
                    raw.status = 'failed'
                    raw.last_error = safe_error_message(exc)
                    raw.save(update_fields=['status', 'last_error'])
                    run.failed += 1
                    run.error_message = safe_error_message(exc)
                    run.save(update_fields=['failed', 'error_message'])
                    continue

                if raw.status == 'processed':
                    run.processed += 1
                    if job:
                        jobs_to_publish[job.pk] = job
                elif raw.status == 'rejected':
                    run.rejected += 1
                elif raw.status == 'duplicate':
                    run.duplicates += 1
                elif raw.status == 'failed':
                    run.failed += 1
                    run.error_message = safe_error_message(
                        raw.last_error or 'Raw post processing failed without an error message.'
                    )
                    self.stderr.write(f'Raw post {raw.pk}: {run.error_message}')
                run.save(update_fields=[
                    'processed', 'rejected', 'duplicates', 'failed', 'error_message',
                ])

            if not opts['no_telegram'] and publication_limit > 0:
                expired_or_missing_deadline = Q(deadline__isnull=True) | Q(deadline__gte=local_today)
                pending_jobs = Job.objects.filter(
                    auto_imported=True,
                    telegram_notification_sent_at__isnull=True,
                ).filter(expired_or_missing_deadline).order_by('posted_date')[:opts['limit']]
                for job in pending_jobs:
                    jobs_to_publish.setdefault(job.pk, job)

                if schedule.destinations.exists():
                    destinations = list(schedule.destinations.filter(enabled=True))
                else:
                    destinations = None

                for job in jobs_to_publish.values():
                    if run.published >= publication_limit:
                        break
                    if not schedule_allows_job(schedule, job):
                        continue
                    try:
                        send_job(job, destinations=destinations)
                        run.published += 1
                    except Exception as exc:
                        run.failed += 1
                        run.error_message = safe_error_message(exc)
                        self.stderr.write(f'Telegram: {run.error_message}')
                    run.save(update_fields=['published', 'failed', 'error_message'])

            run.finished_at = timezone.now()
            run.summary = (
                f'collected={run.collected}, '
                f'processed={run.processed}, '
                f'published={run.published}, '
                f'rejected={run.rejected}, '
                f'duplicates={run.duplicates}, '
                f'failed={run.failed}'
            )
            run.status = 'failed' if run.failed else 'success'
            run.save(update_fields=[
                'finished_at', 'summary', 'status', 'collected', 'processed',
                'published', 'rejected', 'duplicates', 'failed', 'error_message',
            ])
            AutomationSchedule.objects.filter(pk=schedule.pk).update(
                last_run_at=run.finished_at,
                jobs_published=schedule.jobs_published + run.published,
            )
            finish_automation_run(run, run.status, run.error_message)

            self.stdout.write(
                self.style.SUCCESS(run.summary)
            )

        except Exception as exc:
            run.failed += 1
            run.error_message = safe_error_message(exc)
            run.summary = (
                f'collected={run.collected}, processed={run.processed}, '
                f'published={run.published}, rejected={run.rejected}, '
                f'duplicates={run.duplicates}, failed={run.failed}'
            )
            run.save(update_fields=['failed', 'error_message', 'summary'])
            finish_automation_run(run, 'failed', run.error_message)
            raise CommandError(run.error_message) from None




