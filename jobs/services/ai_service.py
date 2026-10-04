import json
import os
import time
import requests

from .utils import clean_text, safe_error_message


DEFAULT_GEMINI_MODEL = 'gemini-3.8-flash'

NULLABLE_NUMBER = {
    'anyOf': [
        {'type': 'number'},
        {'type': 'null'},
    ]
}

SCHEMA = {
    'type': 'object',
    'properties': {
        'is_job': {'type': 'boolean'},
        'title': {'type': 'string'},
        'company': {'type': 'string'},
        'location': {'type': 'string'},
        'job_type': {'type': 'string'},
        'organization_type': {'type': 'string'},
        'education_level': {'type': 'string'},
        'employment_type': {'type': 'string'},
        'work_mode': {'type': 'string'},
        'region': {'type': 'string'},
        'country': {'type': 'string'},
        'languages_required': {
            'type': 'array',
            'items': {'type': 'string'}
        },
        'keywords': {
            'type': 'array',
            'items': {'type': 'string'}
        },
        'salary_min': NULLABLE_NUMBER,
        'salary_max': NULLABLE_NUMBER,
        'salary_currency': {'type': 'string'},

        'category': {'type': 'string'},
        'salary': {'type': 'string'},
        'deadline': {'type': 'string'},
        'description': {'type': 'string'},
        'requirements': {
            'type': 'array',
            'items': {'type': 'string'}
        },
        'responsibilities': {
            'type': 'array',
            'items': {'type': 'string'}
        },
        'education': {'type': 'string'},
        'experience': {'type': 'string'},
        'how_to_apply': {'type': 'string'},
        'application_url': {'type': 'string'},
        'contact_email': {'type': 'string'},
        'contact_phone': {'type': 'string'},
        'source_name': {'type': 'string'},
        'source_url': {'type': 'string'},
    },
    'required': [
        'is_job',
        'title',
        'company',
        'location',
        'job_type',
        'organization_type',
        'education_level',
        'employment_type',
        'work_mode',
        'region',
        'country',
        'languages_required',
        'keywords',
        'salary_min',
        'salary_max',
        'salary_currency',

        'category',
        'salary',
        'deadline',
        'description',
        'requirements',
        'responsibilities',
        'education',
        'experience',
        'how_to_apply',
        'application_url',
        'contact_email',
        'contact_phone',
        'source_name',
        'source_url',
    ],
}


PROMPT = """You are a strict job-vacancy extraction engine for AFRIJOB Ethiopia.

Return ONLY JSON matching the supplied schema.

Never invent, infer, or fabricate facts. If the content is not a genuine job vacancy, set is_job=false and keep all other fields empty.

APPLICATION RULES:
1. If the source contains a real application URL, extract the exact application URL into application_url.
2. Do NOT use a company homepage, vacancy information page, source page, Telegram post URL, or general website URL as application_url unless the source clearly states that applicants should apply through that exact URL.
3. If there is no application URL but the source provides an application method such as email, phone number, Telegram contact, office address, physical submission location, or other contact instruction, preserve it exactly in how_to_apply.
4. Never lose application contact information. Extract contact_email, contact_phone and Telegram contact details when explicitly provided.
5. If applicants are instructed to contact someone, send a CV by email, call a phone number, message Telegram, or submit documents at an address, treat that as the application method.
6. Do not invent an application link when none exists.

DESCRIPTION RULES:
Create a detailed, professional and well-explained job description using ALL useful facts explicitly present in the source.
Do not make the description unnecessarily short.
Include the purpose of the position, organization information, duties, responsibilities, qualifications, requirements, education, experience, employment type, location, salary, deadline and application instructions whenever those facts are available.
Do not invent information that is not stated in the source.

Clean promotional text, emojis, repeated hashtags and tracking text, but do not remove useful job facts.

Classify organization type only when explicitly supported by the source:
NGO, Private Company, Government, International Organization, UN / Development Organization, or Other.

Classify education, employment type, experience, work mode, region and country only from stated facts.

For missing or unclear values, return an empty string. Never infer.

Extract languages explicitly required and useful job keywords when present.

Salary_min and salary_max must be numeric only when actual numeric salary amounts are stated; otherwise return null.
salary_currency should be the stated currency code/name only.

Extract title, company, location/remote, type, category, salary, deadline, detailed description, requirements, responsibilities, education, experience, how_to_apply, application URL, email, phone, source name and source URL.

Preserve exact application URLs and contact information from the source.

Use empty strings or empty lists when missing.

Source content:
"""


def _gemini_request(model, text):
    key = os.getenv('GEMINI_API_KEY', '').strip()

    if not key:
        raise RuntimeError('GEMINI_API_KEY is not configured')

    url = (
        'https://generativelanguage.googleapis.com/'
        f'v1beta/models/{model}:generateContent'
    )

    body = {
        'contents': [
            {
                'parts': [
                    {
                        'text': PROMPT + clean_text(text)
                    }
                ]
            }
        ],
        'generationConfig': {
            'responseMimeType': 'application/json',
            'responseJsonSchema': SCHEMA,
        },
    }

    response = requests.post(
        url,
        headers={
            'Content-Type': 'application/json',
            'x-goog-api-key': key,
        },
        json=body,
        timeout=60,
    )

    if response.status_code >= 400:
        try:
            error_message = response.json().get('error', {}).get('message', '')
        except ValueError:
            error_message = ''
        error_message = safe_error_message(error_message, limit=500)
        detail = f': {error_message}' if error_message else ''
        raise requests.HTTPError(
            f'{response.status_code} {response.reason}{detail}',
            response=response,
        )

    data = response.json()

    candidates = data.get('candidates', [])

    if not candidates:
        raise ValueError('Gemini returned no candidates')

    parts = candidates[0].get('content', {}).get('parts', [])

    raw = ''.join(
        part.get('text', '')
        for part in parts
    ).strip()

    if not raw:
        raise ValueError('Gemini returned an empty response')

    return json.loads(raw)


def call_gemini(text):
    primary_model = os.getenv(
        'GEMINI_MODEL',
        DEFAULT_GEMINI_MODEL
    ).strip() or DEFAULT_GEMINI_MODEL

    errors = []
    for attempt in range(3):
        try:
            return _gemini_request(primary_model, text)

        except requests.HTTPError as exc:
            status = (
                exc.response.status_code
                if exc.response is not None
                else None
            )

            errors.append(
                f'{primary_model} attempt {attempt + 1}: '
                f'HTTP {status}: {exc}'
            )

            if status in (429, 500, 502, 503, 504):
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue

            break

        except requests.RequestException as exc:
            errors.append(
                f'{primary_model} attempt {attempt + 1}: {exc}'
            )

            if attempt < 2:
                time.sleep(2 ** attempt)
                continue

            break

        except (ValueError, json.JSONDecodeError) as exc:
            errors.append(
                f'{primary_model} attempt {attempt + 1}: {exc}'
            )

            if attempt < 2:
                time.sleep(2 ** attempt)
                continue

            break

        except Exception as exc:
            errors.append(
                f'{primary_model} attempt {attempt + 1}: {exc}'
            )
            break

    raise RuntimeError(
        'Gemini model failed: ' + ' | '.join(errors)
    )


def call_openai_compatible(
    provider,
    base_url,
    api_key,
    model,
    text,
):
    if not api_key:
        raise RuntimeError(
            f'{provider} API key is not configured'
        )

    payload = {
        'model': model,
        'messages': [
            {
                'role': 'system',
                'content': PROMPT,
            },
            {
                'role': 'user',
                'content': clean_text(text),
            },
        ],
        'temperature': 0,
        'response_format': {
            'type': 'json_object'
        },
    }

    response = requests.post(
        base_url.rstrip('/') + '/chat/completions',
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        json=payload,
        timeout=60,
    )

    response.raise_for_status()

    data = response.json()

    choices = data.get('choices', [])

    if not choices:
        raise ValueError(
            f'{provider} returned no choices'
        )

    content = (
        choices[0]
        .get('message', {})
        .get('content', '')
    )

    if not content:
        raise ValueError(
            f'{provider} returned an empty response'
        )

    return json.loads(content)


def call_groq(text):
    return call_openai_compatible(
        'Groq',
        'https://api.groq.com/openai/v1',
        os.getenv('GROQ_API_KEY', ''),
        os.getenv(
            'GROQ_MODEL',
            'openai/gpt-oss-120b'
        ),
        text,
    )


def call_openrouter(text):
    return call_openai_compatible(
        'OpenRouter',
        'https://openrouter.ai/api/v1',
        os.getenv('OPENROUTER_API_KEY', ''),
        os.getenv(
            'OPENROUTER_MODEL',
            'openrouter/free'
        ),
        text,
    )


PROVIDERS = [
    ('gemini', call_gemini),
    ('groq', call_groq),
    ('openrouter', call_openrouter),
]


def extract_job(text, log=None):
    errors = []

    for name, fn in PROVIDERS:
        try:
            result = fn(text)

            if not isinstance(result, dict):
                raise ValueError(
                    'AI response was not a JSON object'
                )

            result['_provider'] = name

            if log:
                log(
                    provider=name,
                    status='success',
                    message='AI extraction successful',
                )

            return result

        except Exception as exc:
            errors.append(
                f'{name}: {exc}'
            )

            if log:
                log(
                    provider=name,
                    status='failed',
                    message=str(exc),
                )

    raise RuntimeError(
        'All AI providers failed: '
        + ' | '.join(errors)
    )
