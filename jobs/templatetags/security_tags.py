import bleach
import re
from html import unescape
from urllib.parse import urlparse
from django import template
from django.utils.safestring import mark_safe
from bleach.css_sanitizer import CSSSanitizer

register = template.Library()

ALLOWED_TAGS = {
    'a', 'abbr', 'b', 'blockquote', 'br', 'code', 'em', 'i', 'li',
    'del', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ol', 'p', 'pre', 'small', 'strong', 'u', 'ul', 'div', 'span',
    'img',
}
ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title', 'rel', 'target'],
    'abbr': ['title'],
    'img': ['src', 'alt', 'width', 'height', 'style'],
    'span': ['style'],
}
ALLOWED_PROTOCOLS = {'http', 'https', 'mailto'}
CSS_SANITIZER = CSSSanitizer(allowed_css_properties={
    'color', 'background-color', 'font-size', 'max-width', 'width', 'height', 'display', 'margin', 'padding'
})
AD_CODE_TAGS = {'div', 'ins', 'script', 'span', 'strong', 'p'}
AD_CODE_PROTOCOLS = {'https'}
AD_SCRIPT_HOSTS = {'pagead2.googlesyndication.com', 'googleads.g.doubleclick.net'}


def _ad_code_attribute_allowed(tag, name, value):
    if tag == 'script':
        if name in {'async', 'defer'}:
            return True
        if name == 'src':
            parsed = urlparse(value)
            return parsed.scheme == 'https' and parsed.hostname in AD_SCRIPT_HOSTS
        return False
    if tag == 'ins':
        return name in {
            'class', 'style', 'data-ad-client', 'data-ad-slot',
            'data-ad-format', 'data-full-width-responsive',
        }
    return name == 'class'


@register.filter
def sanitize_html(value):
    value = unescape(value or '')
    cleaned = bleach.clean(
        value,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        css_sanitizer=CSS_SANITIZER,
        strip=True,
    )
    return mark_safe(cleaned)


@register.filter
def sanitize_ad_code(value):
    cleaned = bleach.clean(
        unescape(value or ''),
        tags=AD_CODE_TAGS,
        attributes=_ad_code_attribute_allowed,
        protocols=AD_CODE_PROTOCOLS,
        strip=True,
    )
    # Empty or inline script bodies are never valid for the supported AdSense form.
    cleaned = re.sub(r'<script\b(?![^>]*\bsrc\s*=)[^>]*>.*?</script\s*>', '', cleaned, flags=re.I | re.S)
    return mark_safe(cleaned)
