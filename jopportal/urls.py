from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls.i18n import i18n_patterns
from django.views.i18n import set_language as django_set_language
from django.utils.translation import check_for_language
from jobs import views as job_views


LANGUAGE_CODES = {code for code, _ in settings.LANGUAGES}


def _strip_locale_prefix(path):
    if not path or path == '/':
        return '/'

    normalized = path.rstrip('/') or '/'
    if normalized == '/':
        return '/'

    pieces = normalized.split('/')
    if len(pieces) > 1 and pieces[1] in LANGUAGE_CODES:
        if len(pieces) == 2:
            return '/'
        return '/' + '/'.join(pieces[2:])
    return normalized if normalized.startswith('/') else '/' + normalized


def _build_language_redirect(path, language):
    if not path:
        return '/'

    raw_path, sep, query = path.partition('?')
    raw_path = raw_path or '/'

    if raw_path.startswith(f'/{language}') or raw_path.startswith(f'/{language}/'):
        target = raw_path.rstrip('/') or f'/{language}'
        if raw_path.endswith('/') and not target.endswith('/'):
            target = f'{target}/'
        if sep:
            target = f'{target}?{query}'
        return target

    if raw_path.startswith('/admin'):
        admin_path = raw_path.rstrip('/') or '/admin'
        pieces = admin_path.split('/')
        if len(pieces) > 2 and pieces[1] in LANGUAGE_CODES:
            admin_path = '/' + '/'.join(pieces[2:]) if len(pieces) > 2 else '/admin'
        if not admin_path.startswith('/admin'):
            admin_path = '/admin' + ('' if admin_path == '/' else admin_path)
        if language == settings.LANGUAGE_CODE:
            target = '/admin/' if admin_path in {'/admin', '/admin/'} else admin_path
        else:
            if admin_path in {'/admin', '/admin/'}:
                target = f'/{language}/admin/'
            elif admin_path.startswith('/admin'):
                target = f'/{language}{admin_path}'
            else:
                target = f'/{language}/admin{admin_path}'
        if target == '/admin':
            target = '/admin/'
    else:
        normalized = _strip_locale_prefix(raw_path)
        if language == settings.LANGUAGE_CODE:
            target = normalized
            if raw_path.endswith('/') and target != '/' and not target.endswith('/'):
                target = f'{target}/'
        else:
            target = f'/{language}{normalized}' if normalized != '/' else f'/{language}/'
            if raw_path.endswith('/') and not target.endswith('/'):
                target = f'{target}/'

    if not target.startswith('/'):
        target = '/' + target
    if sep:
        target = f'{target}?{query}'
    return target


def set_language_with_prefix(request):
    response = django_set_language(request)
    language = request.POST.get('language')
    next_url = request.POST.get('next')

    if language and next_url and check_for_language(language):
        response['Location'] = _build_language_redirect(next_url, language)

    return response


urlpatterns = [
    path('ckeditor/', include('ckeditor_uploader.urls')),
    path('i18n/setlang/', set_language_with_prefix, name='set_language'),
]

urlpatterns += i18n_patterns(
    path('admin/theme-config/', job_views.admin_theme_config, name='admin_theme_config'),
    path('admin/', admin.site.urls),
    path('', include('jobs.urls')),
    prefix_default_language=False,
)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)