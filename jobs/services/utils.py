import hashlib
import os
import re
from html import escape, unescape
from urllib.parse import urljoin
from urllib.parse import urlsplit
from django.utils.html import strip_tags


def clean_text(value):
    value = strip_tags(value or '').replace('\r', '\n')
    value = re.sub(r'[ \t]+', ' ', value)
    value = re.sub(r'\n{3,}', '\n\n', value)
    return value.strip()


SOURCE_PROMOTION_MARKERS = (
    r'\bjoin\b.{0,80}\b(?:telegram|our channel|the channel)\b',
    r'\b(?:telegram jobs channel|please join our telegram channel)\b',
    r'\b(?:get|receive)\s+(?:the\s+)?(?:latest|daily)\s+jobs?\b',
    r'\bfollow\b.{0,60}\b(?:on\s+)?telegram\b',
    r'\b(?:related posts|more jobs|share this job|search jobs|no results)\b',
    r'^\s*tags\s*:?\s*$',
)
SOURCE_PROMOTION_RE = re.compile(
    '|'.join(f'(?:{marker})' for marker in SOURCE_PROMOTION_MARKERS),
    re.IGNORECASE,
)


def strip_source_promotions(value):
    """Drop unrelated source-site marketing and related-job content after job facts."""
    if not value:
        return ''

    kept_lines = []
    for line in str(value).replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        marker = SOURCE_PROMOTION_RE.search(line)
        if marker:
            prefix = line[:marker.start()].strip(' \t-–—:|')
            prefix = re.sub(
                r'<(?:p|li|ul|ol|div|h[1-6])\b[^>]*>\s*$',
                '',
                prefix,
                flags=re.IGNORECASE,
            )
            if prefix:
                kept_lines.append(prefix)
            break
        kept_lines.append(line)

    cleaned = '\n'.join(kept_lines)
    cleaned = re.sub(r'[ \t]+\n', '\n', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


def public_telegram_url(channel_id):
    channel_id = str(channel_id or '').strip()
    match = re.fullmatch(r'@?([A-Za-z0-9_]{5,})', channel_id)
    if not match:
        return ''
    return f'https://t.me/{match.group(1)}'


def _join_character_tokens(tokens):
    if len(tokens) < 12 or not all(
        len(token) == 1 and re.fullmatch(r'[A-Za-z0-9.,;:!?+\-/–—\s]', token)
        for token in tokens
    ):
        return None

    words = []
    current = ''
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.isalnum():
            current += token
        elif token.isspace():
            if current:
                words.append(current)
                current = ''
        elif token == '.':
            if re.fullmatch(r'[A-Z](?:\.[A-Za-z]{1,2})?', current):
                current += token
            else:
                if index + 1 < len(tokens) and tokens[index + 1] == '.':
                    if re.fullmatch(r'[A-Z](?:\.[A-Za-z]){1,3}', current):
                        current += '.'
                    if current:
                        words.append(current)
                        current = ''
                    while index + 1 < len(tokens) and tokens[index + 1] == '.':
                        index += 1
                elif current:
                    words.append(current)
                    current = ''
        elif token == ',':
            if current:
                words.append(current + ',')
                current = ''
        elif token in {'-', '+', '/', '–', '—'}:
            current += token
        else:
            if current:
                words.append(current)
                current = ''
        index += 1

    if current:
        words.append(current.rstrip('.,;:!?'))
    text = ' '.join(word for word in words if word)
    if len(text.split()) < 3:
        return None

    return text


def _repair_character_list(match):
    items = re.findall(r'<li\b[^>]*>(.*?)</li\s*>', match.group('items'), re.I | re.S)
    tokens = []
    for item in items:
        token = unescape(strip_tags(item))
        tokens.append(token if token.isspace() else token.strip())
    text = _join_character_tokens(tokens)
    if text is None:
        return match.group(0)

    return f'<ul><li>{escape(text)}</li></ul>'


def _repair_character_lines(value):
    lines = value.splitlines()
    repaired = []
    candidate_tokens = []
    candidate_lines = []

    def flush_candidate():
        if not candidate_tokens:
            return
        text = _join_character_tokens(candidate_tokens)
        repaired.extend([f'• {text}'] if text is not None else candidate_lines)
        candidate_tokens.clear()
        candidate_lines.clear()

    for line in lines:
        match = re.fullmatch(r'\s*[•·�]\s*(.*?)\s*', line)
        token = match.group(1) if match else ''
        if match and (not token or len(token) == 1):
            candidate_tokens.append(token or ' ')
            candidate_lines.append(line)
        else:
            flush_candidate()
            repaired.append(line)

    flush_candidate()
    return '\n'.join(repaired)


def repair_spaced_bullets(value):
    value = re.sub(
        r'<ul\b[^>]*>(?P<items>(?:\s*<li\b[^>]*>.*?</li\s*>)+\s*)</ul\s*>',
        _repair_character_list,
        value or '',
        flags=re.I | re.S,
    )
    parts = re.split(r'(<[^>]+>)', value)

    for index, part in enumerate(parts):
        if part.startswith('<') and part.endswith('>'):
            continue

        lines = []
        for line in part.splitlines(keepends=True):
            ending = line[len(line.rstrip('\r\n')):]
            content = line[:-len(ending)] if ending else line
            prefix_match = re.match(r'^(\s*[•·]\s+)', content)
            prefix = prefix_match.group(1) if prefix_match else ''
            content = content[len(prefix):]

            separators = re.findall(r'(?<=\w)\s*[•·]\s*(?=\w)', content)
            single_characters = re.findall(r'(?<!\w)[A-Za-z0-9](?!\w)', content)
            if len(separators) >= 8 and len(single_characters) >= 12:
                content = re.sub(r'(?<=\w)\s*[•·]\s*(?=\w)', '', content)
                content = re.sub(r'(?:\s*[•·])+\s*', ' ', content)

            lines.append(prefix + content + ending)

        if lines:
            parts[index] = ''.join(lines)

    return _repair_character_lines(''.join(parts))


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
