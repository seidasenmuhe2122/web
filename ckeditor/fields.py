"""Legacy field import shim for migrations created with django-ckeditor."""

from django.db import models


class RichTextField(models.TextField):
    """Preserve the historical field import without loading CKEditor 4."""
