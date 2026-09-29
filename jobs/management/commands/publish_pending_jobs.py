from django.core.management.base import BaseCommand
from jobs.models import Job
from jobs.services.telegram_service import send_job
class Command(BaseCommand):
    help = 'Send website links for auto-imported jobs that have not been notified.'
    def handle(self, *args, **opts):
        for job in Job.objects.filter(auto_imported=True, telegram_notification_sent_at__isnull=True):
            try: send_job(job)
            except Exception as exc: self.stderr.write(f'{job.pk}: {exc}')
