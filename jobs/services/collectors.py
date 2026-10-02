import asyncio
import ipaddress
import logging
import os
import socket
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from .utils import clean_text, absolute_url, safe_error_message, safe_http_url, sha256
from ..models import RawJobPost


logger = logging.getLogger(__name__)


def save_raw(source, content, external_id='', source_url=''):
    content = clean_text(content)

    if not content:
        return None

    h = sha256(content)

    defaults = {
        'source_url': source_url,
        'content': content,
        'content_hash': h,
        'status': 'new',
    }

    obj, created = RawJobPost.objects.get_or_create(
        source=source,
        external_id=str(external_id or h[:24]),
        defaults=defaults,
    )

    if (
        not created
        and obj.content_hash != h
        and obj.status in {'failed', 'new'}
    ):
        obj.content = content
        obj.content_hash = h
        obj.source_url = source_url
        obj.status = 'new'

        obj.save(
            update_fields=[
                'content',
                'content_hash',
                'source_url',
                'status',
            ]
        )

    return obj if created else None


def collect_website(config):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36'
    }
    headers.update(config.headers_json or {})

    def is_internal(url):
        from urllib.parse import urlparse

        base = urlparse(config.url)
        target = urlparse(url)

        return (
            target.scheme in {'http', 'https'}
            and target.netloc == base.netloc
        )

    def looks_like_job_url(url, text=''):
        from urllib.parse import urlparse

        parsed = urlparse(url)
        path = parsed.path.lower()
        combined = f'{path} {text.lower()}'

        blocked = (
    '/about',
    '/contact',
    '/privacy',
    '/terms',
    '/category/',
    '/tag/',
    '/author/',
    '/page/',
    '/search',
    '/feed',
    '/jobs/new',
)

        if any(x in path for x in blocked):
            return False

        keywords = (
            'job',
            'jobs',
            'vacancy',
            'vacancies',
            'career',
            'careers',
            'position',
            'employment',
            'recruit',
        )

        return any(word in combined for word in keywords)

    def fetch(url):
        current_url = url
        request_headers = dict(headers)
        for _ in range(6):
            if not safe_http_url(current_url):
                raise ValueError('Website URL must use HTTP or HTTPS without embedded credentials.')

            parsed = urlsplit(current_url)
            try:
                address = ipaddress.ip_address(parsed.hostname)
                addresses = [address]
            except ValueError:
                records = socket.getaddrinfo(
                    parsed.hostname,
                    parsed.port or (443 if parsed.scheme == 'https' else 80),
                    type=socket.SOCK_STREAM,
                )
                addresses = list({ipaddress.ip_address(record[4][0]) for record in records})

            if not addresses or any(not address.is_global for address in addresses):
                raise ValueError('Website URL resolves to a non-public network address.')

            response = requests.get(
                current_url,
                headers=request_headers,
                timeout=config.timeout_seconds,
                allow_redirects=False,
            )
            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get('Location')
                response.close()
                if not location:
                    raise ValueError('Website redirected without a Location header.')
                next_url = urljoin(current_url, location)
                if urlsplit(next_url).netloc.lower() != parsed.netloc.lower():
                    request_headers = {
                        key: value for key, value in request_headers.items()
                        if key.lower() not in {'authorization', 'cookie'}
                    }
                current_url = next_url
                continue
            response.raise_for_status()
            return response

        raise ValueError('Website exceeded the maximum redirect count.')

    # ---------------------------------------------------------
    # 1. Open the configured source/listing page
    # ---------------------------------------------------------
    response = fetch(config.url)

    soup = BeautifulSoup(
        response.text,
        'html.parser',
    )

    # ---------------------------------------------------------
    # 2. Find possible job-detail links
    # ---------------------------------------------------------
    links = []

    for a in soup.find_all('a', href=True):
        href = a.get('href', '').strip()

        if not href:
            continue

        url = absolute_url(config.url, href)

        if not is_internal(url):
            continue

        text = clean_text(
            a.get_text(
                ' ',
                strip=True,
            )
        )

        if looks_like_job_url(url, text):
            links.append((url, text))

    # Remove duplicates while preserving order
    unique_links = []
    seen = set()

    for url, text in links:
        if url in seen:
            continue

        seen.add(url)
        unique_links.append((url, text))

    unique_links = unique_links[:config.max_items_per_run]

    out = []

    # ---------------------------------------------------------
    # 3. Visit each possible job-detail page
    # ---------------------------------------------------------
    for url, link_text in unique_links:
        try:
            detail_response = fetch(url)

            detail_soup = BeautifulSoup(
                detail_response.text,
                'html.parser',
            )

            # Remove navigation / irrelevant page elements
            for tag in detail_soup([
                'script',
                'style',
                'nav',
                'footer',
                'header',
                'noscript',
            ]):
                tag.decompose()

            content = clean_text(
                detail_soup.get_text(
                    '\n',
                    strip=True,
                )
            )

            if not content:
                continue

            # -------------------------------------------------
            # 4. Basic protection against non-job pages
            # -------------------------------------------------
            job_words = (
                'job',
                'vacancy',
                'vacancies',
                'position',
                'application',
                'applicants',
                'qualification',
                'requirements',
                'experience',
                'education',
                'deadline',
                'how to apply',
                'salary',
            )

            matched_words = sum(
                1
                for word in job_words
                if word in content.lower()
            )

            if matched_words < 2:
                continue

            # -------------------------------------------------
            # 5. Save the actual job-detail page
            # -------------------------------------------------
            raw = save_raw(
                config.source,
                content,
                external_id=url,
                source_url=url,
            )

            if raw:
                out.append(raw)

        except requests.RequestException as exc:
            logger.warning(
                'Website detail fetch failed for host %s: %s',
                urlsplit(url).hostname,
                safe_error_message(exc),
            )
            continue
        except Exception as exc:
            logger.warning(
                'Website detail processing failed for host %s: %s',
                urlsplit(url).hostname,
                safe_error_message(exc),
            )
            continue

    return out

def collect_telegram(config):
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    api_id = int(
        os.getenv(
            'TELEGRAM_API_ID',
            '0',
        )
    )

    api_hash = os.getenv(
        'TELEGRAM_API_HASH',
        '',
    ).strip()

    session = os.getenv(
        'TELEGRAM_SESSION_STRING',
        '',
    ).strip()

    if not api_id or not api_hash or not session:
        raise RuntimeError(
            'TELEGRAM_API_ID, TELEGRAM_API_HASH '
            'and TELEGRAM_SESSION_STRING are required'
        )

    client = TelegramClient(
        StringSession(session),
        api_id,
        api_hash,
    )

    async def run():
        await client.start()

        try:
            entity = await client.get_entity(
                config.channel
            )

            out = []

            # First run:
            # establish the current latest message as the
            # starting point. Do NOT import old messages.
            if config.last_message_id <= 0:

                latest_messages = []

                async for msg in client.iter_messages(
                    entity,
                    limit=1,
                ):
                    latest_messages.append(msg)
                    config.last_message_id = (
                        latest_messages[0].id
                    )

                    config.save(
                        update_fields=[
                            'last_message_id'
                        ]
                    )

                return out

            max_id = config.last_message_id

            async for msg in client.iter_messages(
                entity,
                limit=config.max_messages_per_run,
                min_id=config.last_message_id,
            ):
                text = msg.message or ''

                if not text:
                    continue

                channel = str(
                    config.channel
                ).lstrip('@')

                if channel.lstrip('-').isdigit():
                    source_url = ''
                else:
                    source_url = (
                        f'https://t.me/{channel}/{msg.id}'
                    )

                raw = save_raw(
                    config.source,
                    text,
                    external_id=msg.id,
                    source_url=source_url,
                )

                if raw:
                    out.append(raw)

                max_id = max(
                    max_id,
                    msg.id,
                )

            if max_id != config.last_message_id:
                config.last_message_id = max_id

                config.save(
                    update_fields=[
                        'last_message_id'
                    ]
                )

            return out

        finally:
            await client.disconnect()

    return asyncio.run(run())

