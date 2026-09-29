from django.core.management.base import BaseCommand
from jobs.models import RawJobPost
from jobs.services.processor import process_raw
class Command(BaseCommand):
    help = 'Process pending raw job posts with the AI fallback chain.'
    def add_arguments(self, parser): parser.add_argument('--limit', type=int, default=50)
    def handle(self, *args, **opts):
        for raw in RawJobPost.objects.filter(status='new').order_by('discovered_at')[:opts['limit']]: process_raw(raw)
