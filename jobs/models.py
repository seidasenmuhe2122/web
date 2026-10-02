from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.utils.text import slugify
from django.utils import timezone, translation
from django.utils.translation import gettext_lazy as _
from ckeditor.fields import RichTextField

class Job(models.Model):
    DISPLAY_MODE_CHOICES = [
        ('site', 'Use site default'),
        ('previous', 'Previous display'),
        ('work', 'Work display'),
        ('list', 'List display'),
    ]

    JOB_TYPE_CHOICES = [
        ('Full-time', _('Full-time')),
        ('Part-time', _('Part-time')),
        ('Remote', _('Remote')),
        ('Contract', _('Contract')),
        ('Internship', _('Internship')),
    ]

    EXP_LEVEL_CHOICES = [
        ('Fresh Graduate', _('Fresh Graduate')),
        ('1-3 Years', _('1-3 Years')),
        ('3-5 Years', _('3-5 Years')),
        ('5+ Years', _('5+ Years')),
    ]

    title = models.CharField(max_length=200)
    company_name = models.CharField(max_length=200)
    company_logo = models.ImageField(upload_to='company_logos/', blank=True, null=True)
    location = models.CharField(max_length=100)
    job_type = models.CharField(max_length=20, choices=JOB_TYPE_CHOICES, default='Full-time')
    display_mode = models.CharField(
        max_length=10,
        choices=DISPLAY_MODE_CHOICES,
        default='site',
        help_text='Choose the display for this job, or inherit the Website Settings default.',
    )
    experience_level = models.CharField(max_length=30, choices=EXP_LEVEL_CHOICES, default='Fresh Graduate')
    category = models.ForeignKey(
        'JobCategory',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='jobs',
        help_text='Select the job category.',
    )
    salary = models.CharField(max_length=100, blank=True, help_text="ለአብነት፡ Negotiable, 15,000 ETB...")
    vacancies = models.PositiveIntegerField(default=1)
    
    is_featured = models.BooleanField(default=False)
    is_urgent = models.BooleanField(default=False)

    description = models.TextField()
    description_en = models.TextField(blank=True)
    description_am = models.TextField(blank=True)
    description_aa = models.TextField(blank=True)
    description_om = models.TextField(blank=True)
    description_fr = models.TextField(blank=True)
    description_ar = models.TextField(blank=True)
    description_es = models.TextField(blank=True)

    apply_link = models.URLField(max_length=500, blank=True)
    source_name = models.CharField(max_length=200, blank=True)
    source_url = models.URLField(max_length=1500, blank=True)
    original_content = models.TextField(blank=True)
    content_hash = models.CharField(max_length=64, blank=True, db_index=True)
    normalized_title = models.CharField(max_length=255, blank=True, db_index=True)
    normalized_company = models.CharField(max_length=255, blank=True, db_index=True)
    normalized_location = models.CharField(max_length=255, blank=True, db_index=True)
    auto_imported = models.BooleanField(default=False, db_index=True)
    telegram_notification_sent_at = models.DateTimeField(blank=True, null=True)
    # AI classification fields for filtering and Telegram routing
    organization_type = models.CharField(max_length=80, blank=True, db_index=True)
    education_level = models.CharField(max_length=80, blank=True, db_index=True)
    employment_type = models.CharField(max_length=50, blank=True, db_index=True)
    work_mode = models.CharField(max_length=30, blank=True, db_index=True)
    region = models.CharField(max_length=100, blank=True, db_index=True)
    country = models.CharField(max_length=100, blank=True, db_index=True)
    languages_required = models.JSONField(default=list, blank=True)
    keywords = models.JSONField(default=list, blank=True)
    salary_min = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    salary_max = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    salary_currency = models.CharField(max_length=10, blank=True)


    TELEGRAM_DESTINATION_MODES = [
        ('auto', 'Automatic source routing'),
        ('all', 'All enabled destinations'),
        ('selected', 'Selected destinations'),
    ]

    source = models.ForeignKey(
        'JobSource',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='jobs',
    )
    telegram_destination_mode = models.CharField(
        max_length=10,
        choices=TELEGRAM_DESTINATION_MODES,
        default='auto',
    )
    telegram_destinations = models.ManyToManyField(
        'TelegramDestination',
        blank=True,
        related_name='jobs',
    )

    deadline = models.DateField(blank=True, null=True)
    posted_date = models.DateTimeField(auto_now_add=True)

    # View እና Click መቆጣጠሪያ
    views_count = models.PositiveIntegerField(default=0)
    clicks_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-posted_date']

    def get_description_for_language(self, language_code=None):
        requested_language = (language_code or translation.get_language() or settings.LANGUAGE_CODE).split('-')[0]
        preferred_codes = [requested_language, settings.LANGUAGE_CODE]

        for code in preferred_codes:
            translated_description = getattr(self, f'description_{code}', None)
            if translated_description:
                return translated_description

        return self.description or ''

    @property
    def translated_description(self):
        return self.get_description_for_language()

    def __str__(self):
        return f"{self.title} - {self.company_name}"


class BlogPost(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, blank=True)
    excerpt = models.TextField(blank=True, help_text='Short summary shown on blog cards.')
    content = RichTextField(help_text='Full article content with formatting tools.')
    cover_image = models.ImageField(upload_to='blog/', blank=True, null=True)
    author = models.CharField(max_length=120, blank=True, default='Admin')
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Blog Post'
        verbose_name_plural = 'Blog Posts'

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)[:80] or 'blog-post'
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class JobCategory(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, blank=True)
    description = RichTextField(blank=True, help_text='Short category description with formatting.')
    icon = models.CharField(max_length=50, blank=True, default='fa-briefcase', help_text='Font Awesome icon class, e.g. fa-briefcase.')
    accent_color = models.CharField(max_length=7, default='#63d9ff', blank=True, validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')])
    is_featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Job Category'
        verbose_name_plural = 'Job Categories'

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:80] or 'category'
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# AdSense እና Banner ማስታወቂያዎች መቆጣጠሪያ
class Advertisement(models.Model):
    FORMAT_CHOICES = [
        ('auto', 'Auto (recommended)'),
        ('banner', 'Banner image'),
        ('video', 'Video'),
        ('full_page', 'Full page'),
        ('html', 'HTML / AdSense'),
    ]
    POSITION_CHOICES = [
        ('auto', 'Auto Placement'),
        ('header', 'Header Banner'),
        ('sidebar', 'Sidebar Banner'),
        ('inside_job', 'Inside Job Details'),
        ('footer', 'Footer Banner'),
        ('right_top', 'Right Top'),
        ('right_middle', 'Right Middle'),
        ('right_bottom', 'Right Bottom'),
        ('left_top', 'Left Top'),
        ('left_middle', 'Left Middle'),
        ('left_bottom', 'Left Bottom'),
    ]
    SIZE_MODE_CHOICES = [
        ('auto', 'Auto (responsive)'),
        ('manual', 'Manual'),
    ]
    TEXT_PLACEMENT_CHOICES = [
        ('below', 'Below advertisement'),
        ('above', 'Above advertisement'),
        ('left', 'Left of advertisement'),
        ('right', 'Right of advertisement'),
    ]

    title = models.CharField(max_length=100)
    position = models.CharField(max_length=20, choices=POSITION_CHOICES, default='header')
    display_format = models.CharField(max_length=20, choices=FORMAT_CHOICES, default='auto')
    adsense_code = models.TextField(blank=True, help_text="የGoogle AdSense Script ኮድ እዚህ ያስገቡ")
    ad_text = models.TextField(blank=True, verbose_name='Advertisement text')
    text_color = models.CharField(max_length=7, default='#ffffff', verbose_name='Text color')
    text_size = models.PositiveIntegerField(default=16, verbose_name='Text size (px)')
    text_placement = models.CharField(max_length=10, choices=TEXT_PLACEMENT_CHOICES, default='below')
    banner_image = models.ImageField(upload_to='ads/', blank=True, null=True)
    size_mode = models.CharField(max_length=10, choices=SIZE_MODE_CHOICES, default='auto')
    image_width = models.PositiveIntegerField(blank=True, null=True, verbose_name='Manual width (px)')
    image_height = models.PositiveIntegerField(blank=True, null=True, verbose_name='Manual height (px)')
    video_url = models.URLField(blank=True, help_text='Direct video URL for MP4/WebM content.')
    destination_link = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    views_count = models.PositiveIntegerField(default=0)
    clicks_count = models.PositiveIntegerField(default=0)

    @property
    def click_through_rate(self):
        if not self.views_count:
            return 0
        return (self.clicks_count / self.views_count) * 100

    @property
    def effective_format(self):
        if self.display_format != 'auto':
            return self.display_format
        if self.adsense_code:
            return 'html'
        if self.video_url:
            return 'video'
        if self.banner_image:
            return 'banner'
        return 'html'

    @property
    def effective_position(self):
        return 'header' if self.position == 'auto' else self.position

    def __str__(self):
        return f"{self.title} ({self.position})"
# የዌብሳይት ስም፣ ሎጎ እና ጠቅላላ መረጃዎች መቆጣጠሪያ
class SiteSetting(models.Model):
    ADMIN_BACKGROUND_MODE_CHOICES = [
        ('previous', 'Previous dashboard background'),
        ('image', 'Image'),
        ('video', 'Video'),
        ('3d', '3D video'),
        ('4k', '4K video'),
    ]
    JOB_DISPLAY_MODE_CHOICES = [
        ('previous', 'Previous display'),
        ('work', 'Work display'),
        ('list', 'List display'),
    ]

    site_name = models.CharField(max_length=100, default="AFRI JOB ETHIOPIA", verbose_name="Website name")
    site_logo = models.ImageField(upload_to='site/', blank=True, null=True, verbose_name="Website logo")
    site_favicon = models.ImageField(upload_to='site/', blank=True, null=True, verbose_name="Website favicon")
    header_text = models.CharField(max_length=200, blank=True, default='AFRI JOB ETHIOPIA')
    top_bar_text = models.TextField(blank=True, default='Find your next opportunity in Ethiopia')
    background_text = models.TextField(blank=True, default='AFRI JOB ETHIOPIA')
    background_image = models.ImageField(upload_to='site/backgrounds/', blank=True, null=True)
    footer_text = models.TextField(blank=True, verbose_name="Footer text")
    contact_email = models.EmailField(blank=True, verbose_name="Contact email")
    contact_phone = models.CharField(max_length=20, blank=True, verbose_name="Contact phone")
    contact_action_enabled = models.BooleanField(default=False, verbose_name='Show contact action button')
    contact_action_label = models.CharField(max_length=80, blank=True, default='Contact us directly')
    contact_action_url = models.URLField(blank=True, verbose_name='Contact action URL')
    contact_submit_enabled = models.BooleanField(default=True, verbose_name='Show Send message button')
    hero_badge = models.CharField(max_length=120, default='Premium hiring platform')
    hero_title = models.CharField(max_length=200, default='Find your next opportunity')
    hero_description = models.TextField(
        default='Discover top jobs, connect with employers, and grow your career with a smarter job search experience.'
    )
    show_hero = models.BooleanField(default=True)
    show_about_contact_links = models.BooleanField(default=True)
    show_language_switcher = models.BooleanField(default=True)
    show_footer_links = models.BooleanField(default=True)
    show_search_filters = models.BooleanField(default=True)
    show_job_stats = models.BooleanField(default=True)
    show_advertisements = models.BooleanField(default=True)
    job_display_mode = models.CharField(max_length=10, choices=JOB_DISPLAY_MODE_CHOICES, default='work')
    primary_color = models.CharField(
        max_length=7,
        default='#38bdf8',
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
    )
    secondary_color = models.CharField(
        max_length=7,
        default='#a855f7',
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
    )
    background_color = models.CharField(
        max_length=7,
        default='#070b16',
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
    )
    text_color = models.CharField(
        max_length=7,
        default='#e0f2fe',
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
    )
    font_family = models.CharField(max_length=120, default='Segoe UI, Tahoma, sans-serif')
    corner_radius = models.PositiveSmallIntegerField(default=24, validators=[MinValueValidator(0), MaxValueValidator(40)])
    admin_sidebar_color = models.CharField(
        max_length=7,
        default='#070b16',
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
        verbose_name='Admin sidebar color',
    )
    admin_accent_color = models.CharField(
        max_length=7,
        default='#22d3ee',
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
        verbose_name='Admin accent color',
    )
    admin_workspace_color = models.CharField(
        max_length=7,
        default='#0b1120',
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
        verbose_name='Admin workspace color',
    )
    admin_primary_color = models.CharField(
        max_length=7,
        default='#38bdf8',
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
        verbose_name='Admin primary color',
    )
    admin_secondary_color = models.CharField(
        max_length=7,
        default='#a855f7',
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
        verbose_name='Admin secondary color',
    )
    admin_text_color = models.CharField(
        max_length=7,
        default='#e0f2fe',
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
        verbose_name='Admin text color',
    )
    admin_background_image = models.ImageField(upload_to='admin/backgrounds/', blank=True, null=True, verbose_name='Admin background image')
    admin_background_video = models.FileField(
        upload_to='admin/backgrounds/',
        blank=True,
        null=True,
        verbose_name='Admin background video',
        help_text='Upload an MP4 or WebM video. The image is used as the fallback.',
    )
    admin_background_mode = models.CharField(
        max_length=10,
        choices=ADMIN_BACKGROUND_MODE_CHOICES,
        default='image',
        verbose_name='Admin background mode',
    )
    admin_background_3d = models.FileField(
        upload_to='admin/backgrounds/3d/',
        blank=True,
        null=True,
        verbose_name='Admin 3D background video',
        help_text='Upload an MP4/WebM 3D animation.',
    )
    admin_background_4k = models.FileField(
        upload_to='admin/backgrounds/4k/',
        blank=True,
        null=True,
        verbose_name='Admin 4K background video',
        help_text='Upload an optimized MP4/WebM 4K video.',
    )
    job_paper_width = models.PositiveIntegerField(
        default=860,
        validators=[MinValueValidator(480), MaxValueValidator(1400)],
        verbose_name='Job paper width (px)',
        help_text='Desktop width of the public job detail paper. Use 480-1400 px.',
    )
    job_paper_height = models.PositiveIntegerField(
        default=700,
        validators=[MinValueValidator(320), MaxValueValidator(2400)],
        verbose_name='Job paper minimum height (px)',
        help_text='Minimum height of the public job detail paper. Use 320-2400 px.',
    )
    job_paper_background_color = models.CharField(
        max_length=7,
        default='#ffffff',
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
        verbose_name='Job paper background color',
    )
    job_paper_background_image = models.ImageField(
        upload_to='site/job-paper/',
        blank=True,
        null=True,
        verbose_name='Job paper background image',
    )
    job_paper_background_video = models.FileField(
        upload_to='site/job-paper/',
        blank=True,
        null=True,
        verbose_name='Job paper background video',
        help_text='Upload MP4 or WebM. The image and color remain fallbacks.',
    )

    class Meta:
        verbose_name = "Website setting"
        verbose_name_plural = "Website settings"

    def __str__(self):
        return self.site_name


class LegalPage(models.Model):
    PLACEMENT_CHOICES = [
        ('header', 'Header'),
        ('footer', 'Footer'),
        ('main_body', 'Main Body'),
        ('right_top', 'Right Top'),
        ('right_middle', 'Right Middle'),
        ('right_bottom', 'Right Bottom'),
        ('left_top', 'Left Top'),
        ('left_middle', 'Left Middle'),
        ('left_bottom', 'Left Bottom'),
    ]

    page_type = models.CharField(
        max_length=80,
        unique=True,
        help_text='Unique URL slug, such as about, privacy, faq, support, or contact.',
    )
    title = models.CharField(max_length=200)
    content = models.TextField(
        help_text='Rich text / HTML content. Unsafe tags and attributes are removed before display.'
    )
    text_color = models.CharField(
        max_length=7,
        default='#212529',
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
    )
    font_size = models.PositiveSmallIntegerField(
        default=16,
        validators=[MinValueValidator(10), MaxValueValidator(48)],
        help_text='Font size in pixels (10-48).',
    )
    placement_location = models.CharField(max_length=20, choices=PLACEMENT_CHOICES, default='footer')
    contact_enabled = models.BooleanField(
        default=True,
        help_text='When disabled, visitors cannot submit the Contact Us form.',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['page_type']
        verbose_name = 'Legal Page'
        verbose_name_plural = 'Legal Pages'

    def save(self, *args, **kwargs):
        self.page_type = (self.page_type or '').strip().lower().replace(' ', '-')
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class CustomPage(models.Model):
    SLUG_MODE_CHOICES = [
        ('auto', 'Auto-generate from title'),
        ('manual', 'Enter manually'),
    ]
    PLACEMENT_CHOICES = [
        ('header', 'Header'),
        ('footer', 'Footer'),
        ('main_body', 'Main Body'),
        ('right_top', 'Right Top'),
        ('right_middle', 'Right Middle'),
        ('right_bottom', 'Right Bottom'),
        ('left_top', 'Left Top'),
        ('left_middle', 'Left Middle'),
        ('left_bottom', 'Left Bottom'),
    ]

    title = models.CharField(max_length=200)
    slug_mode = models.CharField(max_length=10, choices=SLUG_MODE_CHOICES, default='auto')
    slug = models.SlugField(max_length=80, unique=True, blank=True)
    content = models.TextField(
        help_text='Enter HTML content. Unsafe tags and attributes are removed before display.',
    )
    text_color = models.CharField(
        max_length=7,
        default='#212529',
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
    )
    font_size = models.PositiveSmallIntegerField(
        default=16,
        validators=[MinValueValidator(10), MaxValueValidator(48)],
        help_text='Font size in pixels (10-48).',
    )
    placement_location = models.CharField(max_length=20, choices=PLACEMENT_CHOICES, default='main_body')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['title']
        verbose_name = 'Custom Page'
        verbose_name_plural = 'Custom Pages'

    def clean(self):
        if self.slug_mode == 'manual' and not (self.slug or '').strip():
            raise ValidationError({'slug': 'Enter a slug when manual mode is selected.'})

    def save(self, *args, **kwargs):
        if self.slug_mode == 'auto':
            base_slug = slugify(self.title)[:80] or 'page'
            candidate = base_slug
            suffix = 2
            while type(self).objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                suffix_text = f'-{suffix}'
                candidate = f'{base_slug[:80 - len(suffix_text)]}{suffix_text}'
                suffix += 1
            self.slug = candidate
        else:
            self.slug = (self.slug or '').strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class ContactMessage(models.Model):
    name = models.CharField(max_length=120)
    email = models.EmailField()
    subject = models.CharField(max_length=200)
    message = models.TextField()
    submitted_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    reply_message = models.TextField(blank=True)
    replied_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-submitted_at']

    def __str__(self):
        return f'{self.subject} - {self.name}'


class SentEmail(models.Model):
    recipient = models.EmailField(verbose_name='Recipient')
    subject = models.CharField(max_length=255, verbose_name='Subject')
    message = models.TextField(verbose_name='Message')
    attachment_names = models.JSONField(default=list, blank=True)
    sent_at = models.DateTimeField(default=timezone.now, verbose_name='Sent at')

    class Meta:
        ordering = ['-sent_at']
        verbose_name = 'Sent email'
        verbose_name_plural = 'Sent emails'

    def __str__(self):
        return f'Sent to {self.recipient} - {self.subject}'


class JobSource(models.Model):
    SOURCE_TYPES = [('telegram','Telegram'), ('website','Website')]
    name = models.CharField(max_length=160, unique=True)
    source_type = models.CharField(max_length=20, choices=SOURCE_TYPES)
    enabled = models.BooleanField(default=True)
    interval_minutes = models.PositiveIntegerField(default=15)
    last_run_at = models.DateTimeField(blank=True, null=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class TelegramSource(models.Model):
    source = models.OneToOneField(JobSource, on_delete=models.CASCADE, related_name='telegram_config')
    channel = models.CharField(max_length=255, help_text='Username such as @channel or numeric channel ID.')
    fetch_images = models.BooleanField(default=False)
    max_messages_per_run = models.PositiveIntegerField(default=50)
    last_message_id = models.BigIntegerField(default=0)
    session_name = models.CharField(max_length=80, blank=True, default='afrijob')

    def __str__(self):
        return f'{self.source.name}: {self.channel}'


class WebsiteSource(models.Model):
    source = models.OneToOneField(JobSource, on_delete=models.CASCADE, related_name='website_config')
    url = models.URLField(max_length=1000)
    method = models.CharField(max_length=10, default='GET')
    headers_json = models.JSONField(default=dict, blank=True)
    listing_selector = models.CharField(max_length=300, blank=True, help_text='CSS selector for each job card. Leave blank to treat the page as one post.')
    fields_json = models.JSONField(default=dict, blank=True, help_text='CSS selectors: title, company, location, description, deadline, application_url.')
    max_items_per_run = models.PositiveIntegerField(default=30)
    timeout_seconds = models.PositiveIntegerField(default=20)

    def __str__(self):
        return f'{self.source.name}: {self.url}'


class TelegramDestination(models.Model):
    name = models.CharField(max_length=160, unique=True)
    channel_id = models.CharField(
        max_length=255,
        unique=True,
        help_text='Telegram channel username such as @mychannel or numeric channel ID.',
    )
    enabled = models.BooleanField(default=True)
    filters_json = models.JSONField(
        default=dict,
        blank=True,
        help_text='Destination filters: organization, education, experience, employment, region, country, category, work mode, keywords, salary, etc.',
    )
    allowed_sources = models.ManyToManyField(
        'JobSource',
        blank=True,
        related_name='telegram_destinations',
        help_text='Leave empty to allow jobs from all enabled sources.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def str(self):
        return f'{self.name} ({self.channel_id})'


class AutomationControl(models.Model):
    FREQUENCY_CHOICES = [
        (10, 'Every 10 minutes'),
        (15, 'Every 15 minutes'),
        (30, 'Every 30 minutes'),
        (60, 'Every 1 hour'),
        (0, 'Manual only'),
    ]

    enabled = models.BooleanField(default=True)
    frequency_minutes = models.PositiveIntegerField(
        choices=FREQUENCY_CHOICES,
        default=15,
    )
    daily_max_jobs = models.PositiveIntegerField(
        default=0,
        help_text='Maximum jobs to publish per day. 0 = unlimited.',
    )
    last_run_at = models.DateTimeField(blank=True, null=True)
    next_run_at = models.DateTimeField(blank=True, null=True)
    last_error = models.TextField(blank=True)
    active_run = models.ForeignKey(
        'AutomationRun',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='active_controls',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Automation Control'
        verbose_name_plural = 'Automation Control'

    def str(self):
        return 'AFRIJOB Automation Control'



class AutomationSchedule(models.Model):
    DAYS_OF_WEEK = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    ]

    name = models.CharField(max_length=160, unique=True)
    enabled = models.BooleanField(default=True)

    days_of_week = models.JSONField(
        default=list,
        blank=True,
        help_text='Use weekday numbers: 0=Monday ... 6=Sunday.',
    )

    start_time = models.TimeField()
    end_time = models.TimeField()

    max_jobs = models.PositiveIntegerField(
        default=5,
        help_text='Maximum jobs allowed during this schedule window.',
    )

    max_jobs_per_run = models.PositiveIntegerField(
        default=1,
        help_text='Maximum jobs to publish in one automation cycle.',
    )

    destinations = models.ManyToManyField(
        'TelegramDestination',
        blank=True,
        related_name='automation_schedules',
        help_text='Leave empty to use the job destination rules.',
    )

    filters_json = models.JSONField(
        default=dict,
        blank=True,
        help_text='Optional country, region, organization, category, keyword and other filters.',
    )

    last_run_at = models.DateTimeField(blank=True, null=True)
    jobs_published = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['start_time', 'name']
        verbose_name = 'Automation Schedule'
        verbose_name_plural = 'Automation Schedules'

    def str(self):
        return self.name


class RawJobPost(models.Model):
    STATUS_CHOICES = [
        ('new','New'), ('processing','Processing'), ('processed','Processed'),
        ('rejected','Rejected'), ('failed','Failed'), ('duplicate','Duplicate'),
    ]
    source = models.ForeignKey(JobSource, on_delete=models.SET_NULL, null=True, blank=True, related_name='raw_posts')
    external_id = models.CharField(max_length=255, blank=True, db_index=True)
    source_url = models.URLField(max_length=1500, blank=True)
    content = models.TextField()
    content_hash = models.CharField(max_length=64, db_index=True)
    discovered_at = models.DateTimeField(default=timezone.now, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new', db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    processed_at = models.DateTimeField(blank=True, null=True)
    job = models.ForeignKey(Job, on_delete=models.SET_NULL, null=True, blank=True, related_name='raw_posts')
    extracted_json = models.JSONField(default=dict, blank=True)
    rejection_reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-discovered_at']
        constraints = [models.UniqueConstraint(fields=['source','external_id'], name='uniq_raw_source_external')]

    def __str__(self):
        return f'{self.source or "Unknown"} / {self.external_id or self.pk}'


class JobProcessingLog(models.Model):
    STAGES = [('collect','Collect'),('ai','AI'),('validate','Validate'),('dedupe','Duplicate check'),('publish','Publish'),('telegram','Telegram'),('system','System')]
    STATUSES = [('started','Started'),('success','Success'),('failed','Failed'),('skipped','Skipped')]
    raw_post = models.ForeignKey(RawJobPost, on_delete=models.CASCADE, related_name='logs', null=True, blank=True)
    job = models.ForeignKey(Job, on_delete=models.SET_NULL, null=True, blank=True, related_name='processing_logs')
    provider = models.CharField(max_length=80, blank=True)
    stage = models.CharField(max_length=20, choices=STAGES)
    status = models.CharField(max_length=20, choices=STATUSES)
    message = models.TextField(blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']


class TelegramNotification(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sending', 'Sending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]

    job = models.ForeignKey(
        Job,
        on_delete=models.CASCADE,
        related_name='telegram_notifications',
    )
    destination = models.ForeignKey(
        TelegramDestination,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications',
    )
    channel_id = models.CharField(max_length=255)
    message_id = models.BigIntegerField(blank=True, null=True)
    message_text = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    last_attempt_at = models.DateTimeField(blank=True, null=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['job', 'destination'],
                name='uniq_telegram_notification_job_destination',
            )
        ]


class AutomationRun(models.Model):
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('running', 'Running'),
        ('success', 'Succeeded'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
    ]

    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(blank=True, null=True)
    command = models.CharField(max_length=120)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='queued', db_index=True)
    error_message = models.TextField(blank=True)
    collected = models.PositiveIntegerField(default=0)
    processed = models.PositiveIntegerField(default=0)
    published = models.PositiveIntegerField(default=0)
    rejected = models.PositiveIntegerField(default=0)
    duplicates = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    summary = models.TextField(blank=True)

    class Meta:
        ordering = ['-started_at']

