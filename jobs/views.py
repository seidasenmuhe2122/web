import os
import hmac
import subprocess
import sys
from pathlib import Path

from django.views.decorators.http import require_GET
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import F, Q
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.translation import gettext as _
from urllib.parse import urlparse
from .forms import ContactMessageForm
from .models import BlogPost, Job, JobCategory, Advertisement, CustomPage, LegalPage, SiteSetting
from .services.automation_run import claim_automation_run, finish_automation_run
from .services.utils import safe_http_url


@staff_member_required
def admin_theme_config(request):
    site_settings = SiteSetting.objects.first()
    response = JsonResponse({
        'sidebar_color': site_settings.admin_sidebar_color if site_settings else '#070b16',
        'accent_color': site_settings.admin_accent_color if site_settings else '#22d3ee',
        'workspace_color': site_settings.admin_workspace_color if site_settings else '#0b1120',
        'primary_color': site_settings.admin_primary_color if site_settings else '#38bdf8',
        'secondary_color': site_settings.admin_secondary_color if site_settings else '#a855f7',
        'text_color': site_settings.admin_text_color if site_settings else '#e0f2fe',
        'background_mode': site_settings.admin_background_mode if site_settings else 'image',
        'background_image': site_settings.admin_background_image.url if site_settings and site_settings.admin_background_image else '',
        'background_video': site_settings.admin_background_video.url if site_settings and site_settings.admin_background_video else '',
        'background_3d': site_settings.admin_background_3d.url if site_settings and site_settings.admin_background_3d else '',
        'background_4k': site_settings.admin_background_4k.url if site_settings and site_settings.admin_background_4k else '',
    })
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response


def job_list(request):
    jobs = Job.objects.all()
    site_display_mode = (
        SiteSetting.objects.values_list('job_display_mode', flat=True).first()
        or 'work'
    )
    for job in jobs:
        job.effective_display_mode = (
            site_display_mode if job.display_mode == 'site' else job.display_mode
        )

    query = request.GET.get('q')
    job_type = request.GET.get('job_type')
    experience = request.GET.get('experience')
    location = request.GET.get('location')

    if query:
        jobs = jobs.filter(
            Q(title__icontains=query) |
            Q(company_name__icontains=query) |
            Q(category__name__icontains=query) |
            Q(category__slug__icontains=query)
        )
    if job_type:
        jobs = jobs.filter(job_type=job_type)
    if experience:
        jobs = jobs.filter(experience_level=experience)
    if location:
        jobs = jobs.filter(location__icontains=location)

    featured_jobs = Job.objects.filter(is_featured=True)[:5]

    context = {
        'jobs': jobs,
        'featured_jobs': featured_jobs,
        'job_types': Job.JOB_TYPE_CHOICES,
        'experience_levels': (
            Job.objects.exclude(experience_level='')
            .order_by('experience_level')
            .values_list('experience_level', flat=True)
            .distinct()
        ),
        'display_mode': site_display_mode,
    }
    return render(request, 'jobs/job_list.html', context)


def home_view(request):
    return job_list(request)


def category_list_view(request):
    categories = JobCategory.objects.all()
    return render(request, 'jobs/category_list.html', {'categories': categories})


def blog_list_view(request):
    posts = BlogPost.objects.order_by('-created_at')
    return render(request, 'jobs/blog_list.html', {'posts': posts})


def blog_detail_view(request, slug):
    post = get_object_or_404(BlogPost, slug=slug)
    return render(request, 'jobs/blog_detail.html', {'post': post})


def job_detail(request, pk):
    job = get_object_or_404(Job, pk=pk)

    Job.objects.filter(pk=job.pk).update(views_count=F('views_count') + 1)

    inside_job_ad = Advertisement.objects.filter(position='inside_job', is_active=True).first()
    after_apply_ad = Advertisement.objects.filter(position='after_apply', is_active=True).first()

    context = {
        'job': job,
        'apply_url': job.apply_link if safe_http_url(job.apply_link) else '',
        'inside_job_ad': inside_job_ad,
        'after_apply_ad': after_apply_ad,
    }
    return render(request, 'jobs/job_detail.html', context)


def advertisement_impression(request, pk):
    Advertisement.objects.filter(pk=pk, is_active=True).update(views_count=F('views_count') + 1)
    response = HttpResponse(
        b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;',
        content_type='image/gif',
    )
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response


def advertisement_click(request, pk):
    advertisement = get_object_or_404(Advertisement, pk=pk, is_active=True)
    Advertisement.objects.filter(pk=pk).update(clicks_count=F('clicks_count') + 1)
    if advertisement.destination_link:
        destination = urlparse(advertisement.destination_link)
        if destination.scheme in {'http', 'https'} and destination.hostname:
            return redirect(advertisement.destination_link)
    return redirect('job_list')


def legal_page(request, page_type):
    page = get_object_or_404(LegalPage, page_type=page_type)
    form = None
    show_message_form = False
    if page_type == 'contact':
        if not page.contact_enabled:
            return render(request, 'jobs/contact_disabled.html', {'page': page})
        if request.method == 'POST':
            form = ContactMessageForm(request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, _('Thank you. Your message has been received by our Kombolcha team.'))
                return redirect('contact_us')
        else:
            form = ContactMessageForm()

    template_name = 'jobs/contact.html' if page_type == 'contact' else 'jobs/legal_page.html'
    return render(
        request,
        template_name,
        {'page': page, 'form': form, 'show_message_form': show_message_form},
    )


def contact_message(request):
    page = get_object_or_404(LegalPage, page_type='contact')
    if not page.contact_enabled:
        return render(request, 'jobs/contact_disabled.html', {'page': page})
    if request.method == 'POST':
        form = ContactMessageForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _('Thank you. Your message has been received by our Kombolcha team.'))
            return redirect('contact_message')
    else:
        form = ContactMessageForm()
    return render(
        request,
        'jobs/contact.html',
        {'page': page, 'form': form, 'show_message_form': True},
    )


def custom_page(request, slug):
    page = CustomPage.objects.filter(slug=slug).first()
    if page is not None:
        return render(request, 'jobs/custom_page.html', {'page': page})

    legacy_page = get_object_or_404(LegalPage, page_type=slug)
    return render(request, 'jobs/legal_page.html', {'page': legacy_page, 'form': None})

@require_GET
def automation_trigger(request):
    secret = os.environ.get('AUTOMATION_SECRET', '')
    provided_secret = request.headers.get('X-Automation-Secret') or request.GET.get('key', '')

    if not secret or not hmac.compare_digest(
        provided_secret.encode('utf-8'),
        secret.encode('utf-8'),
    ):
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    run = claim_automation_run()
    if run is None:
        return JsonResponse(
            {'status': 'already_running', 'message': 'An automation cycle is already active.'},
            status=409,
        )

    log_path = Path(os.environ.get(
        'AUTOMATION_LOG_FILE',
        settings.BASE_DIR / 'logs' / f'automation-{timezone.localdate().isoformat()}.log',
    ))
    if not log_path.is_absolute():
        log_path = settings.BASE_DIR / log_path
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open('a', encoding='utf-8') as worker_log:
            subprocess.Popen(
                [
                    sys.executable,
                    str(settings.BASE_DIR / 'manage.py'),
                    'automation_cycle',
                    '--run-id',
                    str(run.pk),
                ],
                cwd=str(settings.BASE_DIR),
                stdin=subprocess.DEVNULL,
                stdout=worker_log,
                stderr=subprocess.STDOUT,
                close_fds=True,
            )
    except Exception as exc:
        finish_automation_run(run, 'failed', exc)
        return JsonResponse(
            {'status': 'failed', 'message': 'Automation worker could not be started.'},
            status=503,
        )

    return JsonResponse({
        'status': 'started',
        'run_id': run.pk,
        'message': 'AFRIJOB automation cycle started',
    })