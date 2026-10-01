import os
import re

import requests
from django.urls import reverse
from django.utils import timezone

from ..models import TelegramDestination, TelegramNotification


def public_job_url(job, request=None):
    path = reverse('job_detail', args=[job.pk])

    if request:
        return request.build_absolute_uri(path)

    return (
        os.getenv(
            'PUBLIC_BASE_URL',
            'https://afrijob.world'
        ).rstrip('/')
        + path
    )


def destination_allows_job(destination, job):
    allowed_sources = destination.allowed_sources.all()

    if not allowed_sources.exists():
        return True

    if not job.source_id:
        return False

    return allowed_sources.filter(
        pk=job.source_id
    ).exists()


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
    token = os.getenv(
        'TELEGRAM_BOT_TOKEN',
        ''
    ).strip()

    if not token:
        raise RuntimeError(
            'TELEGRAM_BOT_TOKEN is required'
        )

    chat = destination.channel_id.strip()

    if not chat:
        raise RuntimeError(
            f'Telegram destination "{destination.name}" has no channel ID'
        )

    # Prevent duplicate Telegram posts.
    existing = TelegramNotification.objects.filter(
        job=job,
        destination=destination,
        status='sent',
    ).first()

    if existing:
        return existing

    summary = _telegram_summary(
        job.description,
        limit=650
    )

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
        lines.extend([
            '📝 Summary:',
            summary,
            '',
        ])

    if job.deadline:
        deadline = job.deadline.strftime('%B %d, %Y')
        lines.extend([
            f'⏰ Deadline: {deadline}',
            '',
        ])

    lines.extend([
        '👉 Full Details & Apply:',
        public_job_url(job),
    ])

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
        raise RuntimeError(
            data.get(
                'description',
                'Telegram API error'
            )
        )

    message = data['result']

    notification, _ = TelegramNotification.objects.get_or_create(
        job=job,
        destination=destination,
    )

    notification.channel_id = chat
    notification.message_id = message.get('message_id')
    notification.message_text = text
    notification.status = 'sent'
    notification.sent_at = timezone.now()
    notification.last_error = ''
    notification.attempts += 1
    notification.save()

    return notification


def send_job(job):
    destinations = get_job_destinations(job)

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

    if notifications:
        job.telegram_notification_sent_at = timezone.now()
        job.save(
            update_fields=[
                'telegram_notification_sent_at'
            ]
        )

    if errors and not notifications:
        raise RuntimeError(
            'All Telegram destinations failed: '
            + '; '.join(errors)
        )

    return notifications