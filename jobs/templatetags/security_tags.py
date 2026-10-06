import bleach
import re
from html import unescape
from urllib.parse import urlparse
from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe
from bleach.css_sanitizer import CSSSanitizer
from ..services.utils import repair_spaced_bullets

register = template.Library()

ALLOWED_TAGS = {
    'a', 'abbr', 'b', 'blockquote', 'br', 'code', 'em', 'i', 'li',
    'del', 'figure', 'figcaption', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ol', 'p', 'pre', 'small', 'strong', 'u', 'ul', 'div', 'span',
    'img',
}
ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title', 'rel', 'target'],
    'abbr': ['title'],
    'figure': ['class'],
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
    return mark_safe(_clean_html(value))


def _clean_html(value):
    return bleach.clean(
        value,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        css_sanitizer=CSS_SANITIZER,
        strip=True,
    )


def _repair_mojibake(value):
    repaired = []
    for token in value.split(' '):
        for _ in range(2):
            if not any(marker in token for marker in ('Ã', 'Â', 'â')):
                break
            try:
                candidate = token.encode('cp1252').decode('utf-8')
            except (UnicodeEncodeError, UnicodeDecodeError):
                break
            if sum(candidate.count(marker) for marker in ('Ã', 'Â', 'â')) >= sum(
                token.count(marker) for marker in ('Ã', 'Â', 'â')
            ):
                break
            token = candidate
        repaired.append(token)
    return ' '.join(repaired)


def _plain_job_description_html(value):
    section_names = {
        'job description',
        'responsibilities',
        'requirements',
        'education',
        'experience',
        'how to apply',
        'additional details from original post',
    }
    chunks = []
    paragraph = []
    list_items = []

    def flush_paragraph():
        if paragraph:
            chunks.append(
                '<p>' + '<br>'.join(str(escape(line)) for line in paragraph) + '</p>'
            )
            paragraph.clear()

    def flush_list():
        if list_items:
            chunks.append(
                '<ul>' + ''.join(
                    f'<li>{escape(item)}</li>' for item in list_items
                ) + '</ul>'
            )
            list_items.clear()

    for line in value.splitlines():
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            flush_list()
            continue

        heading, separator, remainder = stripped.partition(':')
        if not separator and stripped.casefold() in section_names:
            flush_paragraph()
            flush_list()
            chunks.append(f'<h5>{escape(stripped)}</h5>')
            continue
        if separator and heading.strip().casefold() in section_names:
            flush_paragraph()
            flush_list()
            chunks.append(f'<h5>{escape(heading.strip())}</h5>')
            if remainder.strip():
                paragraph.append(remainder.strip())
            continue

        bullet_match = re.match(r'^(?:•|â€¢|[-*])\s+(.+)$', stripped)
        if bullet_match:
            flush_paragraph()
            list_items.append(bullet_match.group(1).strip())
            continue

        flush_list()
        paragraph.append(stripped)

    flush_paragraph()
    flush_list()
    return ''.join(chunks)


@register.filter
def job_description(value):
    value = unescape(_repair_mojibake(str(value or '')))
    value = repair_spaced_bullets(value)
    if re.search(r'<[a-z][^>]*>', value, flags=re.IGNORECASE):
        return mark_safe(_clean_html(value))
    return mark_safe(_clean_html(_plain_job_description_html(value)))


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
