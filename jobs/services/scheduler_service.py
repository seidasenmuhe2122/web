from datetime import datetime, time, timedelta

from django.utils import timezone

from ..models import AutomationSchedule, TelegramNotification


def get_active_schedule(now=None):
    now = now or timezone.now()
    local_now = timezone.localtime(now)
    current_time = local_now.time()
    weekday = local_now.weekday()

    schedules = AutomationSchedule.objects.filter(
        enabled=True
    ).order_by('start_time', 'name')

    for schedule in schedules:
        days = schedule.days_of_week or []

        if days and weekday not in [int(day) for day in days]:
            continue

        start = schedule.start_time
        end = schedule.end_time

        if start <= end:
            active = start <= current_time <= end
        else:
            active = current_time >= start or current_time <= end

        if active:
            return schedule

    return None


def get_schedule_window(schedule, now=None):
    now = now or timezone.now()
    local_now = timezone.localtime(now)

    start = schedule.start_time
    end = schedule.end_time
    current_date = local_now.date()

    if start <= end:
        start_dt = timezone.make_aware(
            datetime.combine(current_date, start),
            timezone.get_current_timezone(),
        )
        end_dt = timezone.make_aware(
            datetime.combine(current_date, end),
            timezone.get_current_timezone(),
        )
    else:
        if local_now.time() >= start:
            start_date = current_date
            end_date = current_date + timedelta(days=1)
        else:
            start_date = current_date - timedelta(days=1)
            end_date = current_date

        start_dt = timezone.make_aware(
            datetime.combine(start_date, start),
            timezone.get_current_timezone(),
        )
        end_dt = timezone.make_aware(
            datetime.combine(end_date, end),
            timezone.get_current_timezone(),
        )

    return start_dt, end_dt


def get_schedule_published_count(schedule, now=None):
    start_dt, end_dt = get_schedule_window(schedule, now)

    notifications = TelegramNotification.objects.filter(
        status='sent',
        sent_at__gte=start_dt,
        sent_at__lte=end_dt,
    )

    if schedule.destinations.exists():
        notifications = notifications.filter(
            destination__in=schedule.destinations.all()
        )

    return notifications.values('job_id').distinct().count()


def schedule_allows_job(schedule, job):
    filters = schedule.filters_json or {}

    def values(key):
        value = filters.get(key, [])

        if isinstance(value, str):
            return [value.strip().lower()] if value.strip() else []

        if isinstance(value, list):
            return [
                str(item).strip().lower()
                for item in value
                if str(item).strip()
            ]

        return []

    def matches(actual_value, key):
        wanted = values(key)

        if not wanted:
            return True

        actual = str(actual_value or '').strip().lower()

        return bool(actual) and any(
            item == actual
            or item in actual
            or actual in item
            for item in wanted
        )

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

    category_name = job.category.name if job.category else ''

    if not matches(category_name, 'category'):
        return False

    wanted_keywords = values('keywords')
    excluded_keywords = values('excluded_keywords')

    job_text = ' '.join([
        str(job.title or ''),
        str(job.company_name or ''),
        str(job.description or ''),
        str(job.country or ''),
        str(job.region or ''),
        str(job.category.name if job.category else ''),
        ' '.join(str(x) for x in (job.keywords or [])),
    ]).lower()

    if wanted_keywords:
        if not any(keyword in job_text for keyword in wanted_keywords):
            return False

    if excluded_keywords:
        if any(keyword in job_text for keyword in excluded_keywords):
            return False

    wanted_languages = values('languages')

    if wanted_languages:
        actual_languages = [
            str(item).strip().lower()
            for item in (job.languages_required or [])
        ]

        if not any(
            wanted in actual
            or actual in wanted
            for wanted in wanted_languages
            for actual in actual_languages
        ):
            return False

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
