import os
import hmac
import json
import logging
import subprocess
import sys
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, register_namespace, tostring

from django.views.decorators.http import require_GET
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F, Q
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.utils.html import strip_tags
from django.utils import timezone
from django.utils.translation import gettext as _, override
from urllib.parse import urlparse
from .forms import ContactMessageForm
from .models import (
    BlogPost,
    Job,
    JobCategory,
    Advertisement,
    CustomPage,
    LegalPage,
    PaginationStyle,
    SiteSetting,
    JobViewDaily,
    CustomPage,
)
from .services.automation_run import claim_automation_run, finish_automation_run
from .services.utils import safe_http_url


logger = logging.getLogger(__name__)


def _paginated_items(request, queryset, page_name):
    configuration = PaginationStyle.objects.filter(
        page=page_name,
        is_active=True,
    ).first()
    if configuration is None:
        return {'items': queryset}

    paginator = Paginator(queryset, configuration.items_per_page)
    page_obj = paginator.get_page(request.GET.get('page'))
    query_params = request.GET.copy()
    query_params.pop('page', None)
    page_number = page_obj.number
    visible_page_numbers = range(
        max(1, page_number - 2),
        min(paginator.num_pages, page_number + 2) + 1,
    )
    return {
        'items': page_obj.object_list,
        'page_obj': page_obj,
        'pagination_style': configuration.style,
        'pagination_query': query_params.urlencode(),
        'pagination_page_numbers': visible_page_numbers,
    }


def _job_view_is_recent(request, job_id, now, interval):
    recent_views = request.session.get('job_detail_views', {})
    if not isinstance(recent_views, dict):
        return False, {}

    cutoff = now.timestamp() - interval
    recent_views = {
        key: viewed_at
        for key, viewed_at in recent_views.items()
        if isinstance(viewed_at, (int, float)) and viewed_at > cutoff
    }
    previous_view = recent_views.get(str(job_id))
    return previous_view is not None, recent_views


def _record_job_view(request, job):
    user_agent = request.headers.get('User-Agent', '').lower()
    automated_agents = (
        'bot', 'crawler', 'spider', 'preview', 'facebookexternalhit',
        'slackbot', 'whatsapp', 'telegrambot', 'linkedinbot', 'discordbot',
        'twitterbot',
    )
    request_purpose = ' '.join((
        request.headers.get('Purpose', ''),
        request.headers.get('Sec-Purpose', ''),
    )).lower()
    if (
        request.method != 'GET'
        or any(agent in user_agent for agent in automated_agents)
        or any(purpose in request_purpose for purpose in ('prefetch', 'prerender'))
        or request.GET.get('preview', '').lower() in {'1', 'true', 'yes'}
    ):
        return

    try:
        interval = max(0, int(getattr(settings, 'JOB_VIEW_COUNT_INTERVAL_SECONDS', 1800)))
        now = timezone.now()
        already_counted, recent_views = _job_view_is_recent(request, job.pk, now, interval)
        if already_counted:
            return

        with transaction.atomic():
            Job.objects.filter(pk=job.pk).update(views_count=F('views_count') + 1)
            daily_view, _ = JobViewDaily.objects.get_or_create(
                job_id=job.pk,
                view_date=timezone.localdate(now),
            )
            JobViewDaily.objects.filter(pk=daily_view.pk).update(
                views_count=F('views_count') + 1,
            )

        recent_views[str(job.pk)] = now.timestamp()
        request.session['job_detail_views'] = recent_views
    except Exception:
        logger.exception('Unable to record detail view for job %s', job.pk)


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

    route = getattr(request.resolver_match, 'route', '')
    page_name = 'home' if route in ('', 'home/') else 'jobs'
    pagination_context = _paginated_items(request, jobs, page_name)
    jobs = pagination_context.pop('items')
    for job in jobs:
        job.effective_display_mode = (
            site_display_mode if job.display_mode == 'site' else job.display_mode
        )

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
        'seo_page_name': page_name,
    }
    context.update(pagination_context)
    return render(request, 'jobs/job_list.html', context)


def home_view(request):
    return job_list(request)


def category_list_view(request):
    categories = JobCategory.objects.all()
    return render(request, 'jobs/category_list.html', {'categories': categories})


def blog_list_view(request):
    posts = BlogPost.objects.order_by('-created_at')
    pagination_context = _paginated_items(request, posts, 'blog')
    posts = pagination_context.pop('items')
    context = {'posts': posts, **pagination_context}
    return render(request, 'jobs/blog_list.html', context)


def blog_detail_view(request, slug):
    post = get_object_or_404(BlogPost, slug=slug)
    return render(request, 'jobs/blog_detail.html', {'post': post})


def job_detail(request, pk):
    job = get_object_or_404(Job, pk=pk)

    inside_job_ad = Advertisement.objects.filter(position='inside_job', is_active=True).first()
    after_apply_ad = Advertisement.objects.filter(position='after_apply', is_active=True).first()

    context = {
        'job': job,
        'apply_url': job.apply_link if safe_http_url(job.apply_link) else '',
        'inside_job_ad': inside_job_ad,
        'after_apply_ad': after_apply_ad,
    }
    employment_types = {
        'Full-time': 'FULL_TIME',
        'Part-time': 'PART_TIME',
        'Contract': 'CONTRACTOR',
        'Internship': 'INTERN',
    }
    if (
        job.title
        and job.company_name
        and job.location
        and job.country
        and job.deadline
        and job.deadline >= timezone.localdate()
        and strip_tags(job.translated_description).strip()
        and job.job_type in employment_types
    ):
        job_posting = {
            '@context': 'https://schema.org',
            '@type': 'JobPosting',
            'title': job.title,
            'description': strip_tags(job.translated_description).strip(),
            'datePosted': job.posted_date.isoformat(),
            'validThrough': job.deadline.isoformat(),
            'employmentType': employment_types[job.job_type],
            'hiringOrganization': {
                '@type': 'Organization',
                'name': job.company_name,
            },
            'jobLocation': {
                '@type': 'Place',
                'address': {
                    '@type': 'PostalAddress',
                    'addressLocality': job.location,
                    'addressCountry': job.country,
                },
            },
            'url': f'https://afrijob.world/job/{job.pk}/',
        }
        context['job_structured_data'] = json.dumps(
            job_posting,
            ensure_ascii=False,
        ).replace('<', '\\u003c')
    response = render(request, 'jobs/job_detail.html', context)
    _record_job_view(request, job)
    return response


@require_GET
def robots_txt(request):
    admin_path = f'/{settings.ADMIN_URL.strip("/")}/'
    language_admin_paths = ''.join(
        f'Disallow: /{language}{admin_path}\n'
        for language, _ in settings.LANGUAGES
    )
    return HttpResponse(
        'User-agent: *\n'
        'Allow: /\n'
        'Allow: /static/\n'
        f'Disallow: {admin_path}\n'
        f'{language_admin_paths}'
        'Sitemap: https://afrijob.world/sitemap.xml\n',
        content_type='text/plain; charset=utf-8',
    )


@require_GET
def sitemap_xml(request):
    namespace = 'http://www.sitemaps.org/schemas/sitemap/0.9'
    register_namespace('', namespace)
    urlset = Element(f'{{{namespace}}}urlset')
    today = timezone.localdate()

    with override(settings.LANGUAGE_CODE):
        public_urls = [
            reverse('canonical_home'),
            reverse('job_list'),
            reverse('category_list'),
            reverse('blog_list'),
        ]
        legal_pages = list(LegalPage.objects.order_by('page_type'))
        static_legal_routes = {
            'about': 'about_us',
            'contact': 'contact_us',
            'privacy': 'privacy_policy',
            'terms': 'terms_and_conditions',
        }
        public_urls.extend(
            reverse(static_legal_routes[page.page_type])
            for page in legal_pages
            if page.page_type in static_legal_routes
        )
        public_urls.extend(
            reverse('custom_page', args=[page.page_type])
            for page in legal_pages
            if page.page_type not in static_legal_routes
        )
        custom_pages = CustomPage.objects.order_by('slug')
        public_urls.extend(
            reverse('custom_page', args=[page.slug])
            for page in custom_pages
        )
        entries = [(path, None) for path in public_urls]
        entries.extend(
            (
                reverse('job_detail', args=[job.pk]),
                job.posted_date.date(),
            )
            for job in Job.objects.filter(
                Q(deadline__isnull=True) | Q(deadline__gte=today)
            ).order_by('pk')
        )
        entries.extend(
            (
                reverse('blog_detail', args=[post.slug]),
                post.updated_at.date(),
            )
            for post in BlogPost.objects.filter(
                is_published=True,
            ).order_by('slug')
        )

    for path, last_modified in entries:
        url_element = SubElement(urlset, f'{{{namespace}}}url')
        SubElement(url_element, f'{{{namespace}}}loc').text = (
            f'https://afrijob.world{path}'
        )
        if last_modified:
            SubElement(url_element, f'{{{namespace}}}lastmod').text = (
                last_modified.isoformat()
            )

    return HttpResponse(
        tostring(urlset, encoding='utf-8', xml_declaration=True),
        content_type='application/xml; charset=utf-8',
    )


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