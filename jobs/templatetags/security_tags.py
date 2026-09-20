import bleach
from html import unescape
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
