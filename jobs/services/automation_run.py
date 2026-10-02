from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from ..models import AutomationControl, AutomationRun
from .utils import safe_error_message


RUN_STALE_AFTER = timedelta(hours=4)


def claim_automation_run(command='automation_cycle'):
    AutomationControl.objects.get_or_create(
        pk=1,
        defaults={'enabled': True, 'frequency_minutes': 15},
    )

    with transaction.atomic():
        control = AutomationControl.objects.select_for_update().get(pk=1)
        now = timezone.now()
        active = control.active_run

        if active:
            if active.finished_at is None and active.started_at > now - RUN_STALE_AFTER:
                return None
            if active.finished_at is None:
                active.status = 'failed'
                active.error_message = 'Automation worker lease expired before completion.'
                active.finished_at = now
                active.save(update_fields=['status', 'error_message', 'finished_at'])
            control.active_run = None

        run = AutomationRun.objects.create(command=command, status='queued')
        control.active_run = run
        control.save(update_fields=['active_run', 'updated_at'])
        return run


def finish_automation_run(run, status, error=''):
    now = timezone.now()
    run.status = status
    run.error_message = safe_error_message(error) if error else ''
    run.finished_at = now
    run.save(update_fields=['status', 'error_message', 'finished_at'])
    AutomationControl.objects.filter(active_run=run).update(
        active_run=None,
        last_error=run.error_message,
        updated_at=now,
    )
    return run
