from django.core import mail
from django.core.cache import cache
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.conf import settings
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.utils import timezone
from django.urls import reverse

from .admin import AdvertisementTextWidget
from .models import Advertisement, ContactMessage, CustomPage, Job, LegalPage, SiteSetting
from .templatetags.security_tags import sanitize_html


class SecurityTests(TestCase):

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

    def test_security_settings_restrict_rich_text_uploads_to_images(self):
        self.assertFalse(settings.CKEDITOR_ALLOW_NONIMAGE_FILES)

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

    def test_blog_editor_image_features_are_configured(self):
        self.assertIn('image2', settings.CKEDITOR_CONFIGS['default']['extraPlugins'])
        self.assertIn('uploadimage', settings.CKEDITOR_CONFIGS['default']['extraPlugins'])
        self.assertFalse(settings.CKEDITOR_CONFIGS['default']['image2_disableResizer'])

    def test_blog_admin_uses_upload_enabled_editor(self):
        from .admin import BlogPostAdmin

        form = BlogPostAdmin.form()
        self.assertEqual(form.fields['content'].widget.__class__.__name__, 'CKEditorUploadingWidget')

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

    def test_admin_login_page_has_language_switcher(self):
        response = self.client.get('/admin/login/?next=/admin/')

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
            {'language': 'am', 'next': '/admin/'},
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
