from django.core.management.base import BaseCommand
from django.utils import timezone
from jobs.models import Job
class Command(BaseCommand):
    help = 'Report expired jobs without deleting them.'
    def handle(self, *args, **opts):
        self.stdout.write(f'Expired jobs: {Job.objects.filter(deadline__lt=timezone.localdate()).count()}')
