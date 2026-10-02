from django.db.models import Q
from .utils import normalize, sha256
from ..models import Job

def fingerprint(data, content=''):
    parts = [normalize(data.get('title')), normalize(data.get('company')), normalize(data.get('location')),
             (data.get('application_url') or '').strip().lower(), (data.get('source_url') or '').strip().lower(),
             normalize(content)]
    return sha256('||'.join(parts))

def find_duplicate(data, content=''):
    h = fingerprint(data, content)
    existing_job = Job.objects.filter(content_hash=h, auto_imported=True).first()
    if existing_job:
        return existing_job

    title = normalize(data.get('title'))
    company = normalize(data.get('company'))
    q = Q()
    if title and company:
        q |= Q(normalized_title=title, normalized_company=company)
    if data.get('source_url'):
        q |= Q(source_url=(data.get('source_url') or '').strip())
    return Job.objects.filter(q, auto_imported=True).first() if q else None
