from django.contrib import admin
from django import forms
from django.core.cache import cache
from django.contrib import messages
from django.core.mail import EmailMultiAlternatives, send_mail
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.html import strip_tags
from django.utils.safestring import mark_safe
from django.utils.html import conditional_escape
from html import unescape
from django.conf import settings
from ckeditor_uploader.widgets import CKEditorUploadingWidget
from .forms import AdminEmailForm, ContactReplyForm
from .models import (
    Advertisement,
    BlogPost,
    ContactMessage,
    CustomPage,
    Job,
    JobCategory,
    LegalPage,
    SentEmail,
    SiteSetting,
)
from .templatetags.security_tags import sanitize_html


@admin.register(JobCategory)
class JobCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_featured', 'created_at')
    list_filter = ('is_featured',)
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name', 'slug', 'description')
    list_editable = ('is_featured',)
    fields = ('name', 'slug', 'icon', 'accent_color', 'description', 'is_featured', 'created_at', 'updated_at')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    class BlogPostAdminForm(forms.ModelForm):
        content = forms.CharField(widget=CKEditorUploadingWidget(config_name='default'))

        class Meta:
            model = BlogPost
            fields = '__all__'

    form = BlogPostAdminForm
    list_display = ('title', 'author', 'is_published', 'created_at')
    list_filter = ('is_published', 'created_at')
    prepopulated_fields = {'slug': ('title',)}
    search_fields = ('title', 'slug', 'author', 'excerpt', 'content')
    list_editable = ('is_published',)
    fields = ('title', 'slug', 'author', 'cover_image', 'excerpt', 'content', 'is_published', 'created_at', 'updated_at')
    readonly_fields = ('created_at', 'updated_at')


class SiteSettingAdminForm(forms.ModelForm):
    class Meta:
        model = SiteSetting
        fields = '__all__'
        widgets = {
            'job_display_mode': forms.RadioSelect,
        }


class AdvertisementTextWidget(forms.Textarea):
    class Media:
        js = ('jobs/js/advertisement_editor.js',)
        css = {'all': ('jobs/css/advertisement_editor.css',)}

    def render(self, name, value, attrs=None, renderer=None):
        attrs = attrs or {}
        widget_id = attrs.get('id', f'id_{name}')
        editor_id = f'{widget_id}_editor'
        value = unescape(value or '')
        return mark_safe(
            '<div class="advertisement-editor">'
            '<div class="advertisement-editor-toolbar" role="toolbar">'
            '<button type="button" data-ad-command="bold"><strong>B</strong></button>'
            '<button type="button" data-ad-command="italic"><em>I</em></button>'
            '<button type="button" data-ad-command="underline"><u>U</u></button>'
            '<button type="button" data-ad-command="strikeThrough"><s>S</s></button>'
            '<select data-ad-command="formatBlock" aria-label="Text style"><option value="p">Paragraph</option><option value="h2">Heading</option><option value="h3">Subheading</option><option value="blockquote">Quote</option></select>'
            '<button type="button" data-ad-command="insertUnorderedList">Bullets</button>'
            '<button type="button" data-ad-command="insertOrderedList">Numbered</button>'
            '<select data-ad-command="justify" aria-label="Text alignment"><option value="left">Left</option><option value="center">Center</option><option value="right">Right</option><option value="full">Justify</option></select>'
            '<button type="button" data-ad-command="strikeThrough"><s>S</s></button>'
            '<select data-ad-command="formatBlock" aria-label="Text style">'
            '<option value="p">Paragraph</option><option value="h2">Heading</option>'
            '<option value="h3">Subheading</option><option value="blockquote">Quote</option></select>'
            '<button type="button" data-ad-command="insertUnorderedList">Bullets</button>'
            '<button type="button" data-ad-command="insertOrderedList">Numbered</button>'
            '<select data-ad-command="justify" aria-label="Text alignment">'
            '<option value="left">Left</option><option value="center">Center</option>'
            '<option value="right">Right</option><option value="full">Justify</option></select>'
            '<label>Text <input type="color" data-ad-command="color" value="#ffffff"></label>'
            '<label>Background <input type="color" data-ad-command="background" value="#000000"></label>'
            '<label>Size <input type="number" data-ad-command="size" value="16" min="1" max="2000" step="1"> px</label>'
            '<button type="button" data-ad-command="size-apply">Apply px</button>'
            '<input type="url" data-ad-link-url placeholder="https://example.com" aria-label="Link URL">'
            '<button type="button" data-ad-command="link">Add link</button>'
            '<button type="button" data-ad-command="removeFormat">Clear format</button>'
            '<button type="button" data-ad-command="removeFormat">Clear format</button>'
            '<button type="button" data-ad-command="insertImage">Image</button>'
            '<button type="button" data-ad-command="apply" class="advertisement-editor-apply">Apply</button>'
            '</div>'
            f'<div id="{conditional_escape(editor_id)}" class="advertisement-editor-content" contenteditable="true">{sanitize_html(value)}</div>'
            f'<textarea name="{conditional_escape(name)}" id="{conditional_escape(widget_id)}" hidden>{conditional_escape(value)}</textarea>'
            '</div>'
        )

class JobAdminForm(forms.ModelForm):
    category = forms.ModelChoiceField(
        queryset=JobCategory.objects.all(),
        empty_label='Select category',
        required=False,
        label='Category',
    )

    class Meta:
        model = Job
        fields = '__all__'


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    form = JobAdminForm
    list_display = ('title', 'company_name', 'category', 'job_type', 'display_mode', 'is_featured', 'is_urgent')
    list_filter = ('category', 'job_type', 'experience_level', 'is_featured', 'is_urgent')
    search_fields = ('title', 'company_name', 'category__name')
    list_editable = ('display_mode', 'is_featured', 'is_urgent')
    readonly_fields = ('views_count', 'clicks_count')
    list_per_page = 20

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == 'display_mode':
            formfield.help_text = 'Choose Previous, Work, or List for this job, or inherit the Website Settings default.'
            return formfield
        if db_field.name.startswith('description'):
            formfield.widget = AdvertisementTextWidget()
            return formfield
        if db_field.name == 'salary':
            formfield.help_text = 'For example: Negotiable, 15,000 ETB.'
        elif db_field.name == 'deadline':
            formfield.input_formats = ['%d/%m/%Y', '%Y-%m-%d', '%m/%d/%Y']
            formfield.widget.format = '%d/%m/%Y'
            formfield.widget.attrs.update({
                'placeholder': 'DD/MM/YYYY',
                'autocomplete': 'off',
            })
            formfield.help_text = 'Use DD/MM/YYYY, for example 21/11/2026.'
        return formfield


@admin.register(Advertisement)
class AdvertisementAdmin(admin.ModelAdmin):
    list_display = ('title', 'position', 'display_format', 'is_active', 'views_count', 'clicks_count', 'click_through_rate_display')
    list_filter = ('position', 'display_format', 'is_active')
    list_editable = ('is_active',)
    readonly_fields = ('views_count', 'clicks_count', 'click_through_rate_display')
    fieldsets = (
        ('Basic settings', {
            'fields': ('title', 'position', 'display_format', 'is_active'),
        }),
        ('Advertisement media', {
            'fields': ('banner_image', 'video_url', 'adsense_code', 'destination_link'),
        }),
        ('Text formatting', {
            'fields': ('text_color', 'text_size', 'text_placement', 'ad_text'),
        }),
        ('Image sizing', {
            'fields': ('size_mode', 'image_width', 'image_height'),
        }),
        ('Analytics', {
            'fields': ('views_count', 'clicks_count', 'click_through_rate_display'),
        }),
    )

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == 'adsense_code':
            formfield.help_text = 'Enter the Google AdSense script code here.'
        elif db_field.name == 'ad_text':
            formfield.widget = AdvertisementTextWidget()
            formfield.help_text = 'Select text, then use the toolbar to set color, background, size, or add a link.'
        elif db_field.name == 'destination_link':
            formfield.help_text = 'External domains must be listed in DJANGO_ADVERTISEMENT_ALLOWED_HOSTS.'
        elif db_field.name == 'text_color':
            formfield.widget = forms.TextInput(attrs={'type': 'color'})
        elif db_field.name == 'text_size':
            formfield.help_text = 'Text size in pixels.'
        elif db_field.name in {'image_width', 'image_height'}:
            formfield.help_text = 'Used only when size mode is Manual.'
        return formfield

    @admin.display(description='CTR')
    def click_through_rate_display(self, obj):
        return f'{obj.click_through_rate:.2f}%'

    def changelist_view(self, request, extra_context=None):
        advertisements = Advertisement.objects.all()
        views = sum(ad.views_count for ad in advertisements)
        clicks = sum(ad.clicks_count for ad in advertisements)
        position_stats = []
        for position_value, position_label in Advertisement.POSITION_CHOICES:
            position_ads = advertisements.filter(position=position_value)
            position_views = sum(ad.views_count for ad in position_ads)
            position_clicks = sum(ad.clicks_count for ad in position_ads)
            position_stats.append({
                'label': position_label,
                'views': position_views,
                'clicks': position_clicks,
                'ctr': (position_clicks / position_views * 100) if position_views else 0,
            })
        extra_context = extra_context or {}
        extra_context['analytics_summary'] = {
            'advertisements': advertisements.count(),
            'active': advertisements.filter(is_active=True).count(),
            'views': views,
            'clicks': clicks,
            'ctr': (clicks / views * 100) if views else 0,
            'advertisements_data': [
                {
                    'label': ad.title,
                    'position': ad.get_position_display(),
                    'views': ad.views_count,
                    'clicks': ad.clicks_count,
                    'ctr': ad.click_through_rate,
                }
                for ad in advertisements
            ],
            'position_data': position_stats,
        }
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(SiteSetting)
class SiteSettingAdmin(admin.ModelAdmin):
    form = SiteSettingAdminForm
    list_display = ('site_name', 'job_display_mode', 'contact_email', 'contact_phone', 'show_hero', 'show_language_switcher', 'public_preview')
    list_editable = ('job_display_mode',)
    fieldsets = (
        ('Branding', {
            'fields': ('site_name', 'site_logo', 'site_favicon', 'header_text', 'footer_text'),
        }),
        ('Top bar and background', {
            'fields': ('top_bar_text', 'background_text', 'background_image'),
            'description': 'Control the text and image shown in the public website header and background. The uploaded image is used as a responsive background on the public site.',
        }),
        ('Contact details', {
            'fields': (
                'contact_email', 'contact_phone', 'contact_action_enabled',
                'contact_action_label', 'contact_action_url', 'contact_submit_enabled',
            ),
        }),
        ('Homepage hero', {
            'fields': ('hero_badge', 'hero_title', 'hero_description', 'show_hero'),
        }),
        ('Theme and layout', {
            'fields': (
                'primary_color', 'secondary_color', 'background_color', 'text_color',
                'font_family', 'corner_radius',
            ),
        }),
        ('Dashboard customization', {
            'fields': (
                'admin_sidebar_color', 'admin_workspace_color', 'admin_primary_color',
                'admin_secondary_color', 'admin_accent_color', 'admin_text_color',
                'admin_background_mode', 'admin_background_image', 'admin_background_video',
                'admin_background_3d', 'admin_background_4k',
                'job_paper_width', 'job_paper_height', 'job_paper_background_color',
                'job_paper_background_image', 'job_paper_background_video',
            ),
            'description': 'Control dashboard colors, background media, and the public job detail paper dimensions. The selected background mode controls which dashboard media is active; the image remains the fallback.',
        }),
        ('Visibility controls', {
            'fields': (
                'show_about_contact_links', 'show_language_switcher', 'show_footer_links',
                'show_search_filters', 'show_job_stats', 'show_advertisements',
                'job_display_mode',
            ),
            'description': 'These controls remain available independently. Job display mode selects the site-wide fallback; individual jobs can override it from the Job admin.',
        }),
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        cache.delete('jobs:global_context')

    @admin.display(description='Public preview')
    def public_preview(self, obj):
        return format_html(
            '<a class="button" href="{}" target="_blank" rel="noopener">Open site</a>',
            reverse('home'),
        )

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name in {'top_bar_text', 'background_text', 'footer_text', 'hero_description'}:
            formfield.widget = AdvertisementTextWidget()
            return formfield
        labels = {
            'site_name': 'Website name',
            'site_logo': 'Website logo',
            'site_favicon': 'Favicon',
            'footer_text': 'Footer text',
            'contact_email': 'Contact email',
            'contact_phone': 'Contact phone',
        }
        if db_field.name in labels:
            formfield.label = labels[db_field.name]
        return formfield

    # በአንድ ጊዜ ከአንድ በላይ Setting እንዳይፈጠር ለመከላከል
    def has_add_permission(self, request):
        if SiteSetting.objects.exists():
            return False
        return super().has_add_permission(request)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        cache.delete('jobs:global_context')


@admin.register(LegalPage)
class LegalPageAdmin(admin.ModelAdmin):
    list_display = ('title', 'page_type', 'placement_location', 'public_page', 'contact_status', 'text_color', 'font_size', 'updated_at')
    list_filter = ('page_type', 'placement_location')
    search_fields = ('title', 'content')
    fieldsets = (
        ('Page identity', {'fields': ('page_type', 'title', 'placement_location')}),
        ('Editable content', {'fields': ('content',)}),
        ('Appearance', {'fields': ('text_color', 'font_size')}),
        ('Contact controls', {'fields': ('contact_enabled',)}),
        ('Audit', {'fields': ('updated_at',)}),
    )
    readonly_fields = ('updated_at',)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == 'content':
            formfield.widget = AdvertisementTextWidget()
        return formfield

    @admin.display(description='Public page')
    def public_page(self, obj):
        url = reverse('custom_page', args=[obj.page_type])
        return format_html('<a href="{}" target="_blank" rel="noopener">Open page</a>', url)

    @admin.display(description='Contact form')
    def contact_status(self, obj):
        if obj.page_type != 'contact':
            return 'Not applicable'
        return 'Enabled' if obj.contact_enabled else 'Disabled'

    def has_add_permission(self, request):
        return super().has_add_permission(request)

    def save_model(self, request, obj, form, change):
        obj.updated_at = timezone.now()
        super().save_model(request, obj, form, change)
        cache.delete('jobs:global_context')


@admin.register(CustomPage)
class CustomPageAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'placement_location', 'public_page', 'updated_at')
    list_filter = ('placement_location',)
    search_fields = ('title', 'slug', 'content')
    readonly_fields = ('updated_at',)
    fieldsets = (
        ('Page identity', {'fields': ('title', 'slug_mode', 'slug', 'placement_location')}),
        ('Rich content', {'fields': ('content',)}),
        ('Appearance', {'fields': ('text_color', 'font_size')}),
        ('Audit', {'fields': ('updated_at',)}),
    )

    @admin.display(description='Public page')
    def public_page(self, obj):
        url = reverse('custom_page', args=[obj.slug])
        return format_html('<a href="{}" target="_blank" rel="noopener">Open page</a>', url)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == 'content':
            formfield.widget = AdvertisementTextWidget(attrs={
                'rows': 18,
                'class': 'vLargeTextField custom-page-rich-text',
                'placeholder': '<h2>Page heading</h2>\n<p>Page content...</p>',
            })
        return formfield

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        cache.delete('jobs:global_context')


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    class Media:
        css = {'all': ('jobs/css/contact_admin.css',)}

    change_list_template = 'admin/jobs/contactmessage/change_list.html'
    list_display = ('subject', 'name', 'email', 'submitted_at', 'read_status', 'reply_status', 'action_links')
    list_filter = ('is_read', 'submitted_at')
    search_fields = ('name', 'email', 'subject', 'message')
    readonly_fields = ('name', 'email', 'subject', 'message', 'submitted_at', 'reply_message', 'replied_at')

    def has_add_permission(self, request):
        return False

    def changelist_view(self, request, extra_context=None):
        site_setting = SiteSetting.objects.first()
        contact_page = LegalPage.objects.filter(page_type='contact').first()
        extra_context = extra_context or {}
        extra_context.update({
            'compose_email_url': reverse('admin:jobs_contactmessage_compose_email'),
            'outbox_url': reverse('admin:jobs_sentemail_changelist'),
            'contact_button_toggle_url': reverse('admin:jobs_contactmessage_toggle_contact_button'),
            'contact_button_toggle_label': (
                'Hide Send button'
                if site_setting and site_setting.contact_submit_enabled
                else 'Show Send button'
            ),
            'contact_page_toggle_url': reverse('admin:jobs_contactmessage_toggle_contact_page'),
            'contact_page_toggle_label': (
                'Hide Contact page'
                if contact_page and contact_page.contact_enabled
                else 'Show Contact page'
            ),
        })
        return super().changelist_view(request, extra_context=extra_context)

    @admin.display(description='Read status')
    def read_status(self, obj):
        status = 'Read' if obj.is_read else 'Unread'
        css_class = 'contact-status-read' if obj.is_read else 'contact-status-unread'
        return format_html('<span class="{}">{}</span>', css_class, status)

    @admin.display(description='Reply status')
    def reply_status(self, obj):
        return 'Replied' if obj.replied_at else 'Awaiting reply'

    @admin.display(description='Action')
    def action_links(self, obj):
        view_url = reverse('admin:jobs_contactmessage_view', args=[obj.pk])
        reply_url = reverse('admin:jobs_contactmessage_reply', args=[obj.pk])
        toggle_url = reverse('admin:jobs_contactmessage_toggle_read', args=[obj.pk])
        site_setting = SiteSetting.objects.first()
        settings_url = (
            reverse('admin:jobs_sitesetting_change', args=[site_setting.pk])
            if site_setting
            else reverse('admin:jobs_sitesetting_add')
        )
        toggle_label = 'Mark unread' if obj.is_read else 'Mark read'
        contact_button_url = reverse('admin:jobs_contactmessage_toggle_contact_button')
        contact_button_label = 'Hide Send button' if site_setting and site_setting.contact_submit_enabled else 'Show Send button'
        contact_page = LegalPage.objects.filter(page_type='contact').first()
        contact_page_url = reverse('admin:jobs_contactmessage_toggle_contact_page')
        contact_page_label = 'Hide Contact page' if contact_page and contact_page.contact_enabled else 'Show Contact page'
        return format_html(
            '<span class="contact-actions">'
            '<a class="button contact-action-view" href="{}">View</a>'
            '<a class="button contact-action-reply" href="{}">Reply</a>'
            '<a class="button contact-action-toggle" href="{}">{}</a>'
            '<a class="button contact-action-email" href="mailto:{}">Email</a>'
            '<a class="button contact-action-settings" href="{}">Contact button settings</a>'
            '<a class="button contact-action-toggle" href="{}">{}</a>'
            '<a class="button contact-action-settings" href="{}">{}</a>'
            '</span>',
            view_url,
            reply_url,
            toggle_url,
            toggle_label,
            obj.email,
            settings_url,
            contact_button_url,
            contact_button_label,
            contact_page_url,
            contact_page_label,
        )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'compose-email/',
                self.admin_site.admin_view(self.compose_email_view),
                name='jobs_contactmessage_compose_email',
            ),
            path(
                '<int:object_id>/reply/',
                self.admin_site.admin_view(self.reply_view),
                name='jobs_contactmessage_reply',
            ),
            path(
                '<int:object_id>/toggle-read/',
                self.admin_site.admin_view(self.toggle_read_view),
                name='jobs_contactmessage_toggle_read',
            ),
            path(
                '<int:object_id>/view-message/',
                self.admin_site.admin_view(self.view_message),
                name='jobs_contactmessage_view',
            ),
            path(
                'toggle-contact-button/',
                self.admin_site.admin_view(self.toggle_contact_button_view),
                name='jobs_contactmessage_toggle_contact_button',
            ),
            path(
                'toggle-contact-page/',
                self.admin_site.admin_view(self.toggle_contact_page_view),
                name='jobs_contactmessage_toggle_contact_page',
            ),
        ]
        return custom_urls + urls

    def compose_email_view(self, request):
        if request.method == 'POST':
            form = AdminEmailForm(request.POST)
            if form.is_valid():
                try:
                    message_html = sanitize_html(form.cleaned_data['message'])
                    email = EmailMultiAlternatives(
                        subject=form.cleaned_data['subject'],
                        body=strip_tags(message_html),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        to=[form.cleaned_data['recipient']],
                    )
                    email.attach_alternative(message_html, 'text/html')
                    uploaded_files = form.cleaned_data['attachments'] or request.FILES.getlist('attachments')
                    for uploaded_file in uploaded_files:
                        email.attach(
                            uploaded_file.name,
                            uploaded_file.read(),
                            uploaded_file.content_type,
                        )
                    sent_count = email.send()
                except Exception as error:
                    sent_count = 0
                    error_message = f'Email could not be sent: {error}'
                else:
                    error_message = None
                if sent_count:
                    SentEmail.objects.create(
                        recipient=form.cleaned_data['recipient'],
                        subject=form.cleaned_data['subject'],
                        message=message_html,
                        attachment_names=[uploaded_file.name for uploaded_file in uploaded_files],
                    )
                    self.message_user(request, 'Email sent successfully.', messages.SUCCESS)
                    return HttpResponseRedirect(reverse('admin:jobs_contactmessage_changelist'))
                if not error_message:
                    error_message = (
                        'Email was not delivered. Configure SMTP settings before sending email.'
                    )
                self.message_user(request, error_message, messages.ERROR)
        else:
            form = AdminEmailForm()

        return render(
            request,
            'admin/jobs/contactmessage/compose_email.html',
            {
                **self.admin_site.each_context(request),
                'opts': self.model._meta,
                'form': form,
                'title': 'Write email',
                'DEFAULT_FROM_EMAIL': settings.DEFAULT_FROM_EMAIL,
            },
        )

    def toggle_read_view(self, request, object_id):
        contact_message = get_object_or_404(ContactMessage, pk=object_id)
        contact_message.is_read = not contact_message.is_read
        contact_message.save(update_fields=['is_read'])
        self.message_user(
            request,
            f'Message marked {"read" if contact_message.is_read else "unread"}.',
            messages.SUCCESS,
        )
        return HttpResponseRedirect(reverse('admin:jobs_contactmessage_changelist'))

    def view_message(self, request, object_id):
        contact_message = get_object_or_404(ContactMessage, pk=object_id)
        if not contact_message.is_read:
            contact_message.is_read = True
            contact_message.save(update_fields=['is_read'])
        return HttpResponseRedirect(
            reverse('admin:jobs_contactmessage_change', args=[contact_message.pk])
        )

    def toggle_contact_button_view(self, request):
        site_setting = SiteSetting.objects.first()
        if site_setting is None:
            site_setting = SiteSetting.objects.create()
        site_setting.contact_submit_enabled = not site_setting.contact_submit_enabled
        site_setting.save(update_fields=['contact_submit_enabled'])
        cache.delete('jobs:global_context')
        status = 'shown' if site_setting.contact_submit_enabled else 'hidden'
        self.message_user(request, f'Send message button {status}.', messages.SUCCESS)
        return HttpResponseRedirect(reverse('admin:jobs_contactmessage_changelist'))

    def toggle_contact_page_view(self, request):
        contact_page = LegalPage.objects.filter(page_type='contact').first()
        if contact_page is None:
            contact_page = LegalPage.objects.create(
                page_type='contact',
                title='Contact Us',
                content='Contact us using the form below.',
            )
        contact_page.contact_enabled = not contact_page.contact_enabled
        contact_page.save(update_fields=['contact_enabled', 'updated_at'])
        status = 'shown' if contact_page.contact_enabled else 'hidden'
        self.message_user(request, f'Contact page {status}.', messages.SUCCESS)
        return HttpResponseRedirect(reverse('admin:jobs_contactmessage_changelist'))

    def reply_view(self, request, object_id):
        contact_message = get_object_or_404(ContactMessage, pk=object_id)
        if request.method == 'POST':
            form = ContactReplyForm(request.POST)
            if form.is_valid():
                email_error = None
                try:
                    sent_count = send_mail(
                        subject=form.cleaned_data['subject'],
                        message=form.cleaned_data['message'],
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[contact_message.email],
                    )
                except Exception as error:
                    email_error = f'Email could not be sent: {error}'
                    sent_count = 0
                if not sent_count:
                    if email_error:
                        error_message = email_error
                    elif settings.MAILERS['default']['BACKEND'].endswith('filebased.EmailBackend'):
                        error_message = (
                            'Reply was not delivered because the file email backend is enabled. '
                            'Configure SMTP environment variables to send real email.'
                        )
                    else:
                        error_message = 'The email backend did not send the reply. Check your SMTP settings.'
                    self.message_user(
                        request,
                        error_message,
                        messages.ERROR,
                    )
                    return render(
                        request,
                        'admin/jobs/contactmessage/reply.html',
                        {
                            **self.admin_site.each_context(request),
                            'opts': self.model._meta,
                            'original': contact_message,
                            'form': form,
                            'DEFAULT_FROM_EMAIL': settings.DEFAULT_FROM_EMAIL,
                            'title': f'Reply to {contact_message.name}',
                        },
                    )
                contact_message.reply_message = form.cleaned_data['message']
                contact_message.replied_at = timezone.now()
                contact_message.is_read = True
                contact_message.save(update_fields=['reply_message', 'replied_at', 'is_read'])
                SentEmail.objects.create(
                    recipient=contact_message.email,
                    subject=form.cleaned_data['subject'],
                    message=form.cleaned_data['message'],
                )
                self.message_user(request, 'Reply sent and saved successfully.', messages.SUCCESS)
                return HttpResponseRedirect(reverse('admin:jobs_contactmessage_changelist'))
        else:
            form = ContactReplyForm(initial={'subject': f'Re: {contact_message.subject}'})

        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'original': contact_message,
            'form': form,
            'DEFAULT_FROM_EMAIL': settings.DEFAULT_FROM_EMAIL,
            'title': f'Reply to {contact_message.name}',
        }
        return render(request, 'admin/jobs/contactmessage/reply.html', context)


@admin.register(SentEmail)
class SentEmailAdmin(admin.ModelAdmin):
    list_display = ('subject', 'recipient', 'sent_at', 'attachment_summary')
    list_filter = ('sent_at',)
    search_fields = ('recipient', 'subject', 'message')
    readonly_fields = ('recipient', 'subject', 'message', 'attachment_names', 'sent_at')

    @admin.display(description='Attachments')
    def attachment_summary(self, obj):
        return ', '.join(obj.attachment_names) if obj.attachment_names else 'None'