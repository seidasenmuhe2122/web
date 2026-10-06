from datetime import datetime, time, timedelta, timezone as datetime_timezone
from io import BytesIO, StringIO
import os
import tempfile
from unittest.mock import Mock, patch

import requests
from PIL import Image
from django import forms
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_login_failed
from django.conf import settings
from django.http import HttpResponse
from django.test import Client, TestCase, override_settings
from django.test import RequestFactory
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.utils import timezone
from django.urls import reverse

from .admin import AdvertisementTextWidget, JobAdminForm
from .services.ai_service import (
    AIProvidersUnavailable,
    DEFAULT_GEMINI_MODEL,
    PROMPT,
    PROVIDERS,
    SCHEMA,
    _gemini_request,
    call_gemini,
    extract_job,
)
from .models import (
    Advertisement,
    AutomationControl,
    AutomationRun,
    AutomationSchedule,
    ContactMessage,
    CustomPage,
    Job,
    JobSource,
    LegalPage,
    RawJobPost,
    SiteSetting,
    TelegramDestination,
    TelegramNotification,
    WebsiteSource,
)
from .services.collectors import collect_website, save_raw
from .services.processor import process_raw
from .services.telegram_service import (
    _telegram_summary,
    send_job,
    send_job_to_destination,
)
from .services.scheduler_service import automation_timezone, get_active_schedule
from .templatetags.security_tags import job_description, sanitize_ad_code, sanitize_html
from jopportal.middleware import RateLimitMiddleware


class AutomationCycleTests(TestCase):
    def test_processes_batch_beyond_publish_quota_and_recovers_stale_posts(self):
        source = JobSource.objects.create(name='Test website', source_type='website')
        WebsiteSource.objects.create(source=source, url='https://example.com/jobs')
        AutomationSchedule.objects.create(
            name='Test schedule',
            start_time=time.min,
            end_time=time.max,
            max_jobs=5,
            max_jobs_per_run=1,
        )
        fresh_posts = [
            RawJobPost.objects.create(
                source=source,
                external_id=f'fresh-{index}',
                content=f'Fresh post {index}',
                content_hash=f'{index:064d}',
            )
            for index in range(2)
        ]
        stale_post = RawJobPost.objects.create(
            source=source,
            external_id='stale',
            content='Interrupted post',
            content_hash='3' * 64,
            status='processing',
            discovered_at=timezone.now() - timedelta(hours=2),
        )
        publication_job = Job.objects.create(
            title='Eligible job',
            company_name='Example Company',
            location='Addis Ababa',
            description='A current vacancy.',
            auto_imported=True,
        )

        def process(raw):
            raw.status = 'processed' if raw.pk == fresh_posts[0].pk else 'rejected'
            raw.save(update_fields=['status'])
            return publication_job if raw.status == 'processed' else None

        with patch(
            'jobs.management.commands.automation_cycle.collect_website',
            return_value=fresh_posts,
        ), patch(
            'jobs.management.commands.automation_cycle.process_raw',
            side_effect=process,
        ) as process_raw, patch(
            'jobs.management.commands.automation_cycle.send_job',
        ) as send_job_mock:
            call_command('automation_cycle', stdout=StringIO())

        self.assertEqual(process_raw.call_count, 3)
        send_job_mock.assert_called_once()
        run = AutomationRun.objects.get(command='automation_cycle')
        self.assertEqual(run.collected, 2)
        self.assertEqual(run.processed, 1)
        self.assertEqual(run.rejected, 2)
        self.assertEqual(run.published, 1)
        self.assertEqual(AutomationControl.objects.get().daily_max_jobs, 0)
        stale_post.refresh_from_db()
        self.assertEqual(stale_post.status, 'rejected')

    def test_collector_creates_raw_post_with_new_status(self):
        source = JobSource.objects.create(name='Collector status source', source_type='website')

        raw = save_raw(source, 'A valid collected vacancy', external_id='source-item-1')

        self.assertEqual(raw.status, 'new')

    def test_processing_failure_is_reported_in_run_diagnostics(self):
        AutomationSchedule.objects.create(
            name='Processing failure schedule',
            start_time=time.min,
            end_time=time.max,
            max_jobs=10,
            max_jobs_per_run=2,
        )
        raw = RawJobPost.objects.create(
            external_id='failed-job',
            content='A collected vacancy',
            content_hash='e' * 64,
        )
        error_message = 'All AI providers failed: Gemini returned HTTP 400.'
        stderr = StringIO()

        def fail_processing(post):
            post.status = 'failed'
            post.last_error = error_message
            post.save(update_fields=['status', 'last_error'])
            return None

        with patch(
            'jobs.management.commands.automation_cycle.process_raw',
            side_effect=fail_processing,
        ):
            call_command('automation_cycle', stdout=StringIO(), stderr=stderr)

        run = AutomationRun.objects.get(command='automation_cycle')
        self.assertEqual(run.failed, 1)
        self.assertEqual(run.error_message, error_message)
        self.assertIn(f'Raw post {raw.pk}: {error_message}', stderr.getvalue())

    @patch('jobs.services.ai_service.requests.post')
    def test_gemini_error_includes_provider_diagnostic(self, post):
        response = Mock(status_code=400, reason='Bad Request')
        response.json.return_value = {
            'error': {'message': 'The model is not supported.'},
        }
        post.return_value = response

        with patch.dict(os.environ, {'GEMINI_API_KEY': 'test-api-key'}):
            with self.assertRaises(requests.HTTPError) as raised:
                _gemini_request('unsupported-model', 'A vacancy')

        self.assertIn('The model is not supported.', str(raised.exception))

    @patch('jobs.services.ai_service.requests.post')
    def test_gemini_schema_uses_nullable_numeric_salary_fields(self, post):
        response = Mock(status_code=200)
        response.json.return_value = {
            'candidates': [{'content': {'parts': [{'text': '{}'}]}}],
        }
        post.return_value = response

        with patch.dict(os.environ, {'GEMINI_API_KEY': 'test-api-key'}):
            _gemini_request('gemini-2.5-flash-lite', 'A vacancy')

        payload = post.call_args.kwargs['json']
        generation_config = payload['generationConfig']
        request_schema = generation_config['responseJsonSchema']
        expected = {
            'anyOf': [
                {'type': 'number'},
                {'type': 'null'},
            ]
        }
        for field in ('salary_min', 'salary_max'):
            self.assertEqual(request_schema['properties'][field], expected)
        self.assertEqual(SCHEMA['properties']['salary_min'], expected)
        self.assertEqual(SCHEMA['properties']['salary_max'], expected)
        self.assertEqual(request_schema, SCHEMA)
        self.assertEqual(
            set(request_schema['properties']),
            {
                'is_job', 'title', 'company', 'location', 'job_type',
                'organization_type', 'education_level', 'employment_type',
                'work_mode', 'region', 'country', 'languages_required',
                'keywords', 'salary_min', 'salary_max', 'salary_currency',
                'category', 'salary', 'deadline', 'description',
                'requirements', 'responsibilities', 'education', 'experience',
                'how_to_apply', 'application_url', 'contact_email',
                'contact_phone', 'contact_telegram', 'source_name', 'source_url',
            },
        )
        self.assertEqual(set(request_schema['properties']), set(request_schema['required']))
        self.assertEqual(generation_config['responseMimeType'], 'application/json')
        self.assertNotIn('responseSchema', generation_config)
        self.assertNotIn('temperature', generation_config)
        self.assertEqual(SCHEMA['properties']['experience'], {'type': 'string'})
        self.assertIn('free-form text', PROMPT)
        self.assertIn('Do not map experience to', PROMPT)

    @patch('jobs.services.ai_service.requests.post')
    def test_gemini_default_model_is_used_by_active_provider(self, post):
        response = Mock(status_code=200)
        response.json.return_value = {
            'candidates': [{
                'content': {
                    'parts': [{
                        'text': (
                            '{"is_job":true,"title":"Field Officer",'
                            '"company":"Example NGO","location":"Addis Ababa",'
                            '"description":"Manage field programs."}'
                        )
                    }]
                }
            }],
        }
        post.return_value = response

        raw = RawJobPost.objects.create(
            external_id='gemini-success',
            content='Field Officer vacancy details',
            content_hash='9' * 64,
        )
        with patch.dict(
            os.environ,
            {'GEMINI_API_KEY': 'test-api-key'},
            clear=True,
        ):
            job = process_raw(raw)

        raw.refresh_from_db()
        self.assertEqual(job.title, 'Field Officer')
        self.assertEqual(raw.status, 'processed')
        post.assert_called_once()
        self.assertEqual(
            post.call_args.args[0],
            'https://generativelanguage.googleapis.com/'
            f'v1beta/models/{DEFAULT_GEMINI_MODEL}:generateContent',
        )

    @patch('jobs.services.ai_service.requests.post')
    def test_gemini_model_can_be_overridden(self, post):
        response = Mock(status_code=200)
        response.json.return_value = {
            'candidates': [{'content': {'parts': [{'text': '{}'}]}}],
        }
        post.return_value = response

        with patch.dict(
            os.environ,
            {
                'GEMINI_API_KEY': 'test-api-key',
                'GEMINI_MODEL': 'gemini-test-flash-lite',
            },
            clear=True,
        ):
            call_gemini('A vacancy')

        self.assertIn(
            '/models/gemini-test-flash-lite:generateContent',
            post.call_args.args[0],
        )

    def test_gemini_flash_model_override_is_not_used(self):
        with patch.dict(
            os.environ,
            {
                'GEMINI_API_KEY': 'test-api-key',
                'GEMINI_MODEL': 'gemini-3.8-flash',
            },
            clear=True,
        ), patch('jobs.services.ai_service.requests.post') as post:
            with self.assertRaisesRegex(RuntimeError, 'Flash-Lite'):
                call_gemini('A vacancy')

        post.assert_not_called()

    def test_provider_order_and_gemini_flash_lite_default(self):
        self.assertEqual(
            [name for name, _ in PROVIDERS],
            ['gemini', 'groq', 'openrouter'],
        )
        gemini = Mock(return_value={'is_job': True})
        groq = Mock(return_value={'is_job': True})
        openrouter = Mock(return_value={'is_job': True})
        providers = [
            ('gemini', gemini),
            ('groq', groq),
            ('openrouter', openrouter),
        ]
        with patch('jobs.services.ai_service.PROVIDERS', providers):
            result = extract_job('A vacancy')

        self.assertEqual(
            [name for name, _ in providers],
            ['gemini', 'groq', 'openrouter'],
        )
        self.assertEqual(DEFAULT_GEMINI_MODEL, 'gemini-2.5-flash-lite')
        self.assertEqual(result['_provider'], 'gemini')
        gemini.assert_called_once_with('A vacancy')
        groq.assert_not_called()
        openrouter.assert_not_called()

    def test_gemini_429_falls_back_to_groq_without_retry(self):
        gemini = Mock(side_effect=requests.HTTPError(
            '429 Too Many Requests',
            response=Mock(status_code=429),
        ))
        groq = Mock(return_value={'is_job': True})
        openrouter = Mock()
        events = []
        with patch(
            'jobs.services.ai_service.PROVIDERS',
            [
                ('gemini', gemini),
                ('groq', groq),
                ('openrouter', openrouter),
            ],
        ):
            result = extract_job('A vacancy', log=lambda **event: events.append(event))

        self.assertEqual(result['_provider'], 'groq')
        gemini.assert_called_once_with('A vacancy')
        groq.assert_called_once_with('A vacancy')
        openrouter.assert_not_called()
        self.assertTrue(any('HTTP 429' in event['message'] for event in events))
        self.assertTrue(any(
            event['provider'] == 'groq'
            and 'Fallback selected' in event['message']
            for event in events
        ))

    def test_groq_429_falls_back_to_openrouter_without_retry(self):
        gemini = Mock(side_effect=RuntimeError('Gemini unavailable'))
        groq = Mock(side_effect=requests.HTTPError(
            '429 Too Many Requests',
            response=Mock(status_code=429),
        ))
        openrouter = Mock(return_value={'is_job': True})
        with patch(
            'jobs.services.ai_service.PROVIDERS',
            [
                ('gemini', gemini),
                ('groq', groq),
                ('openrouter', openrouter),
            ],
        ):
            result = extract_job('A vacancy')

        self.assertEqual(result['_provider'], 'openrouter')
        gemini.assert_called_once_with('A vacancy')
        groq.assert_called_once_with('A vacancy')
        openrouter.assert_called_once_with('A vacancy')

    def test_provider_logs_never_expose_api_keys(self):
        secret = 'provider-secret-key'
        gemini = Mock(side_effect=RuntimeError(f'GEMINI_API_KEY={secret}'))
        events = []
        with patch.dict(os.environ, {'GEMINI_API_KEY': secret}), patch(
            'jobs.services.ai_service.PROVIDERS',
            [
                ('gemini', gemini),
                ('groq', Mock(side_effect=RuntimeError('Groq unavailable'))),
                ('openrouter', Mock(side_effect=RuntimeError('OpenRouter unavailable'))),
            ],
        ):
            with self.assertRaises(AIProvidersUnavailable) as raised:
                extract_job('A vacancy', log=lambda **event: events.append(event))

        self.assertNotIn(secret, str(raised.exception))
        self.assertNotIn(secret, repr(events))
        self.assertTrue(any(
            event['provider'] == 'all' and event['status'] == 'failed'
            for event in events
        ))

    def test_ai_provider_fallback_remains_intact(self):
        gemini = Mock(side_effect=RuntimeError('Gemini unavailable'))
        groq = Mock(return_value={'is_job': True})
        with patch(
            'jobs.services.ai_service.PROVIDERS',
            [('gemini', gemini), ('groq', groq)],
        ):
            result = extract_job('A vacancy')

        self.assertEqual(result, {'is_job': True, '_provider': 'groq'})
        gemini.assert_called_once_with('A vacancy')
        groq.assert_called_once_with('A vacancy')

    @patch('jobs.services.processor.extract_job')
    def test_processor_creates_job_and_marks_repeated_job_duplicate(self, extract_job):
        source = JobSource.objects.create(name='Processor source', source_type='website')
        data = {
            'is_job': True,
            'title': 'Field Officer',
            'company': 'Example NGO',
            'location': 'Addis Ababa',
            'description': 'Manage field programs.',
            'category': 'NGO',
            'job_type': 'Full-time',
            'experience': '1-3 Years',
            'application_url': 'https://example.com/apply/123',
            'source_url': 'https://example.com/jobs/123',
            'requirements': [],
            'responsibilities': [],
            'deadline': '',
        }
        extract_job.return_value = data
        first = RawJobPost.objects.create(
            source=source,
            external_id='job-1',
            content='Field Officer vacancy details',
            content_hash='a' * 64,
        )
        second = RawJobPost.objects.create(
            source=source,
            external_id='job-2',
            content='Field Officer vacancy details',
            content_hash='b' * 64,
        )

        job = process_raw(first)
        duplicate = process_raw(second)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertIsNotNone(job)
        self.assertEqual(first.status, 'processed')
        self.assertEqual(job.apply_link, data['application_url'])
        self.assertEqual(job.source_url, data['source_url'])
        self.assertEqual(duplicate.pk, job.pk)
        self.assertEqual(second.status, 'duplicate')
        self.assertEqual(second.job_id, job.pk)

    @patch('jobs.services.processor.extract_job')
    def test_processor_preserves_free_text_experience_without_defaulting(self, extract_job):
        cases = (
            ('At least 3 years of experience', 'At least 3 years of experience'),
            ('2+ years of experience in accounting', '2+ years of experience in accounting'),
            ('No prior experience required', 'No prior experience required'),
            ('', ''),
            ('Fresh graduates are encouraged to apply', 'Fresh graduates are encouraged to apply'),
        )

        for index, (experience, expected) in enumerate(cases):
            with self.subTest(experience=experience):
                data = {
                    'is_job': True,
                    'title': f'Experience test {index}',
                    'company': 'Experience Test Company',
                    'location': 'Addis Ababa',
                    'description': 'A test vacancy description.',
                    'category': 'Other',
                    'job_type': 'Full-time',
                    'experience': experience,
                    'requirements': [],
                    'responsibilities': [],
                }
                extract_job.return_value = data
                raw = RawJobPost.objects.create(
                    external_id=f'experience-test-{index}',
                    content=f'Vacancy content for experience test {index}.',
                    content_hash=f'{index + 1:064d}',
                )

                job = process_raw(raw)

                self.assertIsNotNone(job)
                self.assertEqual(job.experience_level, expected)
                if expected:
                    self.assertIn(expected, job.description)
                else:
                    self.assertNotIn('<h5>Experience</h5>', job.description)

    def test_job_experience_is_free_text_in_model_and_admin(self):
        experience = 'At least 4 years of relevant experience in procurement'
        job = Job.objects.create(
            title='Procurement Specialist',
            company_name='Example Company',
            location='Addis Ababa',
            experience_level=experience,
            description='A procurement vacancy.',
        )

        field = Job._meta.get_field('experience_level')
        admin_field = JobAdminForm().fields['experience_level']
        response = self.client.get(reverse('job_detail', args=[job.pk]))

        self.assertEqual(field.max_length, 200)
        self.assertIsNone(field.choices)
        self.assertEqual(field.default, '')
        self.assertEqual(field.blank, True)
        self.assertIsInstance(admin_field.widget, forms.TextInput)
        self.assertContains(response, experience)

    @patch('jobs.services.processor.extract_job')
    def test_processor_preserves_structured_details_and_application_contacts(self, extract_job):
        extract_job.return_value = {
            'is_job': True,
            'title': 'Program Coordinator',
            'company': 'Example Organization',
            'location': 'Addis Ababa',
            'description': '<script>alert(1)</script> Coordinate field programs.',
            'category': 'NGO',
            'job_type': ['Full-time'],
            'experience': '2 years',
            'requirements': 'Relevant degree',
            'responsibilities': ['Prepare reports', 'Coordinate staff'],
            'education': 'Bachelor degree',
            'how_to_apply': '',
            'application_url': '',
            'contact_email': 'hr@example.com',
            'contact_phone': '+251 911 123 456',
            'contact_telegram': '@hrteam',
            'source_url': 'https://t.me/example_channel/123',
        }
        raw = RawJobPost.objects.create(
            external_id='structured-description',
            content=(
                'Interested candidates should send a CV to hr@example.com '
                'or message @hrteam. Applications close on Friday.'
            ),
            content_hash='d' * 64,
        )

        job = process_raw(raw)

        self.assertIsNotNone(job)
        self.assertIn('<h5>Job Description</h5>', job.description)
        self.assertIn('<ul><li>Prepare reports</li><li>Coordinate staff</li></ul>', job.description)
        self.assertIn('<ul><li>Relevant degree</li></ul>', job.description)
        self.assertIn('<h5>Education</h5>', job.description)
        self.assertIn('<h5>Experience</h5>', job.description)
        self.assertIn('<h5>How to Apply</h5>', job.description)
        self.assertIn('<strong>Email:</strong> hr@example.com', job.description)
        self.assertIn('<strong>Phone:</strong> +251 911 123 456', job.description)
        self.assertIn('<strong>Telegram:</strong> @hrteam', job.description)
        self.assertIn('Applications close on Friday.', job.description)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', job.description)
        rendered_description = job_description(job.description)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', rendered_description)
        self.assertNotIn('<script>', rendered_description)
        self.assertEqual(job.apply_link, '')
        self.assertEqual(job.source_url, 'https://t.me/example_channel/123')

        response = self.client.get(reverse('job_detail', args=[job.pk]))
        self.assertContains(response, '<ul>', html=False)
        self.assertContains(response, '<strong>Email:</strong> hr@example.com', html=False)
        self.assertContains(response, 'Interested candidates should send a CV', html=False)
        self.assertNotContains(response, 'Apply Now')

    @patch('jobs.services.processor.extract_job')
    def test_ai_failure_is_recorded_on_raw_post_and_processing_log(self, extract_job):
        extract_job.side_effect = RuntimeError('GROQ_API_KEY=provider-secret')
        raw = RawJobPost.objects.create(
            external_id='ai-failure',
            content='A collected vacancy',
            content_hash='c' * 64,
        )

        with patch.dict(os.environ, {'GROQ_API_KEY': 'provider-secret'}):
            result = process_raw(raw)

        raw.refresh_from_db()
        self.assertIsNone(result)
        self.assertEqual(raw.status, 'failed')
        self.assertIn('[redacted]', raw.last_error)
        self.assertNotIn('provider-secret', raw.last_error)
        self.assertTrue(raw.logs.filter(stage='system', status='failed').exists())

    def test_provider_exhaustion_keeps_raw_post_retryable(self):
        raw = RawJobPost.objects.create(
            external_id='provider-exhaustion',
            content='A collected vacancy',
            content_hash='d' * 64,
        )
        providers = [
            (name, Mock(side_effect=requests.HTTPError(
                '429 Too Many Requests',
                response=Mock(status_code=429),
            )))
            for name in ('gemini', 'groq', 'openrouter')
        ]

        with patch('jobs.services.ai_service.PROVIDERS', providers):
            result = process_raw(raw)

        raw.refresh_from_db()
        self.assertIsNone(result)
        self.assertTrue(RawJobPost.objects.filter(pk=raw.pk).exists())
        self.assertEqual(raw.status, 'new')
        self.assertIn('HTTP 429', raw.last_error)
        self.assertEqual(raw.attempts, 1)
        for _, provider in providers:
            provider.assert_called_once_with('A collected vacancy')
        self.assertTrue(raw.logs.filter(stage='system', status='failed').exists())

    @patch('jobs.services.processor.extract_job')
    def test_ai_provider_failure_can_be_retried_in_a_later_cycle(self, extract_job):
        extract_job.side_effect = AIProvidersUnavailable('All AI providers failed: 429')
        raw = RawJobPost.objects.create(
            external_id='provider-retry',
            content='A collected vacancy',
            content_hash='f' * 64,
        )

        process_raw(raw)
        raw.refresh_from_db()
        self.assertEqual(raw.status, 'new')

        process_raw(raw)
        raw.refresh_from_db()
        self.assertEqual(raw.status, 'new')
        self.assertEqual(raw.attempts, 2)
        self.assertEqual(extract_job.call_count, 2)

    @patch('jobs.services.processor.extract_job')
    def test_expired_job_is_rejected_before_creation(self, extract_job):
        extract_job.return_value = {
            'is_job': True,
            'title': 'Expired vacancy',
            'company': 'Example Company',
            'location': 'Addis Ababa',
            'description': 'This application is closed.',
            'deadline': (
                timezone.localtime(timezone.now(), automation_timezone()).date() - timedelta(days=1)
            ).isoformat(),
        }
        raw = RawJobPost.objects.create(
            external_id='expired-job',
            content='An expired vacancy',
            content_hash='d' * 64,
        )

        result = process_raw(raw)

        raw.refresh_from_db()
        self.assertIsNone(result)
        self.assertEqual(raw.status, 'rejected')
        self.assertIn('deadline has already passed', raw.rejection_reason)
        self.assertFalse(Job.objects.filter(title='Expired vacancy').exists())

    def test_website_collector_rejects_private_network_targets(self):
        source = JobSource.objects.create(name='Private URL source', source_type='website')
        config = WebsiteSource.objects.create(
            source=source,
            url='http://127.0.0.1/internal',
        )

        with self.assertRaisesRegex(ValueError, 'non-public network'):
            collect_website(config)

    def test_trigger_requires_secret_and_refuses_overlapping_runs(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            log_path = os.path.join(temporary_directory, 'automation.log')
            with patch.dict(os.environ, {
                'AUTOMATION_SECRET': 'test-trigger-secret',
                'AUTOMATION_LOG_FILE': log_path,
            }), patch('jobs.views.subprocess.Popen') as popen:
                unauthorized = self.client.get('/automation-trigger/?key=wrong')
                self.assertEqual(unauthorized.status_code, 401)
                self.assertEqual(AutomationRun.objects.count(), 0)

                started = self.client.get('/automation-trigger/?key=test-trigger-secret')
                self.assertEqual(started.status_code, 200)
                self.assertEqual(started.json()['status'], 'started')
                self.assertNotIn('test-trigger-secret', started.content.decode())

                overlapping = self.client.get('/automation-trigger/?key=test-trigger-secret')
                self.assertEqual(overlapping.status_code, 409)
                self.assertEqual(popen.call_count, 1)
                self.assertEqual(AutomationRun.objects.get().status, 'queued')

    def test_trigger_records_worker_start_failure_without_exposing_secret(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch.dict(os.environ, {
                'AUTOMATION_SECRET': 'test-trigger-secret',
                'AUTOMATION_LOG_FILE': os.path.join(temporary_directory, 'automation.log'),
            }), patch(
                'jobs.views.subprocess.Popen',
                side_effect=OSError('cannot launch test-trigger-secret'),
            ):
                response = self.client.get('/automation-trigger/?key=test-trigger-secret')

        self.assertEqual(response.status_code, 503)
        self.assertNotIn('test-trigger-secret', response.content.decode())
        run = AutomationRun.objects.get()
        self.assertEqual(run.status, 'failed')
        self.assertNotIn('test-trigger-secret', run.error_message)
        self.assertIsNone(AutomationControl.objects.get().active_run_id)

    def test_inactive_schedule_skips_collection(self):
        source = JobSource.objects.create(name='Inactive source', source_type='website')
        WebsiteSource.objects.create(source=source, url='https://example.com/jobs')

        with patch(
            'jobs.management.commands.automation_cycle.collect_website',
        ) as collect_website:
            call_command('automation_cycle', stdout=StringIO())

        collect_website.assert_not_called()
        run = AutomationRun.objects.get()
        self.assertEqual(run.status, 'skipped')
        self.assertIn('No active schedule', run.summary)

    def test_recent_run_and_manual_frequency_do_not_block_cron_cycle(self):
        control = AutomationControl.objects.create(
            pk=1,
            enabled=True,
            frequency_minutes=0,
            last_run_at=timezone.now() - timedelta(minutes=1),
            next_run_at=timezone.now(),
        )
        schedule = AutomationSchedule.objects.create(
            name='Active cron schedule',
            enabled=True,
            start_time=time.min,
            end_time=time.max,
            days_of_week=[],
            max_jobs=5,
            max_jobs_per_run=1,
        )
        source = JobSource.objects.create(name='Cron test source', source_type='website')
        WebsiteSource.objects.create(source=source, url='https://example.com/jobs')

        self.assertEqual(get_active_schedule(), schedule)

        with patch(
            'jobs.management.commands.automation_cycle.collect_website',
            return_value=[],
        ) as collect_website:
            call_command(
                'automation_cycle',
                '--no-telegram',
                stdout=StringIO(),
            )

        collect_website.assert_called_once()
        run = AutomationRun.objects.get(command='automation_cycle')
        self.assertEqual(run.status, 'success')
        self.assertNotIn('Frequency interval has not elapsed', run.summary)
        control.refresh_from_db()
        self.assertGreater(control.last_run_at, timezone.now() - timedelta(minutes=1))
        self.assertIsNone(control.next_run_at)

    def test_schedule_uses_addis_ababa_local_time(self):
        AutomationSchedule.objects.create(
            name='Ethiopia evening',
            start_time=time(19, 30),
            end_time=time(23, 31),
            max_jobs=500,
            max_jobs_per_run=10,
        )
        before_start = datetime(2026, 10, 2, 16, 29, tzinfo=datetime_timezone.utc)
        at_start = datetime(2026, 10, 2, 16, 30, tzinfo=datetime_timezone.utc)

        self.assertIsNone(get_active_schedule(before_start))
        self.assertIsNotNone(get_active_schedule(at_start))

    def test_daily_publication_limit_stops_sending_but_not_the_cycle(self):
        AutomationSchedule.objects.create(
            name='Daily limit schedule',
            start_time=time.min,
            end_time=time.max,
            max_jobs=10,
            max_jobs_per_run=10,
        )
        control = AutomationControl.objects.create(pk=1, daily_max_jobs=1)
        sent_job = Job.objects.create(
            title='Already sent',
            company_name='Example Company',
            location='Addis Ababa',
            description='Previously sent vacancy.',
        )
        TelegramNotification.objects.create(
            job=sent_job,
            channel_id='@already_sent',
            status='sent',
            sent_at=timezone.now(),
        )
        pending_job = Job.objects.create(
            title='Pending send',
            company_name='Example Company',
            location='Addis Ababa',
            description='Waiting vacancy.',
            auto_imported=True,
        )

        with patch('jobs.management.commands.automation_cycle.send_job') as send_job_mock:
            call_command('automation_cycle', stdout=StringIO())

        send_job_mock.assert_not_called()
        run = AutomationRun.objects.get()
        self.assertEqual(run.status, 'success')
        self.assertEqual(run.published, 0)
        self.assertEqual(control.daily_max_jobs, 1)
        self.assertIsNone(pending_job.telegram_notification_sent_at)

    def test_one_source_failure_does_not_stop_other_sources(self):
        AutomationSchedule.objects.create(
            name='Source isolation schedule',
            start_time=time.min,
            end_time=time.max,
            max_jobs=10,
            max_jobs_per_run=2,
        )
        first_source = JobSource.objects.create(name='Failing source', source_type='website')
        second_source = JobSource.objects.create(name='Healthy source', source_type='website')
        WebsiteSource.objects.create(source=first_source, url='https://first.example/jobs')
        WebsiteSource.objects.create(source=second_source, url='https://second.example/jobs')
        calls = []

        def collect(config):
            calls.append(config.source.name)
            if config.source_id == first_source.pk:
                raise RuntimeError('source unavailable')
            return []

        with patch(
            'jobs.management.commands.automation_cycle.collect_website',
            side_effect=collect,
        ):
            call_command('automation_cycle', stdout=StringIO(), stderr=StringIO())

        self.assertEqual(len(calls), 2)
        run = AutomationRun.objects.get()
        self.assertEqual(run.failed, 1)
        self.assertEqual(run.status, 'failed')

    def test_partial_telegram_failure_is_recorded_and_retried(self):
        job = Job.objects.create(
            title='Field Officer',
            company_name='Example NGO',
            location='Addis Ababa',
            description='Manage field programs.',
            auto_imported=True,
        )
        first_destination = TelegramDestination.objects.create(
            name='First channel', channel_id='@first_channel',
        )
        second_destination = TelegramDestination.objects.create(
            name='Second channel', channel_id='@second_channel',
        )
        sent_response = Mock()
        sent_response.raise_for_status.return_value = None
        sent_response.json.return_value = {
            'ok': True,
            'result': {'message_id': 123},
        }

        with patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': '123456:secret-token'}), patch(
            'jobs.services.telegram_service.requests.post',
            side_effect=[RuntimeError('123456:secret-token unavailable'), sent_response, sent_response],
        ) as post:
            with self.assertRaisesRegex(RuntimeError, 'delivery incomplete'):
                send_job(job, [first_destination, second_destination])

            statuses = dict(TelegramNotification.objects.values_list('destination__name', 'status'))
            self.assertEqual(statuses, {'First channel': 'failed', 'Second channel': 'sent'})
            job.refresh_from_db()
            self.assertIsNone(job.telegram_notification_sent_at)
            self.assertNotIn('123456:secret-token', TelegramNotification.objects.get(
                destination=first_destination,
            ).last_error)

            send_job(job, [first_destination, second_destination])

        job.refresh_from_db()
        self.assertIsNotNone(job.telegram_notification_sent_at)
        self.assertEqual(post.call_count, 3)

    def test_in_flight_telegram_notification_is_not_sent_twice(self):
        job = Job.objects.create(
            title='Concurrent job',
            company_name='Example Company',
            location='Addis Ababa',
            description='A vacancy.',
        )
        destination = TelegramDestination.objects.create(
            name='Concurrent channel',
            channel_id='@concurrent_channel',
        )
        TelegramNotification.objects.create(
            job=job,
            destination=destination,
            channel_id=destination.channel_id,
            status='sending',
            last_attempt_at=timezone.now(),
        )

        with patch('jobs.services.telegram_service.requests.post') as post:
            with self.assertRaisesRegex(RuntimeError, 'already in progress'):
                send_job_to_destination(job, destination)

        post.assert_not_called()

    def test_telegram_summary_formats_html_and_repairs_split_bullets(self):
        description = (
            '&lt;h5&gt;Job Description&lt;/h5&gt;'
            '&lt;p&gt;A friendly teacher.&lt;/p&gt;'
            '&lt;h5&gt;Requirements&lt;/h5&gt;'
            '&lt;ul&gt;&lt;li&gt;B • A • • D • e • g • r • e • e '
            '• • A • c • c • o • u • n • t • i • n • g • • F • i • n • a '
            '• n • c • e • • B • u • s • i • n • e • s • s '
            '• • M • a • n • a • g • e • m • e • n • t&lt;/li&gt;&lt;/ul&gt;'
        )

        summary = _telegram_summary(description)

        self.assertIn('Job Description\nA friendly teacher.', summary)
        self.assertIn('Requirements\n• BA Degree Accounting Finance Business Management', summary)
        self.assertNotIn('<h5>', summary)
        self.assertNotIn('• •', summary)


class SecurityTests(TestCase):

    def test_job_description_decodes_escaped_markup_and_repairs_split_bullets(self):
        rendered = job_description(
            '&lt;h5&gt;Requirements&lt;/h5&gt;'
            '&lt;p&gt;B • A • • D • e • g • r • e • e '
            '• • A • c • c • o • u • n • t • i • n • g • • F • i • n • a '
            '• n • c • e • • B • u • s • i • n • e • s • s '
            '• • M • a • n • a • g • e • m • e • n • t&lt;/p&gt;'
            '&lt;script&gt;alert(1)&lt;/script&gt;'
        )

        self.assertIn('<h5>Requirements</h5>', rendered)
        self.assertIn('BA Degree Accounting Finance Business Management', rendered)
        self.assertNotIn('&lt;h5&gt;', rendered)
        self.assertNotIn('<script>', rendered)

    @override_settings(RATE_LIMITS={'search': {'limit': 2, 'window': 60}})
    def test_rate_limit_returns_429_after_search_limit(self):
        middleware = RateLimitMiddleware(lambda request: HttpResponse('ok'))
        factory = RequestFactory()

        for _ in range(2):
            request = factory.get('/jobs/?q=django', REMOTE_ADDR='198.51.100.20')
            self.assertEqual(middleware(request).status_code, 200)

        request = factory.get('/jobs/?q=django', REMOTE_ADDR='198.51.100.20')
        response = middleware(request)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response['Retry-After'], '60')

    @override_settings(
        AUTH_LOGIN_FAILURE_LIMIT=2,
        AUTH_LOGIN_FAILURE_WINDOW=60,
        AUTH_LOGIN_BLOCK_DURATION=120,
    )
    def test_failed_admin_logins_temporarily_block_ip(self):
        middleware = RateLimitMiddleware(lambda request: HttpResponse('login handled'))
        factory = RequestFactory()
        request = factory.post(f'/{settings.ADMIN_URL}login/', REMOTE_ADDR='198.51.100.21')

        user_login_failed.send(
            sender=self.__class__,
            credentials={'username': 'admin'},
            request=request,
        )
        self.assertEqual(middleware(request).status_code, 200)

        user_login_failed.send(
            sender=self.__class__,
            credentials={'username': 'admin'},
            request=request,
        )
        response = middleware(request)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response['Retry-After'], '120')

    def test_rich_text_sanitizer_removes_executable_markup(self):
        cleaned = sanitize_html(
            '<script>alert(1)</script><a href="https://example.com" '
            'onclick="alert(2)">Link</a>'
        )

        self.assertNotIn('<script', cleaned)
        self.assertNotIn('onclick', cleaned)
        self.assertIn('https://example.com', cleaned)

    def test_rich_text_sanitizer_keeps_safe_formatting(self):
        cleaned = sanitize_html(
            '<span style="color: #f00; background-color: #000; font-size: 20px">'
            'Styled <a href="https://t.me/example">Telegram</a></span>'
        )

        self.assertIn('color: #f00', cleaned)
        self.assertIn('background-color: #000', cleaned)
        self.assertIn('font-size: 20px', cleaned)
        self.assertIn('https://t.me/example', cleaned)

    def test_rich_text_sanitizer_keeps_image_markup(self):
        cleaned = sanitize_html(
            '<img src="https://example.com/image.jpg" alt="Example" width="200" height="100" style="max-width: 100%;">'
        )

        self.assertIn('<img', cleaned)
        self.assertIn('https://example.com/image.jpg', cleaned)
        self.assertIn('max-width: 100%', cleaned)

    def test_legacy_job_description_formats_sections_and_repairs_mojibake(self):
        rendered = job_description(
            'Job Description\nManage field operations.\n\n'
            'Responsibilities:\nâ€¢ Prepare reports\nâ€¢ Coordinate staff\n\n'
            'Requirements:\n- Relevant degree'
        )

        self.assertIn('<h5>Job Description</h5>', rendered)
        self.assertIn('<h5>Responsibilities</h5>', rendered)
        self.assertIn('<ul><li>Prepare reports</li><li>Coordinate staff</li></ul>', rendered)
        self.assertIn('<h5>Requirements</h5>', rendered)
        self.assertIn('<ul><li>Relevant degree</li></ul>', rendered)
        self.assertNotIn('â€¢', rendered)

    def test_ad_code_sanitizer_removes_untrusted_script_markup(self):
        cleaned = sanitize_ad_code(
            '<script>alert(1)</script>'
            '<script src="https://evil.example/script.js"></script>'
            '<ins class="adsbygoogle" data-ad-client="ca-pub-example"></ins>'
        )

        self.assertNotIn('<script', cleaned)
        self.assertIn('adsbygoogle', cleaned)

    def test_security_headers_are_present(self):
        response = self.client.get('/')

        self.assertIn("default-src 'self'", response['Content-Security-Policy'])
        self.assertEqual(response['X-XSS-Protection'], '1; mode=block')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')

    def test_legacy_admin_url_redirects_to_configured_admin(self):
        response = self.client.get('/admin/')

        self.assertRedirects(
            response,
            f'/{settings.ADMIN_URL}',
            fetch_redirect_response=False,
        )

    @override_settings(
        SECURE_HSTS_SECONDS=31536000,
        SECURE_HSTS_INCLUDE_SUBDOMAINS=True,
        SECURE_HSTS_PRELOAD=True,
    )
    def test_hardening_headers_and_cookie_attributes_are_configured(self):
        response = self.client.get('/', secure=True)

        self.assertEqual(settings.X_FRAME_OPTIONS, 'DENY')
        self.assertEqual(settings.SECURE_REFERRER_POLICY, 'strict-origin-when-cross-origin')
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertTrue(settings.CSRF_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, 'Lax')
        self.assertEqual(settings.CSRF_COOKIE_SAMESITE, 'Lax')
        self.assertIn('max-age=31536000', response['Strict-Transport-Security'])

    def test_contact_post_requires_csrf_token(self):
        LegalPage.objects.get_or_create(
            page_type='contact',
            defaults={'title': 'Contact', 'content': '<p>Contact us.</p>'},
        )
        csrf_client = Client(enforce_csrf_checks=True)

        response = csrf_client.post(
            '/contact-us/message/',
            {'name': 'Visitor', 'email': 'visitor@example.com', 'subject': 'Hello', 'message': 'Message'},
        )

        self.assertEqual(response.status_code, 403)

    def test_blog_and_category_rich_text_are_sanitized_on_public_pages(self):
        from .models import BlogPost, JobCategory

        post = BlogPost.objects.create(
            title='Sanitized article',
            content='<p>Safe</p><script>alert("blog")</script>',
        )
        category = JobCategory.objects.create(
            name='Sanitized category',
            description='<p>Safe</p><script>alert("category")</script>',
        )

        blog_response = self.client.get(reverse('blog_detail', args=[post.slug]))
        category_response = self.client.get(reverse('category_list'))

        self.assertContains(blog_response, '<p>Safe</p>', html=False)
        self.assertNotContains(blog_response, '<script>alert("blog")</script>', html=False)
        self.assertContains(category_response, '<p>Safe</p>', html=False)
        self.assertNotContains(category_response, '<script>alert("category")</script>', html=False)

    def test_security_settings_restrict_rich_text_uploads_to_staff_and_images(self):
        self.assertEqual(settings.CKEDITOR_5_FILE_UPLOAD_PERMISSION, 'staff')
        self.assertEqual(
            settings.CKEDITOR_5_UPLOAD_FILE_TYPES,
            ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp'],
        )
        self.assertEqual(settings.CKEDITOR_5_MAX_FILE_SIZE, 5 * 1024 * 1024)

    def test_ckeditor5_upload_requires_staff(self):
        response = self.client.post('/ckeditor5/image_upload/')

        self.assertEqual(response.status_code, 403)

    def test_staff_can_upload_valid_image_with_ckeditor5(self):
        editor = get_user_model().objects.create_user(
            username='ckeditor-editor',
            password='test-password-123',
            is_staff=True,
        )
        self.client.force_login(editor)
        image_data = BytesIO()
        Image.new('RGB', (1, 1), color='white').save(image_data, format='PNG')
        upload = SimpleUploadedFile(
            'editor-image.png',
            image_data.getvalue(),
            content_type='image/png',
        )

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                response = self.client.post(
                    '/ckeditor5/image_upload/',
                    {'upload': upload},
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['url'], '/media/editor-image.png')
                saved_image = os.path.join(media_root, 'editor-image.png')
                self.assertTrue(os.path.exists(saved_image))
                Image.open(saved_image).verify()

    def test_ckeditor4_upload_route_is_removed(self):
        response = self.client.post('/ckeditor/upload/')

        self.assertEqual(response.status_code, 404)

    def test_job_application_link_uses_safe_new_tab_attributes(self):
        job = Job.objects.create(
            title='Safe application link',
            company_name='Security Company',
            location='Kombolcha',
            description='Apply safely.',
            apply_link='https://example.com/apply',
        )

        response = self.client.get(reverse('job_detail', args=[job.pk]))

        self.assertContains(response, 'rel="noopener noreferrer"')

    def test_job_detail_does_not_offer_source_url_as_application_link(self):
        job = Job.objects.create(
            title='Source is not application',
            company_name='Security Company',
            location='Kombolcha',
            description='Apply by email to jobs@example.com.',
            apply_link='javascript:alert(1)',
            source_url='https://t.me/example_channel/123',
        )

        response = self.client.get(reverse('job_detail', args=[job.pk]))

        self.assertNotContains(response, 'Apply Now')
        self.assertContains(response, 'jobs@example.com')

    def test_job_description_editor_supports_image_insertion(self):
        rendered = AdvertisementTextWidget().render('description', '', {'id': 'id_description'})

        self.assertIn('data-ad-command="insertImage"', rendered)

    @override_settings(
        ADVERTISEMENT_ALLOWED_HOSTS={'trusted.example.com'},
        SECURE_SSL_REDIRECT=False,
    )
    def test_advertisement_click_blocks_unsafe_destinations(self):
        advertisement = Advertisement.objects.create(
            title='Unsafe ad',
            position='sidebar',
            destination_link='javascript:alert(1)',
        )

        response = self.client.get(reverse('advertisement_click', args=[advertisement.pk]))

        self.assertIn(response.status_code, (301, 302))
        self.assertEqual(response.url, reverse('job_list'))
        advertisement.refresh_from_db()
        self.assertEqual(advertisement.clicks_count, 1)

    @override_settings(
        ADVERTISEMENT_ALLOWED_HOSTS={'trusted.example.com'},
        SECURE_SSL_REDIRECT=False,
    )
    def test_advertisement_click_redirects_to_allowed_destination(self):
        advertisement = Advertisement.objects.create(
            title='Trusted ad',
            destination_link='https://trusted.example.com/jobs',
        )

        response = self.client.get(reverse('advertisement_click', args=[advertisement.pk]))

        self.assertRedirects(response, 'https://trusted.example.com/jobs', fetch_redirect_response=False)

    def test_advertisement_text_is_rendered(self):
        advertisement = Advertisement.objects.create(
            title='Text ad',
            ad_text='Apply today',
        )
        cache.clear()

        response = self.client.get('/')

        self.assertContains(response, advertisement.ad_text)

    def test_advertisement_text_placement_uses_matching_layout_class(self):
        for placement in ('above', 'below', 'left', 'right'):
            advertisement = Advertisement.objects.create(
                title=f'{placement} ad',
                ad_text='Placement text',
                text_placement=placement,
            )

            rendered = render_to_string('jobs/_advertisement.html', {'ad': advertisement})

            self.assertIn(f'ad-text-{placement}', rendered)

    def test_advertisement_container_keeps_embedded_ads_responsive(self):
        rendered = render_to_string(
            'jobs/_advertisement.html',
            {'ad': Advertisement.objects.create(title='Responsive ad', adsense_code='<ins class="adsbygoogle"></ins>')},
        )
        self.assertIn('adsbygoogle', rendered)
        self.assertIn('ad-media', rendered)


class LegalPageTests(TestCase):

    def test_blog_cover_image_is_rendered_in_list_and_detail(self):
        from .models import BlogPost

        image = SimpleUploadedFile(
            'blog-cover.jpg',
            b'fake-image-content',
            content_type='image/jpeg',
        )
        post = BlogPost.objects.create(
            title='Image article',
            content='<p>Article content</p>',
            cover_image=image,
        )

        list_response = self.client.get(reverse('blog_list'))
        detail_response = self.client.get(reverse('blog_detail', args=[post.slug]))

        self.assertContains(list_response, post.cover_image.url)
        self.assertContains(detail_response, post.cover_image.url)

    def test_blog_editor_formatting_and_image_features_are_configured(self):
        toolbar = settings.CKEDITOR_5_CONFIGS['default']['toolbar']['items']

        for feature in (
            'heading', 'bold', 'italic', 'link', 'bulletedList',
            'numberedList', 'blockQuote', 'undo', 'redo', 'imageUpload',
        ):
            self.assertIn(feature, toolbar)

    def test_blog_admin_uses_upload_enabled_editor(self):
        from .admin import BlogPostAdmin

        form = BlogPostAdmin.form()
        self.assertEqual(form.fields['content'].widget.__class__.__name__, 'CKEditor5Widget')

    def test_rich_text_models_preserve_html_content(self):
        from django.contrib import admin
        from .models import BlogPost, JobCategory

        blog_html = '<h2>Article heading</h2><p><strong>Existing</strong> content.</p>'
        category_html = '<p>Existing category <a href="https://example.com">link</a>.</p>'
        blog = BlogPost.objects.create(title='Existing content', content=blog_html)
        category = JobCategory.objects.create(name='Existing HTML', description=category_html)
        category_form = admin.site._registry[JobCategory].get_form(None)()

        blog.refresh_from_db()
        category.refresh_from_db()

        self.assertEqual(blog.content, blog_html)
        self.assertEqual(category.description, category_html)
        self.assertEqual(category_form.fields['description'].widget.__class__.__name__, 'CKEditor5Widget')

    def test_job_display_defaults_to_work_and_preserves_previous_mode(self):
        job = Job.objects.create(
            title='Work display test',
            company_name='Kombolcha Tech',
            location='Kombolcha',
            description='Build useful tools.',
            apply_link='https://example.com/apply',
        )

        work_response = self.client.get('/')
        self.assertContains(work_response, 'job-card')
        self.assertContains(work_response, 'View Details')
        self.assertContains(work_response, 'View Details')
        self.assertNotContains(work_response, 'Apply Now')

        SiteSetting.objects.create(job_display_mode='previous')
        previous_response = self.client.get('/')
        self.assertContains(previous_response, 'previous-job-description')
        self.assertContains(previous_response, 'previous-job-paper')
        self.assertContains(previous_response, '-webkit-line-clamp: 4')
        self.assertContains(previous_response, 'Show More')
        self.assertNotContains(previous_response, 'View Details')

    def test_each_job_can_use_its_own_display_mode(self):
        previous_job = Job.objects.create(
            title='Previous mode job',
            company_name='Company One',
            location='Kombolcha',
            description='Previous description.',
            apply_link='https://example.com/previous',
            display_mode='previous',
        )
        list_job = Job.objects.create(
            title='List mode job',
            company_name='Company Two',
            location='Kombolcha',
            description='List description.',
            apply_link='https://example.com/list',
            display_mode='list',
        )
        response = self.client.get('/')

        self.assertContains(response, 'previous-job-description')
        self.assertContains(response, 'job-list-card')
        self.assertContains(response, previous_job.title)
        self.assertContains(response, list_job.title)

    def test_website_settings_control_homepage_ui(self):
        SiteSetting.objects.create(
            site_name='Kombolcha Careers',
            hero_badge='Local opportunities',
            hero_title='Build your future in Kombolcha',
            hero_description='Find work close to home.',
            show_hero=True,
            show_about_contact_links=False,
            show_language_switcher=False,
            show_footer_links=False,
            show_search_filters=False,
            show_job_stats=False,
            show_advertisements=False,
            primary_color='#ff0000',
            secondary_color='#00ff00',
            background_color='#101010',
            text_color='#ffffff',
            font_family='Georgia, serif',
            corner_radius=8,
        )
        cache.clear()

        response = self.client.get('/')

        self.assertContains(response, 'Build your future in Kombolcha')
        self.assertContains(response, 'Local opportunities')
        self.assertNotContains(response, 'data-page="about"')
        self.assertNotContains(response, 'name="language"')
        self.assertNotContains(response, 'Privacy Policy')
        self.assertNotContains(response, 'Title, company or category')
        self.assertNotContains(response, 'Active Jobs')
        self.assertContains(response, 'data-site-primary="#ff0000"')
        self.assertContains(response, 'data-site-secondary="#00ff00"')
        self.assertContains(response, 'data-site-font="Georgia, serif"')

    def test_website_branding_uses_site_name_and_header_text(self):
        SiteSetting.objects.create(
            site_name='My New Jobs Brand',
            header_text='Find better work',
            footer_text='',
        )

        response = self.client.get('/')

        self.assertContains(response, 'My New Jobs Brand')
        self.assertContains(response, 'Find better work')
        self.assertContains(response, '© My New Jobs Brand. All rights reserved.')

    def test_rich_branding_text_accepts_editor_markup_over_old_limit(self):
        setting = SiteSetting.objects.create(
            background_text='<p>' + ('Brand text ' * 40) + '</p>',
            top_bar_text='<p>' + ('Top bar text ' * 40) + '</p>',
        )

        setting.refresh_from_db()
        self.assertGreater(len(setting.background_text), 200)
        self.assertGreater(len(setting.top_bar_text), 300)

    def test_website_rich_text_branding_renders_html_safely(self):
        SiteSetting.objects.create(
            background_text='<strong>Watermarked brand</strong><script>alert(1)</script>',
            top_bar_text='<strong>Important notice</strong>',
            footer_text='<a href="https://example.com">Visit us</a>',
        )

        response = self.client.get('/')

        self.assertContains(response, '<strong>Watermarked brand</strong>', html=False)
        self.assertContains(response, '<strong>Important notice</strong>', html=False)
        self.assertContains(response, '<a href="https://example.com">Visit us</a>', html=False)
        self.assertNotContains(response, '<script>alert(1)</script>', html=False)

    def test_website_settings_has_public_preview_link(self):
        from .admin import SiteSettingAdmin

        setting = SiteSetting.objects.create(site_name='Preview Site')
        preview = SiteSettingAdmin(SiteSetting, admin.site).public_preview(setting)

        self.assertIn('Open site', preview)
        self.assertIn(reverse('home'), preview)

    def test_admin_theme_config_returns_dashboard_customization(self):
        from django.contrib.auth import get_user_model

        setting = SiteSetting.objects.create(
            admin_sidebar_color='#112233',
            admin_accent_color='#445566',
            admin_workspace_color='#778899',
            admin_primary_color='#38bdf8',
            admin_secondary_color='#a855f7',
            admin_text_color='#e0f2fe',
            admin_background_mode='image',
        )
        user = get_user_model().objects.create_superuser(
            username='theme-admin',
            email='theme@example.com',
            password='test-password-123',
        )
        self.client.force_login(user)

        response = self.client.get(reverse('admin_theme_config'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['sidebar_color'], setting.admin_sidebar_color)
        self.assertEqual(response.json()['accent_color'], setting.admin_accent_color)
        self.assertEqual(response.json()['workspace_color'], setting.admin_workspace_color)
        self.assertEqual(response.json()['primary_color'], setting.admin_primary_color)
        self.assertEqual(response.json()['secondary_color'], setting.admin_secondary_color)
        self.assertEqual(response.json()['text_color'], setting.admin_text_color)
        self.assertEqual(response['Cache-Control'], 'no-store, no-cache, must-revalidate, max-age=0')

    def test_admin_background_config_returns_uploaded_image(self):
        image = SimpleUploadedFile('admin-background.jpg', b'fake-image', content_type='image/jpeg')
        setting = SiteSetting.objects.create(
            admin_background_mode='image',
            admin_background_image=image,
        )
        user = get_user_model().objects.create_superuser(
            username='background-admin',
            email='background@example.com',
            password='test-password-123',
        )
        self.client.force_login(user)

        response = self.client.get(reverse('admin_theme_config'))

        self.assertEqual(response.status_code, 200)
        self.assertIn('admin-background', response.json()['background_image'])
        self.assertEqual(response.json()['background_mode'], setting.admin_background_mode)

    def test_previous_admin_background_mode_is_available(self):
        self.assertIn(
            ('previous', 'Previous dashboard background'),
            SiteSetting.ADMIN_BACKGROUND_MODE_CHOICES,
        )

    def test_legal_page_admin_content_controls_public_page(self):
        page = LegalPage.objects.get(page_type='about')
        page.title = 'Our Kombolcha Story'
        page.content = '<p>Edited from the Admin Dashboard.</p>'
        page.text_color = '#ff0000'
        page.font_size = 20
        page.save()

        response = self.client.get(reverse('about_us'))

        self.assertContains(response, 'Our Kombolcha Story')
        self.assertContains(response, 'Edited from the Admin Dashboard.')
        self.assertContains(response, 'color: #ff0000')
        self.assertContains(response, 'font-size: 20px')

    def test_job_interface_translates_in_amharic(self):
        job = Job.objects.create(
            title='Python Developer',
            company_name='Kombolcha Tech',
            location='Kombolcha',
            job_type='Full-time',
            experience_level='Fresh Graduate',
            description='Build useful tools.',
            description_am='የሥራ ማጠቃለያ።',
            apply_link='https://example.com/apply',
        )

        response = self.client.get('/am/job/{}/'.format(job.pk))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'የሥራ መግለጫ')
        self.assertContains(response, 'አሁኑኑ ያመልክቱ')
        self.assertContains(response, 'የሥራ ማጠቃለያ።')
        self.assertNotContains(response, 'Job Description')

    def test_dynamic_custom_pages_are_accessible_by_slug(self):
        page = LegalPage.objects.create(
            page_type='faq',
            title='Frequently Asked Questions',
            content='<p>Can I apply online?</p>',
            text_color='#111111',
            font_size=18,
            contact_enabled=False,
        )

        response = self.client.get('/pages/{}/'.format(page.page_type))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Frequently Asked Questions')
        self.assertContains(response, 'Can I apply online?')

    def test_custom_page_auto_slug_and_manual_slug_modes(self):
        auto_page = CustomPage.objects.create(
            title='Employer Guide',
            content='<p>Guide</p>',
        )
        duplicate_page = CustomPage.objects.create(
            title='Employer Guide',
            content='<p>Second guide</p>',
        )
        manual_page = CustomPage.objects.create(
            title='Partner Information',
            slug_mode='manual',
            slug='partners',
            content='<p>Partners</p>',
        )

        self.assertEqual(auto_page.slug, 'employer-guide')
        self.assertEqual(duplicate_page.slug, 'employer-guide-2')
        self.assertEqual(manual_page.slug, 'partners')

    def test_added_legal_pages_are_linked_in_public_footer(self):
        LegalPage.objects.create(
            page_type='help-center',
            title='Help Center',
            content='<p>Help content.</p>',
            contact_enabled=False,
        )
        cache.clear()

        response = self.client.get('/')

        self.assertContains(response, 'href="/pages/help-center/"')
        self.assertContains(response, 'Help Center')

    def test_legal_page_placement_controls_public_location(self):
        LegalPage.objects.create(
            page_type='header-help',
            title='Header Help',
            content='<p>Header help content.</p>',
            placement_location='header',
            contact_enabled=False,
        )
        cache.clear()

        response = self.client.get('/')
        header_link = 'href="/pages/header-help/"'

        self.assertContains(response, header_link)
        self.assertLess(response.content.decode().index(header_link), response.content.decode().index('<main'))

    def test_legal_page_side_placements_render_in_their_sidebar(self):
        LegalPage.objects.create(
            page_type='right-middle-help',
            title='Right Middle Help',
            content='<p>Right middle content.</p>',
            placement_location='right_middle',
            contact_enabled=False,
        )
        cache.clear()

        response = self.client.get('/')

        self.assertContains(response, 'Right Middle Help')
        self.assertContains(response, 'Right middle content.')

    def test_page_updates_bypass_cached_global_context(self):
        page = LegalPage.objects.create(
            page_type='live-update',
            title='Original title',
            content='<p>Original content.</p>',
            placement_location='main_body',
            contact_enabled=False,
        )
        cache.clear()
        self.client.get('/')

        page.title = 'Updated title'
        page.save()

        response = self.client.get('/')
        self.assertContains(response, 'Updated title')
        self.assertNotContains(response, 'Original title')

    def test_custom_page_renders_style_content_and_sanitizes_html(self):
        CustomPage.objects.create(
            title='Employer Guide',
            slug='employer-guide',
            content='<h2>Hiring guide</h2><p>Useful details.</p><script>alert(1)</script>',
            text_color='#ff0000',
            font_size=22,
            placement_location='header',
        )
        cache.clear()

        response = self.client.get('/pages/employer-guide/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Hiring guide')
        self.assertContains(response, 'color: #ff0000')
        self.assertContains(response, 'font-size: 22px')
        legal_content = response.content.decode().split('<div class="legal-content">', 1)[1].split('</div>', 1)[0]
        self.assertNotIn('<script>', legal_content)

    def test_custom_page_placement_is_available_in_public_context(self):
        CustomPage.objects.create(
            title='Resources',
            slug='resources',
            content='<p>Resources</p>',
            placement_location='footer',
        )
        cache.clear()

        response = self.client.get('/')

        self.assertContains(response, 'href="/pages/resources/"')
        self.assertContains(response, 'Resources')

    def test_custom_page_side_placement_renders_in_sidebar(self):
        CustomPage.objects.create(
            title='Custom Sidebar Page',
            slug='custom-sidebar-page',
            content='<p>Custom sidebar content.</p>',
            placement_location='right_middle',
        )
        cache.clear()

        response = self.client.get('/')

        self.assertContains(response, 'Custom Sidebar Page')
        self.assertContains(response, 'Custom sidebar content.')

    def test_advertisement_positions_have_default_and_automatic_rendering(self):
        default_ad = Advertisement.objects.create(title='Default ad')
        self.assertEqual(default_ad.position, 'header')

        right_ad = Advertisement.objects.create(
            title='Right middle ad',
            position='right_middle',
            adsense_code='<strong>Right middle advertisement</strong>',
        )
        cache.clear()

        response = self.client.get('/')

        self.assertContains(response, 'Right middle advertisement')
        self.assertContains(response, f'/advertisement/{right_ad.pk}/impression.gif')

    def test_auto_advertisement_position_resolves_to_header_without_removing_positions(self):
        auto_ad = Advertisement.objects.create(
            title='Auto placement ad',
            position='auto',
            adsense_code='<strong>Auto placement content</strong>',
        )
        self.assertEqual(auto_ad.effective_position, 'header')
        self.assertEqual(
            {value for value, label in Advertisement.POSITION_CHOICES},
            {
                'auto', 'header', 'sidebar', 'inside_job', 'footer',
                'right_top', 'right_middle', 'right_bottom',
                'left_top', 'left_middle', 'left_bottom',
            },
        )
        cache.clear()
        response = self.client.get('/')
        self.assertContains(response, 'Auto placement content')

    def test_advertisement_auto_format_and_video_format(self):
        auto_video = Advertisement.objects.create(
            title='Auto video',
            position='right_top',
            video_url='https://cdn.example.com/demo.mp4',
        )
        explicit_video = Advertisement.objects.create(
            title='Explicit video',
            position='right_bottom',
            display_format='video',
            video_url='https://cdn.example.com/explicit.mp4',
        )

        self.assertEqual(auto_video.effective_format, 'video')
        self.assertEqual(explicit_video.effective_format, 'video')
        cache.clear()
        response = self.client.get('/')
        self.assertContains(response, 'https://cdn.example.com/demo.mp4')
        self.assertContains(response, 'https://cdn.example.com/explicit.mp4')

    def test_legal_page_admin_save_updates_content_and_audit_time(self):
        page = LegalPage.objects.create(
            page_type='support',
            title='Support',
            content='<p>Original support content.</p>',
            contact_enabled=False,
        )
        original_updated_at = page.updated_at
        admin_user = get_user_model().objects.create_superuser(
            username='legaladmin', email='legaladmin@example.com', password='test-password-123'
        )
        self.client.force_login(admin_user)

        response = self.client.post(
            reverse('admin:jobs_legalpage_change', args=[page.pk]),
            {
                'page_type': 'support',
                'title': 'Updated Support',
                'content': '<p>Updated support content.</p>',
                'text_color': '#212529',
                'font_size': 16,
                'placement_location': 'footer',
                'contact_enabled': '',
                '_save': 'Save',
            },
        )

        self.assertEqual(response.status_code, 302)
        page.refresh_from_db()
        self.assertEqual(page.title, 'Updated Support')
        self.assertIn('Updated support content.', page.content)
        self.assertGreaterEqual(page.updated_at, original_updated_at)
        self.assertContains(self.client.get('/pages/support/'), 'Updated Support')

    def test_admin_login_redirects_to_dashboard_after_success(self):
        user = get_user_model().objects.create_superuser(
            username='redirectadmin', email='redirectadmin@example.com', password='test-password-123'
        )

        response = self.client.post(
            f'/{settings.ADMIN_URL}login/',
            {'username': user.username, 'password': 'test-password-123'},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain[-1][0], f'/{settings.ADMIN_URL}')
        self.assertContains(response, 'Dashboard')

    def test_admin_login_page_has_language_switcher(self):
        response = self.client.get(reverse('admin:login'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="language"')
        self.assertContains(response, 'value="am"')
        self.assertContains(response, 'value="ar"')
        self.assertNotContains(response, 'value="aa"')
        self.assertNotContains(response, 'value="es"')
        self.assertNotContains(response, 'value="fr"')
        self.assertNotContains(response, 'value="om"')

    def test_admin_dashboard_translates_to_amharic_after_language_switch(self):
        user = get_user_model().objects.create_superuser(
            username='amadmin', email='amadmin@example.com', password='test-password-123'
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse('set_language'),
            {'language': 'am', 'next': f'/{settings.ADMIN_URL}'},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ዳሽቦርድ')
        language_selector = response.content.decode().split(
            '<div class="dropdown-menu dropdown-menu-lg dropdown-menu-end" id="jazzy-languagemenu">', 1
        )[1].split('</div>', 1)[0]
        self.assertIn('value="en"', language_selector)
        self.assertIn('value="am"', language_selector)
        self.assertIn('value="ar"', language_selector)
        self.assertNotIn('value="aa"', language_selector)
        self.assertNotIn('value="es"', language_selector)
        self.assertNotIn('value="fr"', language_selector)
        self.assertNotIn('value="om"', language_selector)

    def test_language_switch_redirects_to_amharic_page(self):
        response = self.client.post(
            reverse('set_language'),
            {'language': 'am', 'next': '/'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/am/')

    def test_language_switch_works_from_amharic_page(self):
        self.client.get('/am/')

        response = self.client.post(
            reverse('set_language'),
            {'language': 'en', 'next': '/en/'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/en/')

    def test_all_configured_languages_open_homepage(self):
        for language_code, _ in settings.LANGUAGES:
            path = '/' if language_code == settings.LANGUAGE_CODE else f'/{language_code}/'
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, language_code)
            self.assertContains(response, f'value="{language_code}"')

    def test_about_and_contact_are_separate_pages(self):
        about_response = self.client.get(reverse('about_us'))
        contact_response = self.client.get(reverse('contact_us'))
        message_response = self.client.get(reverse('contact_message'))

        self.assertContains(about_response, 'About Job Portal Ethiopia')
        self.assertNotContains(about_response, 'Send us a message')
        self.assertContains(contact_response, 'Contact Us')
        self.assertNotContains(contact_response, 'Write your message here')
        self.assertContains(message_response, 'Send us a message')
        self.assertNotContains(contact_response, 'data-page="about"')
        self.assertNotContains(about_response, 'data-page="contact"')
        self.assertNotEqual(about_response.request['PATH_INFO'], contact_response.request['PATH_INFO'])

    def test_seeded_about_page_contains_kombolcha_identity(self):
        response = self.client.get(reverse('about_us'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Job Portal Ethiopia')
        self.assertContains(response, 'Kombolcha')

    def test_contact_form_creates_message(self):
        response = self.client.post(
            reverse('contact_us'),
            {
                'name': 'Abel',
                'email': 'abel@example.com',
                'subject': 'Listing question',
                'message': 'I have a question about a listing.',
            },
        )

        self.assertRedirects(response, reverse('contact_us'))
        self.assertTrue(ContactMessage.objects.filter(subject='Listing question').exists())
        self.assertEqual(LegalPage.objects.filter(page_type='contact').count(), 1)

    def test_contact_and_message_pages_are_separate(self):
        contact_response = self.client.get(reverse('contact_us'))
        message_response = self.client.get(reverse('contact_message'))

        self.assertContains(contact_response, 'Contact Us')
        self.assertNotContains(contact_response, 'Write your message here')
        self.assertContains(message_response, 'Send us a message')
        self.assertContains(message_response, 'Write your message here')
        self.assertContains(message_response, 'Send message')

    def test_admin_can_disable_contact_form(self):
        contact_page = LegalPage.objects.get(page_type='contact')
        contact_page.contact_enabled = False
        contact_page.save(update_fields=['contact_enabled'])

        response = self.client.get(reverse('contact_us'))

        self.assertContains(response, 'temporarily unavailable')
        self.assertNotContains(response, 'Send us a message')

    def test_admin_controlled_contact_action_button_is_rendered(self):
        SiteSetting.objects.create(
            contact_action_enabled=True,
            contact_action_label='Message us on Telegram',
            contact_action_url='https://t.me/AFRIJO',
        )
        cache.clear()

        response = self.client.get(reverse('contact_message'))

        self.assertContains(response, 'Message us on Telegram')
        self.assertContains(response, 'https://t.me/AFRIJO')

    def test_admin_can_hide_send_message_button(self):
        SiteSetting.objects.create(contact_submit_enabled=False)
        cache.clear()

        response = self.client.get(reverse('contact_message'))

        self.assertNotContains(response, 'Send message')

    @override_settings(
        MAILERS={'default': {'BACKEND': 'django.core.mail.backends.locmem.EmailBackend'}},
    )
    def test_admin_can_reply_to_contact_message(self):
        admin_user = get_user_model().objects.create_superuser(
            username='admin', email='admin@example.com', password='test-password'
        )
        contact_message = ContactMessage.objects.create(
            name='Abel',
            email='abel@example.com',
            subject='Listing question',
            message='Please help.',
        )
        self.client.force_login(admin_user)

        response = self.client.post(
            reverse('admin:jobs_contactmessage_reply', args=[contact_message.pk]),
            {'subject': 'Re: Listing question', 'message': 'Here is the answer.'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('admin:jobs_contactmessage_changelist'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['abel@example.com'])
        contact_message.refresh_from_db()
        self.assertTrue(contact_message.is_read)
        self.assertEqual(contact_message.reply_message, 'Here is the answer.')
        self.assertIsNotNone(contact_message.replied_at)

    @override_settings(
        MAILERS={'default': {'BACKEND': 'django.core.mail.backends.locmem.EmailBackend'}},
    )
    def test_admin_can_send_email_to_any_recipient(self):
        admin_user = get_user_model().objects.create_superuser(
            username='compose-admin', email='admin@example.com', password='test-password'
        )
        self.client.force_login(admin_user)

        response = self.client.post(
            reverse('admin:jobs_contactmessage_compose_email'),
            {
                'recipient': 'business@example.com',
                'subject': 'Business opportunity',
                'message': 'Let us work together.',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('admin:jobs_contactmessage_changelist'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['business@example.com'])
        self.assertEqual(mail.outbox[0].subject, 'Business opportunity')

    @override_settings(
        MAILERS={'default': {'BACKEND': 'django.core.mail.backends.locmem.EmailBackend'}},
    )
    def test_admin_email_supports_rich_text_and_attachments(self):
        admin_user = get_user_model().objects.create_superuser(
            username='attachment-admin', email='admin@example.com', password='test-password'
        )
        self.client.force_login(admin_user)
        attachment = SimpleUploadedFile(
            'proposal.pdf', b'%PDF-1.4 proposal', content_type='application/pdf'
        )

        response = self.client.post(
            reverse('admin:jobs_contactmessage_compose_email'),
            {
                'recipient': 'business@example.com',
                'subject': 'Proposal',
                'message': '<p><strong>Important</strong> <a href="https://example.com">details</a></p>',
                'attachments': [attachment],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('<strong>Important</strong>', mail.outbox[0].alternatives[0][0])
        self.assertIn('proposal.pdf', mail.outbox[0].message().as_string())

    def test_contact_message_admin_shows_contact_button_settings_link(self):
        admin_user = get_user_model().objects.create_superuser(
            username='contact-admin', email='admin@example.com', password='test-password'
        )
        SiteSetting.objects.create()
        contact_message = ContactMessage.objects.create(
            name='Abel',
            email='abel@example.com',
            subject='Button settings',
            message='Please help.',
        )
        self.client.force_login(admin_user)

        response = self.client.get(reverse('admin:jobs_contactmessage_changelist'))

        self.assertContains(response, 'Contact button settings')
        self.assertContains(response, '>View</a>')
        self.assertContains(response, '>Reply</a>')
        self.assertContains(response, '>Mark read</a>')
        self.assertContains(response, 'mailto:abel@example.com')
        self.assertContains(response, 'Hide Send button')
        self.assertContains(response, 'Hide Contact page')
        self.assertContains(response, reverse('admin:jobs_sitesetting_change', args=[SiteSetting.objects.first().pk]))

    def test_contact_admin_can_toggle_send_message_button(self):
        admin_user = get_user_model().objects.create_superuser(
            username='toggle-admin', email='admin@example.com', password='test-password'
        )
        SiteSetting.objects.create(contact_submit_enabled=True)
        ContactMessage.objects.create(
            name='Abel', email='abel@example.com', subject='Toggle', message='Please help.'
        )
        self.client.force_login(admin_user)

        response = self.client.get(reverse('admin:jobs_contactmessage_toggle_contact_button'))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(SiteSetting.objects.first().contact_submit_enabled)

    def test_contact_admin_can_toggle_contact_page_separately(self):
        admin_user = get_user_model().objects.create_superuser(
            username='page-toggle-admin', email='admin@example.com', password='test-password'
        )
        contact_page = LegalPage.objects.get(page_type='contact')
        contact_page.contact_enabled = True
        contact_page.save(update_fields=['contact_enabled'])
        ContactMessage.objects.create(
            name='Abel', email='abel@example.com', subject='Page toggle', message='Please help.'
        )
        self.client.force_login(admin_user)

        response = self.client.get(reverse('admin:jobs_contactmessage_toggle_contact_page'))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(LegalPage.objects.get(page_type='contact').contact_enabled)

    def test_contact_controls_are_independent(self):
        admin_user = get_user_model().objects.create_superuser(
            username='independent-toggle-admin', email='admin@example.com', password='test-password'
        )
        SiteSetting.objects.create(contact_submit_enabled=True)
        contact_page = LegalPage.objects.get(page_type='contact')
        contact_page.contact_enabled = True
        contact_page.save(update_fields=['contact_enabled'])
        self.client.force_login(admin_user)

        self.client.get(reverse('admin:jobs_contactmessage_toggle_contact_button'))
        site_setting = SiteSetting.objects.first()
        contact_page.refresh_from_db()
        self.assertFalse(site_setting.contact_submit_enabled)
        self.assertTrue(contact_page.contact_enabled)

        self.client.get(reverse('admin:jobs_contactmessage_toggle_contact_page'))
        site_setting.refresh_from_db()
        contact_page.refresh_from_db()
        self.assertFalse(site_setting.contact_submit_enabled)
        self.assertFalse(contact_page.contact_enabled)

    def test_contact_menu_has_separate_page_and_message_links(self):
        response = self.client.get(reverse('job_list'))

        self.assertContains(response, 'Contact us')
        self.assertContains(response, 'Send us a message')
        self.assertContains(response, reverse('contact_message'))

    def test_admin_can_toggle_message_read_status(self):
        admin_user = get_user_model().objects.create_superuser(
            username='reader', email='reader@example.com', password='test-password'
        )
        contact_message = ContactMessage.objects.create(
            name='Abel',
            email='abel@example.com',
            subject='Read status',
            message='Please mark me read.',
        )
        self.client.force_login(admin_user)

        response = self.client.get(
            reverse('admin:jobs_contactmessage_toggle_read', args=[contact_message.pk])
        )

        self.assertEqual(response.status_code, 302)
        contact_message.refresh_from_db()
        self.assertTrue(contact_message.is_read)

    def test_read_button_opens_message_and_marks_it_read(self):
        admin_user = get_user_model().objects.create_superuser(
            username='viewer', email='viewer@example.com', password='test-password'
        )
        contact_message = ContactMessage.objects.create(
            name='Marta',
            email='marta@example.com',
            subject='Please read this',
            message='Full message body.',
        )
        self.client.force_login(admin_user)

        response = self.client.get(
            reverse('admin:jobs_contactmessage_view', args=[contact_message.pk])
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            reverse('admin:jobs_contactmessage_change', args=[contact_message.pk]),
        )
        contact_message.refresh_from_db()
        self.assertTrue(contact_message.is_read)
