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

    apply_link = models.URLField(max_length=500)
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
        default='#63d9ff',
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
    )
    secondary_color = models.CharField(
        max_length=7,
        default='#8b5cf6',
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
    )
    background_color = models.CharField(
        max_length=7,
        default='#071421',
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
    )
    text_color = models.CharField(
        max_length=7,
        default='#edf6ff',
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
    )
    font_family = models.CharField(max_length=120, default='Segoe UI, Tahoma, sans-serif')
    corner_radius = models.PositiveSmallIntegerField(default=24, validators=[MinValueValidator(0), MaxValueValidator(40)])
    admin_sidebar_color = models.CharField(
        max_length=7,
        default='#20252d',
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
        verbose_name='Admin sidebar color',
    )
    admin_accent_color = models.CharField(
        max_length=7,
        default='#dbeafe',
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
        verbose_name='Admin accent color',
    )
    admin_workspace_color = models.CharField(
        max_length=7,
        default='#e7ecf1',
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a six-digit hexadecimal color.')],
        verbose_name='Admin workspace color',
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