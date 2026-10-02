from datetime import datetime
from django.utils import timezone
from .ai_service import extract_job
from .dedupe_service import find_duplicate, fingerprint
from .utils import normalize, safe_error_message, safe_http_url
from .scheduler_service import automation_timezone
from ..models import RawJobPost, Job, JobCategory, JobProcessingLog

def log_event(raw, stage, status, message='', provider='', retry_count=0, job=None):
    return JobProcessingLog.objects.create(raw_post=raw, job=job, stage=stage, status=status, provider=provider, message=safe_error_message(message), retry_count=retry_count)

def parse_deadline(value):
    if not value:
        return None
    for fmt in ('%Y-%m-%d','%d/%m/%Y','%d-%m-%Y','%B %d, %Y','%d %B %Y'):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            pass
    return None

def process_raw(raw):
    raw.status = 'processing'
    raw.attempts += 1
    raw.last_error = ''
    raw.save(update_fields=['status','attempts','last_error'])
    try:
        data = extract_job(raw.content, log=lambda **kw: log_event(raw, 'ai', **kw, retry_count=raw.attempts))
        raw.extracted_json = data
        raw.save(update_fields=['extracted_json'])
        if not data.get('is_job'):
            raw.status, raw.rejection_reason, raw.processed_at = 'rejected', 'AI classified the content as not a job vacancy.', timezone.now()
            raw.save(update_fields=['status','rejection_reason','processed_at'])
            log_event(raw,'validate','skipped',raw.rejection_reason)
            return None
        title, company, desc = (data.get('title') or '').strip(), (data.get('company') or '').strip(), (data.get('description') or '').strip()
        if not title or not desc or not (company or data.get('location')):
            raise ValueError('Insufficient job information: title, description, and company/location are required.')
        deadline = parse_deadline(data.get('deadline'))
        local_today = timezone.localtime(timezone.now(), automation_timezone()).date()
        if deadline and deadline < local_today:
            raw.status = 'rejected'
            raw.rejection_reason = 'The application deadline has already passed.'
            raw.processed_at = timezone.now()
            raw.save(update_fields=['status', 'rejection_reason', 'processed_at'])
            log_event(raw, 'validate', 'skipped', raw.rejection_reason)
            return None
        duplicate = find_duplicate(data, raw.content)
        if duplicate:
            raw.status, raw.job, raw.processed_at = 'duplicate', duplicate, timezone.now()
            raw.save(update_fields=['status','job','processed_at'])
            log_event(raw,'dedupe','skipped','Duplicate job detected.',job=duplicate)
            return duplicate
        category_name = (data.get('category') or 'Other').strip()[:100] or 'Other'
        category, _ = JobCategory.objects.get_or_create(name=category_name)
        valid_types = {x[0] for x in Job.JOB_TYPE_CHOICES}
        jt = next((x for x in valid_types if x.lower() in (data.get('job_type') or '').lower()), 'Full-time')
        valid_exp = {x[0] for x in Job.EXP_LEVEL_CHOICES}
        exp = next((x for x in valid_exp if x.lower() in (data.get('experience') or '').lower()), 'Fresh Graduate')
        sections = []
        if data.get('requirements'): sections.append('Requirements:\n' + '\n'.join(f'• {x}' for x in data['requirements'] if x))
        if data.get('responsibilities'): sections.append('Responsibilities:\n' + '\n'.join(f'• {x}' for x in data['responsibilities'] if x))
        if data.get('education'): sections.append('Education:\n' + data['education'])
        if exp: sections.append('Experience:\n' + exp)
        if data.get('how_to_apply'): sections.append('How to Apply:\n' + data['how_to_apply'])
        full_desc = desc + ('\n\n' + '\n\n'.join(sections) if sections else '')
        app = (data.get('application_url') or '').strip()
        if not safe_http_url(app):
            app = ''
        extracted_source_url = (data.get('source_url') or '').strip()
        source_url = (
            extracted_source_url
            if safe_http_url(extracted_source_url)
            else raw.source_url if safe_http_url(raw.source_url) else ''
        )
        job = Job.objects.create(
            source=raw.source,
            title=title[:200], company_name=(company or 'Not specified')[:200], location=(data.get('location') or 'Not specified')[:100],
            job_type=jt, experience_level=exp, category=category, salary=(data.get('salary') or '')[:100], description=full_desc,
            apply_link=app, deadline=deadline, source_name=(data.get('source_name') or (raw.source.name if raw.source else ''))[:200],
            source_url=source_url[:1000], original_content=raw.content, content_hash=fingerprint(data,raw.content),
            normalized_title=normalize(title)[:220], normalized_company=normalize(company)[:220], normalized_location=normalize(data.get('location'))[:160], auto_imported=True,
              organization_type=(data.get('organization_type') or '').strip()[:80],
              education_level=(data.get('education_level') or data.get('education') or '').strip()[:80],
              employment_type=(data.get('employment_type') or data.get('job_type') or '').strip()[:50],
              work_mode=(data.get('work_mode') or '').strip()[:30],
              region=(data.get('region') or '').strip()[:100],
              country=(data.get('country') or '').strip()[:100],
              languages_required=data.get('languages_required') or [],
              keywords=data.get('keywords') or [],
              salary_min=data.get('salary_min') or None,
              salary_max=data.get('salary_max') or None,
              salary_currency=(data.get('salary_currency') or '').strip()[:10],

        )
        raw.status, raw.job, raw.processed_at = 'processed', job, timezone.now()
        raw.save(update_fields=['status','job','processed_at','last_error'])
        log_event(raw,'publish','success','Job created.',job=job)
        return job
    except Exception as exc:
        raw.status, raw.last_error = 'failed', safe_error_message(exc)
        raw.save(update_fields=['status','last_error'])
        log_event(raw,'system','failed',raw.last_error,retry_count=raw.attempts)
        return None
