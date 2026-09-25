import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = "Create or update the admin superuser"

    def handle(self, *args, **options):
        User = get_user_model()

        username = os.environ.get("ADMIN_USERNAME")
        password = os.environ.get("ADMIN_PASSWORD")

        if not username or not password:
            self.stdout.write(
                self.style.WARNING(
                    "ADMIN_USERNAME or ADMIN_PASSWORD is not set."
                )
            )
            return

        user, created = User.objects.get_or_create(
            username=username,
            defaults={"is_staff": True, "is_superuser": True},
        )

        user.set_password(password)
        user.is_staff = True
        user.is_superuser = True
        user.save()

        action = "created" if created else "updated"
        self.stdout.write(
            self.style.SUCCESS(f"Admin user {action} successfully.")
        )