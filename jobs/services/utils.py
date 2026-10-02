import hashlib
import os
import re
from urllib.parse import urljoin
from urllib.parse import urlsplit
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

def safe_error_message(error, limit=2000):
    message = str(error or error.__class__.__name__)
    for name in (
        'AUTOMATION_SECRET',
        'DATABASE_URL',
        'DJANGO_SECRET_KEY',
        'DJANGO_EMAIL_HOST_PASSWORD',
        'TELEGRAM_BOT_TOKEN',
        'TELEGRAM_API_HASH',
        'TELEGRAM_SESSION_STRING',
        'GEMINI_API_KEY',
        'GROQ_API_KEY',
        'OPENROUTER_API_KEY',
        'OPENAI_API_KEY',
    ):
        secret = os.getenv(name, '').strip()
        if secret:
            message = message.replace(secret, '[redacted]')
    message = re.sub(r'bot\d+:[A-Za-z0-9_-]+', '[redacted]', message)
    message = re.sub(r'(?i)(://[^:/\s]+:)[^@/\s]+(@)', r'\1[redacted]\2', message)
    message = re.sub(r'(?i)(bearer\s+)[^\s,;]+', r'\1[redacted]', message)
    message = re.sub(
        r'(?i)((?:api[_-]?key|token|secret|password)=)[^&\s]+',
        r'\1[redacted]',
        message,
    )
    return message[:limit]

def absolute_url(base, value):
    return urljoin(base, value) if value else ''

def safe_http_url(value):
    parsed = urlsplit(value or '')
    return parsed.scheme in {'http', 'https'} and bool(parsed.hostname) and not parsed.username and not parsed.password
