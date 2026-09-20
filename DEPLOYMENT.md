# Deployment

## Production environment

Set these variables in the hosting provider's secret/environment settings. Do not commit real values.

```text
DJANGO_SECRET_KEY=<long-random-secret>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=example.com,www.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://example.com,https://www.example.com
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SECURE_COOKIES=True
DJANGO_SECURE_HSTS_SECONDS=31536000
DJANGO_ADVERTISEMENT_ALLOWED_HOSTS=trusted-advertiser.example
DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
DJANGO_EMAIL_HOST=smtp.gmail.com
DJANGO_EMAIL_PORT=587
DJANGO_EMAIL_HOST_USER=afrijobethiopia@gmail.com
DJANGO_EMAIL_HOST_PASSWORD=<gmail-app-password>
DJANGO_EMAIL_USE_TLS=True
DJANGO_DEFAULT_FROM_EMAIL=afrijobethiopia@gmail.com
```

Use the real application domain in `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, and `DJANGO_ADVERTISEMENT_ALLOWED_HOSTS`.

## Build and start

From the project directory:

```powershell
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py runserver 0.0.0.0:8000
```

For production, put a real WSGI/ASGI server and HTTPS reverse proxy in front of Django. The built-in `runserver` is for development only.

## Local development

```powershell
python manage.py runserver 127.0.0.1:8000
```

Open `http://127.0.0.1:8000/`. Local HTTPS is not enabled by the Django development server.

In debug mode, the default email backend writes replies to the `sent_emails/` directory
instead of delivering them. To send replies during local development, set the same SMTP
variables shown above, including `DJANGO_EMAIL_BACKEND` and `DJANGO_DEFAULT_FROM_EMAIL`.

## Operational notes

- Back up `db.sqlite3` and the `media/` directory before upgrades.
- Run `python manage.py check --deploy` after changing production environment variables.
- Use a managed database and object storage for production scale.
- Keep admin access behind HTTPS and strong authentication.
