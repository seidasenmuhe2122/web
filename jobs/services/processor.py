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

requirements = data.get('requirements') or []
if isinstance(requirements, str):
    requirements = [requirements]

if requirements:
    sections.append(
        'Requirements:\n' +
        '\n'.join(
            f'• {str(x).strip()}'
            for x in requirements
            if str(x).strip()
        )
    )

responsibilities = data.get('responsibilities') or []
if isinstance(responsibilities, str):
    responsibilities = [responsibilities]

if responsibilities:
    sections.append(
        'Responsibilities:\n' +
        '\n'.join(
            f'• {str(x).strip()}'
            for x in responsibilities
            if str(x).strip()
        )
    )

education = data.get('education') or ''
if education:
    if isinstance(education, str):
        education_text = education.strip()
    else:
        education_text = '\n'.join(
            str(x).strip()
            for x in education
            if str(x).strip()
        )

    if education_text:
        sections.append('Education:\n' + education_text)

if exp:
    sections.append('Experience:\n' + str(exp).strip())

how_to_apply = data.get('how_to_apply') or ''
if how_to_apply:
    if isinstance(how_to_apply, str):
        how_to_apply_text = how_to_apply.strip()
    else:
        how_to_apply_text = '\n'.join(
            str(x).strip()
            for x in how_to_apply
            if str(x).strip()
        )

    if how_to_apply_text:
        sections.append('How to Apply:\n' + how_to_apply_text)

full_desc = desc + ('\n\n' + '\n\n'.join(sections) if sections else '')

app = (data.get('application_url') or '').strip()
if not safe_http_url(app):
    app = ''

extracted_source_url = (data.get('source_url') or '').strip()

source_url = (
    extracted_source_url
    if safe_http_url(extracted_source_url)
    else raw.source_url
    if safe_http_url(raw.source_url)
    else ''
)

job = Job.objects.create(
    source=raw.source,
    title=title[:200],
    company_name=(company or '')[:200],
    location=(data.get('location') or '')[:200],
    job_type=jt,
    experience_level=exp,
    category=category,
    salary=(data.get('salary') or '')[:200],
    description=full_desc,
    apply_link=app,
    deadline=deadline,
    source_name=(data.get('source_name') or raw.source_name or '')[:200],
    source_url=source_url,
    original_content=raw.content,
    content_hash=fingerprint(data, raw.content),
    normalized_title=normalize(title),
    normalized_company=normalize(company),
    normalized_location=normalize(data.get('location') or ''),
    auto_imported=True,
    organization_type=(data.get('organization_type') or '')[:100],
    education_level=(data.get('education_level') or '')[:100],
    employment_type=(data.get('employment_type') or '')[:100],
    work_mode=(data.get('work_mode') or '')[:100],
    region=(data.get('region') or '')[:100],
    country=(data.get('country') or '')[:100],
    languages_required=data.get('languages_required') or [],
    keywords=data.get('keywords') or [],
    salary_min=data.get('salary_min') or None,
    salary_max=data.get('salary_max') or None,
    salary_currency=(data.get('salary_currency') or '')[:20],
)