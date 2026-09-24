import hashlib
import logging
import re

from django.conf import settings
from django.core.cache import cache
from django.dispatch import receiver
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.signals import user_logged_in, user_login_failed


logger = logging.getLogger(__name__)


def _request_client_identity(request):
    if request is None:
        return 'unknown'
    address = request.META.get('REMOTE_ADDR') or 'unknown'
    if getattr(settings, 'RATE_LIMIT_TRUST_X_FORWARDED_FOR', False):
        forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
        if forwarded_for:
            address = forwarded_for.split(',')[0].strip() or address
    return address


def _auth_cache_key(prefix, request):
    digest = hashlib.sha256(_request_client_identity(request).encode('utf-8')).hexdigest()
    return f'ratelimit:auth:{prefix}:{digest}'


@receiver(user_login_failed)
def record_failed_login(sender, credentials, request, **kwargs):
    key = _auth_cache_key('failures', request)
    try:
        if cache.add(key, 1, timeout=settings.AUTH_LOGIN_FAILURE_WINDOW):
            failures = 1
        else:
            failures = cache.incr(key)
        if failures >= settings.AUTH_LOGIN_FAILURE_LIMIT:
            cache.set(
                _auth_cache_key('blocked', request),
                True,
                timeout=settings.AUTH_LOGIN_BLOCK_DURATION,
            )
    except Exception:
        logger.warning('Authentication failure tracking unavailable', exc_info=True)


@receiver(user_logged_in)
def clear_failed_logins(sender, request, user, **kwargs):
    try:
        cache.delete(_auth_cache_key('failures', request))
        cache.delete(_auth_cache_key('blocked', request))
    except Exception:
        logger.warning('Authentication failure reset unavailable', exc_info=True)


class RateLimitMiddleware:
    """Apply cache-backed limits to endpoints that are expensive or state-changing."""

    _DEFAULT_LIMITS = {
        'admin_login': (10, 300),
        'contact': (5, 600),
        'search': (60, 60),
        'api': (60, 60),
        'upload': (20, 60),
        'account': (10, 300),
    }
    _SEARCH_PARAMETERS = frozenset({'q', 'job_type', 'experience', 'location'})
    _ACCOUNT_PATH = re.compile(r'^/(?:[^/]+/)?(?:register|signup|password-reset)(?:/|$)')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        category = self._category(request)
        if category:
            if category == 'admin_login' and self._auth_blocked(request):
                return self._too_many_requests(request, settings.AUTH_LOGIN_BLOCK_DURATION)
            limit, window = self._limit_for(category)
            if limit > 0 and self._is_limited(request, category, limit, window):
                return self._too_many_requests(request, window)
        return self.get_response(request)

    def _category(self, request):
        path = request.path_info.rstrip('/') or '/'
        method = request.method.upper()

        admin_login_path = f'/{settings.ADMIN_URL.strip("/")}/login'
        localized_admin_login_paths = {
            admin_login_path,
            *(f'/{code}{admin_login_path}' for code in settings.LANGUAGES),
        }
        if path in localized_admin_login_paths and method == 'POST':
            return 'admin_login'
        if path in {'/contact-us', '/contact-us/message'} and method == 'POST':
            return 'contact'
        if path.startswith('/ckeditor/upload') and method == 'POST':
            return 'upload'
        if '/api/' in f'{path}/' or path.startswith('/api'):
            return 'api'
        if self._ACCOUNT_PATH.match(path) and method in {'POST', 'PUT', 'PATCH'}:
            return 'account'
        if path in {'/', '/home', '/jobs'} and method == 'GET':
            if self._SEARCH_PARAMETERS.intersection(request.GET):
                return 'search'
        return None

    def _limit_for(self, category):
        configured = getattr(settings, 'RATE_LIMITS', {}).get(category, {})
        defaults = self._DEFAULT_LIMITS[category]
        return (
            max(0, int(configured.get('limit', defaults[0]))),
            max(1, int(configured.get('window', defaults[1]))),
        )

    def _client_identity(self, request):
        return _request_client_identity(request)

    def _auth_blocked(self, request):
        try:
            return bool(cache.get(_auth_cache_key('blocked', request)))
        except Exception:
            logger.warning('Authentication block lookup unavailable', exc_info=True)
            return False

    def _cache_key(self, request, category):
        identity = f'{category}:{self._client_identity(request)}'
        digest = hashlib.sha256(identity.encode('utf-8')).hexdigest()
        return f'ratelimit:{category}:{digest}'

    def _is_limited(self, request, category, limit, window):
        key = self._cache_key(request, category)
        try:
            if cache.add(key, 1, timeout=window):
                return False
            return cache.incr(key) > limit
        except Exception:
            # Availability takes precedence if a production cache is unavailable.
            logger.warning('Rate-limit cache unavailable; allowing request', exc_info=True)
            return False

    def _too_many_requests(self, request, window):
        response = (
            JsonResponse({'detail': 'Too many requests. Please try again later.'}, status=429)
            if request.path_info.startswith('/api') or '/api/' in request.path_info
            else HttpResponse('Too many requests. Please try again later.', status=429)
        )
        response['Retry-After'] = str(window)
        response['Cache-Control'] = 'no-store'
        return response


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault('Content-Security-Policy', settings.CONTENT_SECURITY_POLICY)
        response.setdefault('X-XSS-Protection', '1; mode=block')
        return response