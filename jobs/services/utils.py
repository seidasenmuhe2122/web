import hashlib
import re
from urllib.parse import urljoin
from django.utils.html import strip_tags

def clean_text(value):
    value = strip_tags(value or '').replace('\r', '\n')
    value = re.sub(r'[ \t]+', ' ', value)
    value = re.sub(r'\n{3,}', '\n\n', value)
    return value.strip()

def normalize(value):
    value = clean_text(value).lower()
    value = re.sub(r'[^a-z0-9\u1200-\u137f]+', ' ', value)
    return re.sub(r'\s+', ' ', value).strip()

def sha256(value):
    return hashlib.sha256((value or '').encode('utf-8')).hexdigest()

def absolute_url(base, value):
    return urljoin(base, value) if value else ''
