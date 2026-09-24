from django.db.models import Count, Q
from django.conf import settings
from django.templatetags.i18n import GetAvailableLanguagesNode
from django.utils import translation

from .models import Advertisement, CustomPage, Job, LegalPage, SiteSetting


ADMIN_LANGUAGES = (
    ('en', 'English'),
    ('am', 'አማርኛ'),
    ('ar', 'العربية'),
)

FRONTEND_LANGUAGES = (
    ('en', 'English'),
    ('am', 'አማርኛ'),
    ('aa', 'Afaraf'),
    ('ar', 'العربية'),
    ('es', 'Español'),
    ('fr', 'Français'),
    ('om', 'Afaan Oromoo'),
)

_original_language_render = GetAvailableLanguagesNode.render


def _admin_aware_language_render(node, context):
    request = context.get('request')
    path = getattr(request, 'path_info', '')
    admin_path = f'/{settings.ADMIN_URL.strip("/")}'
    localized_admin_paths = (admin_path, *(f'/{code}{admin_path}' for code in ('am', 'ar')))
    if any(path == admin_prefix or path.startswith(f'{admin_prefix}/') for admin_prefix in localized_admin_paths):
        context[node.variable] = [
            (code, translation.gettext(name)) for code, name in ADMIN_LANGUAGES
        ]
        return ''
    return _original_language_render(node, context)


GetAvailableLanguagesNode.render = _admin_aware_language_render


def admin_language_context(request):
    return {'ADMIN_LANGUAGES': ADMIN_LANGUAGES, 'frontend_languages': FRONTEND_LANGUAGES}


def _page_context():
    custom_pages = list(CustomPage.objects.all())
    legal_pages = list(LegalPage.objects.exclude(page_type__in=('privacy', 'about', 'contact', 'terms')))
    return {
        'custom_header_pages': [page for page in custom_pages if page.placement_location == 'header'],
        'custom_footer_pages': [page for page in custom_pages if page.placement_location == 'footer'],
        'custom_main_body_pages': [page for page in custom_pages if page.placement_location == 'main_body'],
        'custom_left_top_pages': [page for page in custom_pages if page.placement_location == 'left_top'],
        'custom_left_middle_pages': [page for page in custom_pages if page.placement_location == 'left_middle'],
        'custom_left_bottom_pages': [page for page in custom_pages if page.placement_location == 'left_bottom'],
        'custom_right_top_pages': [page for page in custom_pages if page.placement_location == 'right_top'],
        'custom_right_middle_pages': [page for page in custom_pages if page.placement_location == 'right_middle'],
        'custom_right_bottom_pages': [page for page in custom_pages if page.placement_location == 'right_bottom'],
        'legal_header_pages': [page for page in legal_pages if page.placement_location == 'header'],
        'legal_footer_pages': [page for page in legal_pages if page.placement_location == 'footer'],
        'legal_main_body_pages': [page for page in legal_pages if page.placement_location == 'main_body'],
        'legal_left_top_pages': [page for page in legal_pages if page.placement_location == 'left_top'],
        'legal_left_middle_pages': [page for page in legal_pages if page.placement_location == 'left_middle'],
        'legal_left_bottom_pages': [page for page in legal_pages if page.placement_location == 'left_bottom'],
        'legal_right_top_pages': [page for page in legal_pages if page.placement_location == 'right_top'],
        'legal_right_middle_pages': [page for page in legal_pages if page.placement_location == 'right_middle'],
        'legal_right_bottom_pages': [page for page in legal_pages if page.placement_location == 'right_bottom'],
    }


def global_context(request):
    site_settings = SiteSetting.objects.first()
    contact_page = LegalPage.objects.filter(page_type='contact').first()
    advertisements = list(Advertisement.objects.filter(is_active=True).order_by('id'))
    placement_slots = (
        'header',
        'sidebar',
        'footer',
        'right_top',
        'right_middle',
        'right_bottom',
        'left_top',
        'left_middle',
        'left_bottom',
    )
    advertisements_by_position = {
        ad.position: ad for ad in advertisements if ad.position != 'auto'
    }
    available_slots = [
        slot for slot in placement_slots if slot not in advertisements_by_position
    ]
    for ad, slot in zip(
        (ad for ad in advertisements if ad.position == 'auto'),
        available_slots,
    ):
        advertisements_by_position[slot] = ad
    all_advertisements = list(Advertisement.objects.all())
    ad_views = sum(ad.views_count for ad in all_advertisements)
    ad_clicks = sum(ad.clicks_count for ad in all_advertisements)
    job_stats = Job.objects.aggregate(
        jobs=Count('id'),
        featured_jobs=Count('id', filter=Q(is_featured=True)),
        urgent_jobs=Count('id', filter=Q(is_urgent=True)),
    )
    context = {
        'site_settings': site_settings,
        'display_mode': site_settings.job_display_mode if site_settings else 'work',
        'contact_page': contact_page,
        'frontend_languages': FRONTEND_LANGUAGES,
        'header_ad': advertisements_by_position.get('header'),
        'sidebar_ad': advertisements_by_position.get('sidebar'),
        'footer_ad': advertisements_by_position.get('footer'),
        'right_top_ad': advertisements_by_position.get('right_top'),
        'right_middle_ad': advertisements_by_position.get('right_middle'),
        'right_bottom_ad': advertisements_by_position.get('right_bottom'),
        'left_top_ad': advertisements_by_position.get('left_top'),
        'left_middle_ad': advertisements_by_position.get('left_middle'),
        'left_bottom_ad': advertisements_by_position.get('left_bottom'),
        'admin_dashboard_stats': {
            'jobs': job_stats['jobs'],
            'featured_jobs': job_stats['featured_jobs'],
            'urgent_jobs': job_stats['urgent_jobs'],
            'advertisements': len(all_advertisements),
            'active_advertisements': len(advertisements),
            'ad_views': ad_views,
            'ad_clicks': ad_clicks,
            'ad_ctr': (ad_clicks / ad_views * 100) if ad_views else 0,
            'top_advertisements': sorted(
                all_advertisements,
                key=lambda ad: (ad.views_count, ad.clicks_count),
                reverse=True,
            )[:5],
        },
    }
    context.update(_page_context())
    return context