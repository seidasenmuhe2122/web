from django import forms
from django.core.exceptions import ValidationError
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from html import unescape

from .models import ContactMessage
from .templatetags.security_tags import sanitize_html


class AdminRichTextWidget(forms.Textarea):
    class Media:
        js = ('jobs/js/advertisement_editor.js',)
        css = {'all': ('jobs/css/advertisement_editor.css',)}

    def render(self, name, value, attrs=None, renderer=None):
        attrs = attrs or {}
        widget_id = attrs.get('id', f'id_{name}')
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
            '<label>Text <input type="color" data-ad-command="color" value="#212529"></label>'
            '<label>Background <input type="color" data-ad-command="background" value="#ffffff"></label>'
            '<label>Size <input type="number" data-ad-command="size" value="16" min="1" max="2000" step="1"> px</label>'
            '<button type="button" data-ad-command="size-apply">Apply px</button>'
            '<input type="url" data-ad-link-url placeholder="https://example.com" aria-label="Link URL">'
            '<button type="button" data-ad-command="link">Add link</button>'
            '<button type="button" data-ad-command="removeFormat">Clear format</button>'
            '</div>'
            f'<div id="{conditional_escape(widget_id)}" class="advertisement-editor-content" contenteditable="true">{sanitize_html(value)}</div>'
            f'<textarea name="{conditional_escape(name)}" id="{conditional_escape(widget_id)}" hidden>{conditional_escape(value)}</textarea>'
            '</div>'
        )


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if not data:
            return []
        if isinstance(data, (list, tuple)):
            return [single_file_clean(file_data, initial) for file_data in data]
        return [single_file_clean(data, initial)]


class ContactMessageForm(forms.ModelForm):
    class Meta:
        model = ContactMessage
        fields = ('name', 'email', 'subject', 'message')
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': _('Your name')}),
            'email': forms.EmailInput(attrs={'placeholder': _('you@example.com')}),
            'subject': forms.TextInput(attrs={'placeholder': _('How can we help?')}),
            'message': forms.Textarea(attrs={'rows': 6, 'placeholder': _('Write your message here...')}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


class ContactReplyForm(forms.Form):
    subject = forms.CharField(max_length=200)
    message = forms.CharField(widget=forms.Textarea(attrs={'rows': 10}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


class AdminEmailForm(forms.Form):
    recipient = forms.EmailField(label='To')
    subject = forms.CharField(max_length=200)
    message = forms.CharField(widget=AdminRichTextWidget(attrs={'rows': 10}))
    attachments = MultipleFileField(
        required=False,
        widget=MultipleFileInput(attrs={'multiple': True}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'

    def clean_attachments(self):
        files = self.cleaned_data.get('attachments', [])
        allowed_types = {
            'application/pdf',
            'application/msword',
            'application/rtf',
            'application/vnd.ms-excel',
            'application/vnd.ms-powerpoint',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'text/plain',
            'text/csv',
        }
        total_size = 0
        for uploaded_file in files:
            content_type = uploaded_file.content_type or ''
            if not (content_type.startswith(('image/', 'video/')) or content_type in allowed_types):
                raise ValidationError(
                    f'{uploaded_file.name} is not an accepted image, video, PDF, or document file.'
                )
            if uploaded_file.size > 25 * 1024 * 1024:
                raise ValidationError(f'{uploaded_file.name} is larger than the 25 MB limit.')
            total_size += uploaded_file.size
        if total_size > 50 * 1024 * 1024:
            raise ValidationError('The total attachment size cannot exceed 50 MB.')
        return files