# Deployment

## Production environment

Set these variables in the hosting provider's secret/environment settings. Do not commit real values.

```text
DJANGO_SECRET_KEY=<long-random-secret>
DJANGO_ENV=production
DJANGO_DEBUG=False
DJANGO_ADMIN_URL=<random-admin-path>/
DJANGO_ALLOWED_HOSTS=example.com,www.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://example.com,https://www.example.com
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SECURE_COOKIES=True
DJANGO_SECURE_HSTS_SECONDS=31536000
DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=False
DJANGO_SECURE_HSTS_PRELOAD=False
DJANGO_ADVERTISEMENT_ALLOWED_HOSTS=trusted-advertiser.example
DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
DJANGO_EMAIL_HOST=smtp.gmail.com
DJANGO_EMAIL_PORT=587
DJANGO_EMAIL_HOST_USER=afrijobethiopia@gmail.com
DJANGO_EMAIL_HOST_PASSWORD=<gmail-app-password>
DJANGO_EMAIL_USE_TLS=True
DJANGO_DEFAULT_FROM_EMAIL=afrijobethiopia@gmail.com
DJANGO_CACHE_URL=redis://:<password>@<redis-host>:6379/0
DJANGO_RATE_LIMIT_TRUST_X_FORWARDED_FOR=False
DJANGO_AUTH_LOGIN_FAILURE_LIMIT=5
DJANGO_AUTH_LOGIN_FAILURE_WINDOW=900
DJANGO_AUTH_LOGIN_BLOCK_DURATION=900
```

Use the real application domain in `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, and `DJANGO_ADVERTISEMENT_ALLOWED_HOSTS`.
When `DJANGO_DEBUG=False`, HTTPS redirection, secure cookies, and one-year HSTS are enabled by default. Ensure HTTPS is active at the host or reverse proxy; only enable HSTS subdomains or preload after confirming every affected hostname supports HTTPS. The corresponding `DJANGO_SECURE_*` variables can explicitly override these defaults.

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
For HTTP-only local development, keep `DJANGO_SECURE_SSL_REDIRECT=False`,
`DJANGO_SECURE_COOKIES=False`, and `DJANGO_SECURE_HSTS_SECONDS=0`.

In debug mode, the default email backend writes replies to the `sent_emails/` directory
instead of delivering them. To send replies during local development, set the same SMTP
variables shown above, including `DJANGO_EMAIL_BACKEND` and `DJANGO_DEFAULT_FROM_EMAIL`.

## Operational notes

- Back up `db.sqlite3` and the `media/` directory before upgrades.
- Run `python manage.py check --deploy` after changing production environment variables.
- Use a managed database and object storage for production scale.
- Keep admin access behind HTTPS and strong authentication.
- Set `DJANGO_CACHE_URL` to a shared Redis instance in multi-worker deployments so
  rate-limit counters are shared across Gunicorn processes. Without it, local-memory
  caching remains suitable for development and single-process deployments.
- Set `DJANGO_RATE_LIMIT_TRUST_X_FORWARDED_FOR=True` only when the reverse proxy
  overwrites `X-Forwarded-For` and is trusted to provide the client address.
- Password creation and change operations require at least 12 characters and use
  Django's common-password and numeric-password validators.
