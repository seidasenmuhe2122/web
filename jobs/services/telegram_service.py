import os
import requests

from django.urls import reverse
from django.utils import timezone

from ..models import TelegramDestination, TelegramNotification


def public_job_url(job, request=None):
    path = reverse('job_detail', args=[job.pk])
    if request:
        return request.build_absolute_uri(path)

    return os.getenv(
        'PUBLIC_BASE_URL',
        'https://afrijob.world'
    ).rstrip('/') + path


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

    text = (
        f'🚨 New Job Opportunity\n\n'
        f'💼 Position: {job.title}\n'
        f'🏢 Company: {job.company_name}\n'
        f'📍 Location: {job.location}\n\n'
        f'👉 Apply / View Details: {public_job_url(job)}'
    )

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