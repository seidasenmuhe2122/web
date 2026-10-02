import os
import re
from datetime import timedelta

import requests
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone

from ..models import TelegramDestination, TelegramNotification
from .utils import safe_error_message


def public_job_url(job, request=None):
    path = reverse('job_detail', args=[job.pk])

    if request:
        return request.build_absolute_uri(path)

    return (
        os.getenv(
            'PUBLIC_BASE_URL',
            'https://www.afrijob.world'
        ).rstrip('/')
        + path
    )


def destination_allows_job(destination, job):
    # Source-level filtering
    allowed_sources = destination.allowed_sources.all()
    if allowed_sources.exists():
        if not job.source_id:
            return False
        if not allowed_sources.filter(pk=job.source_id).exists():
            return False

    # Advanced destination filters
    filters = destination.filters_json or {}

    def values(key):
        value = filters.get(key, [])
        if isinstance(value, str):
            return [value.strip().lower()] if value.strip() else []
        if isinstance(value, list):
            return [str(x).strip().lower() for x in value if str(x).strip()]
        return []

    def matches(field_value, key):
        wanted = values(key)
        if not wanted:
            return True
        actual = str(field_value or '').strip().lower()
        return bool(actual) and any(
            item == actual or item in actual or actual in item
            for item in wanted
        )

    def matches_any_list(field_values, key):
        wanted = values(key)
        if not wanted:
            return True
        actual_values = [
            str(x).strip().lower()
            for x in (field_values or [])
            if str(x).strip()
        ]
        return any(
            wanted_item == actual_item
            or wanted_item in actual_item
            or actual_item in wanted_item
            for wanted_item in wanted
            for actual_item in actual_values
        )

    # Single-value filters
    if not matches(job.organization_type, 'organization_type'):
        return False

    if not matches(job.education_level, 'education_level'):
        return False

    if not matches(job.employment_type, 'employment_type'):
        return False

    if not matches(job.work_mode, 'work_mode'):
        return False

    if not matches(job.region, 'region'):
        return False

    if not matches(job.country, 'country'):
        return False

    if not matches(job.experience_level, 'experience'):
        return False

    if not matches(
        job.category.name if job.category else '',
        'category'
    ):
        return False

    # Languages
    if not matches_any_list(job.languages_required, 'languages'):
        return False

    # Required keywords: at least one selected keyword must appear
    keyword_filters = values('keywords')
    if keyword_filters:
        job_text = ' '.join([
            str(job.title or ''),
            str(job.company_name or ''),
            str(job.description or ''),
            str(job.category.name if job.category else ''),
            ' '.join(str(x) for x in (job.keywords or [])),
        ]).lower()

        if not any(keyword in job_text for keyword in keyword_filters):
            return False

    # Excluded keywords: any match blocks the destination
    excluded = values('excluded_keywords')
    if excluded:
        job_text = ' '.join([
            str(job.title or ''),
            str(job.company_name or ''),
            str(job.description or ''),
            ' '.join(str(x) for x in (job.keywords or [])),
        ]).lower()

        if any(keyword in job_text for keyword in excluded):
            return False

    # Salary minimum / maximum filters
    min_salary = filters.get('salary_min')
    max_salary = filters.get('salary_max')

    try:
        if min_salary is not None and job.salary_max is not None:
            if float(job.salary_max) < float(min_salary):
                return False
        if max_salary is not None and job.salary_min is not None:
            if float(job.salary_min) > float(max_salary):
                return False
    except (TypeError, ValueError):
        pass

    return True

def get_job_destinations(job):
    destinations = TelegramDestination.objects.filter(
        enabled=True
    )

    if job.telegram_destination_mode == 'selected':
        destinations = destinations.filter(
            pk__in=job.telegram_destinations.values('pk')
        )

    return [
        destination
        for destination in destinations
        if destination_allows_job(destination, job)
    ]


def _telegram_summary(text, limit=650):
    """
    Create a medium-length Telegram summary.
    The full description remains available on the website.
    """
    text = re.sub(r'\s+', ' ', text or '').strip()

    if not text:
        return ''

    if len(text) <= limit:
        return text

    shortened = text[:limit]

    # Prefer ending at a sentence boundary.
    sentence_end = max(
        shortened.rfind('. '),
        shortened.rfind('! '),
        shortened.rfind('? ')
    )

    if sentence_end >= int(limit * 0.6):
        shortened = shortened[:sentence_end + 1]
    else:
        shortened = shortened.rsplit(' ', 1)[0]

    return shortened + '…'


def send_job_to_destination(job, destination):
    chat = destination.channel_id.strip()

    # Prevent duplicate Telegram posts.
    existing = TelegramNotification.objects.filter(
        job=job,
        destination=destination,
        status='sent',
    ).first()

    if existing:
        return existing

    notification, _ = TelegramNotification.objects.get_or_create(
        job=job,
        destination=destination,
        defaults={'channel_id': chat},
    )
    now = timezone.now()
    claimed = TelegramNotification.objects.filter(pk=notification.pk).filter(
        Q(status__in=['pending', 'failed'])
        | Q(status='sending', last_attempt_at__lt=now - timedelta(minutes=5))
    ).update(
        channel_id=chat,
        attempts=F('attempts') + 1,
        status='sending',
        last_error='',
        last_attempt_at=now,
    )
    notification.refresh_from_db()
    if not claimed:
        if notification.status == 'sent':
            return notification
        raise RuntimeError('Telegram destination notification is already in progress.')

    try:
        token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
        if not token:
            raise RuntimeError('TELEGRAM_BOT_TOKEN is required')
        if not chat:
            raise RuntimeError(f'Telegram destination "{destination.name}" has no channel ID')

        summary = _telegram_summary(job.description, limit=650)

        job_type = (
            job.get_job_type_display()
            if hasattr(job, 'get_job_type_display')
            else job.job_type
        )

        experience = (
            job.get_experience_level_display()
            if hasattr(job, 'get_experience_level_display')
            else job.experience_level
        )

        salary = (
            job.salary.strip()
            if job.salary and job.salary.strip()
            else 'Not specified'
        )

        lines = [
            '🚨 NEW JOB OPPORTUNITY',
            '',
            f'💼 Position: {job.title}',
            f'🏢 Company: {job.company_name}',
            f'📍 Location: {job.location}',
            f'🕐 Job Type: {job_type}',
            f'🎓 Experience: {experience}',
            f'💰 Salary: {salary}',
            '',
        ]

        if summary:
            lines.extend(['📝 Summary:', summary, ''])

        if job.deadline:
            deadline = job.deadline.strftime('%B %d, %Y')
            lines.extend([f'⏰ Deadline: {deadline}', ''])

        lines.extend(['👉 Full Details & Apply:', public_job_url(job)])

        text = '\n'.join(lines)

        response = requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={
                'chat_id': chat,
                'text': text,
                'disable_web_page_preview': False,
            },
            timeout=30,
        )

        response.raise_for_status()

        data = response.json()
        if not data.get('ok'):
            raise RuntimeError(data.get('description', 'Telegram API error'))

        message = data['result']

        notification.message_id = message.get('message_id')
        notification.message_text = text
        notification.status = 'sent'
        notification.sent_at = timezone.now()
        notification.last_error = ''
        notification.save(update_fields=[
            'message_id', 'message_text', 'status', 'sent_at', 'last_error',
        ])

        return notification
    except Exception as exc:
        notification.status = 'failed'
        notification.last_error = safe_error_message(exc)
        notification.save(update_fields=['status', 'last_error'])
        raise RuntimeError(notification.last_error)



def send_job(job, destinations=None):
    if destinations is None:
        destinations = get_job_destinations(job)
    else:
        destinations = [
            destination
            for destination in destinations
            if destination.enabled and destination_allows_job(destination, job)
        ]
    if not destinations:
        raise RuntimeError(
            f'No enabled Telegram destination is allowed for job {job.pk}.'
        )

    notifications = []
    errors = []

    for destination in destinations:
        try:
            notification = send_job_to_destination(
                job,
                destination
            )
            notifications.append(notification)

        except Exception as exc:
            errors.append(
                f'{destination.name}: {exc}'
            )

    if errors:
        raise RuntimeError(
            'Telegram delivery incomplete: '
            + '; '.join(errors)
        )

    if notifications:
        job.telegram_notification_sent_at = timezone.now()
        job.save(
            update_fields=[
                'telegram_notification_sent_at'
            ]
        )

    return notifications


