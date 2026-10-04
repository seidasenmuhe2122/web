import re
from html import escape
from datetime import datetime
from django.utils import timezone
from .ai_service import AIProvidersUnavailable, extract_job
from .dedupe_service import find_duplicate, fingerprint
from .utils import clean_text, normalize, safe_error_message, safe_http_url
from .scheduler_service import automation_timezone
from ..models import RawJobPost, Job, JobCategory, JobProcessingLog


def _text_items(value):
    if value is None or isinstance(value, dict):
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    items = []
    seen = set()
    for item in values:
        if item is None or isinstance(item, (dict, list, tuple, set)):
            continue
        text = str(item).replace('\r\n', '\n').replace('\r', '\n')
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text).strip()
        key = normalize(text)
        if text and key not in seen:
            items.append(text)
            seen.add(key)
    return items


def _escape_text(value):
    return escape(value)


def _first_text(value):
    items = _text_items(value)
    return items[0] if items else ''


def _paragraphs_html(value):
    paragraphs = re.split(r'\n\s*\n', value.strip())
    return ''.join(
        f'<p>{_escape_text(paragraph).replace(chr(10), "<br>")}</p>'
        for paragraph in paragraphs
        if paragraph.strip()
    )


def _section_html(title, value, as_list=False):
    items = _text_items(value)
    if not items:
        return ''
    if as_list:
        body = '<ul>' + ''.join(f'<li>{_escape_text(item)}</li>' for item in items) + '</ul>'
    else:
        body = ''.join(_paragraphs_html(item) for item in items)
    return f'<h5>{escape(title)}</h5>{body}'


def _application_html(instructions, contacts):
    if not instructions and not contacts:
        return ''
    body = ''.join(_paragraphs_html(item) for item in instructions)
    if contacts:
        body += '<ul>' + ''.join(
            f'<li><strong>{escape(label)}:</strong> {_escape_text(value)}</li>'
            for label, value in contacts
        ) + '</ul>'
    return f'<h5>How to Apply</h5>{body}'


def _original_application_instructions(value):
    text = clean_text(value)
    if not text:
        return []
    chunks = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
    application_cue = re.compile(
        r'\b(apply|application|send|submit|email|e-mail|cv|resume|telegram|'
        r'phone|call|contact|interested candidates|address)\b|'
        r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|@\w+',
        re.IGNORECASE,
    )
    return [chunk.strip() for chunk in chunks if application_cue.search(chunk)]


def _instruction_contacts(instructions):
    text = ' '.join(instructions)
    contacts = []
    patterns = (
        ('Email', r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}'),
        ('Telegram', r'(?<![\w/])@\w{3,}|(?:https?://)?t\.me/[\w]+'),
        ('Phone', r'(?<!\w)\+?\d[\d\s().-]{6,}\d'),
    )
    for label, pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            value = match.strip()
            if label != 'Phone' or sum(char.isdigit() for char in value) >= 7:
                contacts.append((label, value))
    return contacts


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
        if not isinstance(data, dict):
            raise ValueError('AI extraction did not return an object.')
        raw.extracted_json = data
        raw.save(update_fields=['extracted_json'])
        if not data.get('is_job'):
            raw.status, raw.rejection_reason, raw.processed_at = 'rejected', 'AI classified the content as not a job vacancy.', timezone.now()
            raw.save(update_fields=['status','rejection_reason','processed_at'])
            log_event(raw,'validate','skipped',raw.rejection_reason)
            return None
        title = _first_text(data.get('title'))
        company = _first_text(data.get('company'))
        location = _first_text(data.get('location'))
        desc = _first_text(data.get('description')) or clean_text(raw.content)
        if not title or not desc or not (company or location):
            raise ValueError('Insufficient job information: title, description, and company/location are required.')
        deadline = parse_deadline(_first_text(data.get('deadline')))
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
        category_name = _first_text(data.get('category')) or 'Other'
        category_name = category_name[:100] or 'Other'
        category, _ = JobCategory.objects.get_or_create(name=category_name)
        valid_types = {x[0] for x in Job.JOB_TYPE_CHOICES}
        job_type_text = ' '.join(_text_items(data.get('job_type'))).lower()
        jt = next((x for x in valid_types if x.lower() in job_type_text), 'Full-time')
        experience_text = _first_text(data.get('experience'))
        exp = experience_text[:200]
        requirements = _text_items(data.get('requirements'))
        responsibilities = _text_items(data.get('responsibilities'))
        education = _text_items(data.get('education'))
        education.extend(
            item for item in _text_items(data.get('education_level'))
            if normalize(item) not in {normalize(value) for value in education}
        )
        experience = [experience_text] if experience_text else []
        how_to_apply = _text_items(data.get('how_to_apply'))
        if not how_to_apply:
            how_to_apply = _original_application_instructions(raw.content)

        contacts = []
        for label, field in (
            ('Email', 'contact_email'),
            ('Phone', 'contact_phone'),
            ('Telegram', 'contact_telegram'),
        ):
            for value in _text_items(data.get(field)):
                if not any(normalize(value) in normalize(item) for item in how_to_apply):
                    contacts.append((label, value))
        for label, value in _instruction_contacts(how_to_apply):
            if not any(normalize(value) == normalize(existing) for _, existing in contacts):
                contacts.append((label, value))

        description = desc
        sections = [
            _section_html('Job Description', description),
            _section_html('Responsibilities', responsibilities, as_list=True),
            _section_html('Requirements', requirements, as_list=True),
            _section_html('Education', education),
            _section_html('Experience', experience),
            _application_html(how_to_apply, contacts),
        ]

        known_lines = {
            normalize(line)
            for value in (
                [description]
                + requirements
                + responsibilities
                + education
                + experience
                + how_to_apply
                + [value for _, value in contacts]
            )
            for line in value.splitlines()
            if normalize(line)
        }
        original_details = []
        source_chunks = re.split(
            r'(?<=[.!?])\s+(?=[A-Z])|\n+',
            clean_text(raw.content),
        )
        for line in source_chunks:
            line = clean_text(line)
            key = normalize(line)
            if line and key not in known_lines:
                original_details.append(line)
                known_lines.add(key)
        sections.append(
            _section_html('Additional Details from Original Post', original_details)
        )
        full_desc = ''.join(section for section in sections if section)

        app = data.get('application_url')
        app = app.strip() if isinstance(app, str) else ''
        if not safe_http_url(app):
            app = ''

        extracted_source_url = data.get('source_url')
        extracted_source_url = (
            extracted_source_url.strip()
            if isinstance(extracted_source_url, str)
            else ''
        )

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
            location=location[:200],
            job_type=jt,
            experience_level=exp,
            category=category,
            salary=_first_text(data.get('salary'))[:200],
            description=full_desc,
            apply_link=app,
            deadline=deadline,
            source_name=(_first_text(data.get('source_name')) or (raw.source.name if raw.source else '') or '')[:200],
            source_url=source_url,
            original_content=raw.content,
            content_hash=fingerprint(data, raw.content),
            normalized_title=normalize(title),
            normalized_company=normalize(company),
            normalized_location=normalize(location),
            auto_imported=True,
            organization_type=_first_text(data.get('organization_type'))[:100],
            education_level=_first_text(data.get('education_level'))[:100],
            employment_type=_first_text(data.get('employment_type'))[:100],
            work_mode=_first_text(data.get('work_mode'))[:100],
            region=_first_text(data.get('region'))[:100],
            country=_first_text(data.get('country'))[:100],
            languages_required=_text_items(data.get('languages_required')),
            keywords=_text_items(data.get('keywords')),
            salary_min=data.get('salary_min') or None,
            salary_max=data.get('salary_max') or None,
            salary_currency=(data.get('salary_currency') or '')[:20],
        )
        raw.status, raw.job, raw.processed_at = 'processed', job, timezone.now()
        raw.save(update_fields=['status', 'job', 'processed_at', 'last_error'])
        log_event(raw, 'publish', 'success', 'Job created.', job=job)
        return job
    except AIProvidersUnavailable as exc:
        raw.status, raw.last_error = 'new', safe_error_message(exc)
        raw.save(update_fields=['status', 'last_error'])
        log_event(raw, 'system', 'failed', raw.last_error, retry_count=raw.attempts)
        return None
    except Exception as exc:
        raw.status, raw.last_error = 'failed', safe_error_message(exc)
        raw.save(update_fields=['status', 'last_error'])
        log_event(raw, 'system', 'failed', raw.last_error, retry_count=raw.attempts)
        return None
